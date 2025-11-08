#!/bin/bash

# Helper script for managing Claude's GitHub issue queue
# This script provides functions to find, update, and manage issues in the queue

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Labels used by the queue system
LABEL_QUEUE="claude-queue"
LABEL_IN_PROGRESS="claude-in-progress"
LABEL_PR_CREATED="claude-pr-created"
LABEL_FAILED="claude-failed"

# Configuration
MAX_CONCURRENT=3
TIMEOUT_HOURS=24

# Function to print colored messages
log_info() {
    echo -e "${BLUE}ℹ ${1}${NC}"
}

log_success() {
    echo -e "${GREEN}✓ ${1}${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠ ${1}${NC}"
}

log_error() {
    echo -e "${RED}✗ ${1}${NC}"
}

# Check if gh CLI is authenticated
check_gh_auth() {
    if ! gh auth status &>/dev/null; then
        log_error "GitHub CLI is not authenticated"
        exit 1
    fi
}

# Find issue currently in progress (returns first one)
get_in_progress_issue() {
    check_gh_auth
    local issue_number=$(gh issue list --label "$LABEL_IN_PROGRESS" --json number --jq '.[0].number // empty')
    echo "$issue_number"
}

# Find ALL issues currently in progress (for parallel processing)
get_all_in_progress() {
    check_gh_auth
    gh issue list --label "$LABEL_IN_PROGRESS" --json number --jq '.[].number'
}

# Count how many issues are currently in progress
count_in_progress() {
    check_gh_auth
    gh issue list --label "$LABEL_IN_PROGRESS" --json number --jq 'length'
}

# Find next issue in queue (sorted by issue number, oldest first)
get_next_queued_issue() {
    check_gh_auth
    local issue_number=$(gh issue list --label "$LABEL_QUEUE" --json number --jq 'sort_by(.number) | .[0].number // empty')
    echo "$issue_number"
}

# Check if an issue exists and get its details
get_issue_details() {
    local issue_number=$1
    check_gh_auth
    gh issue view "$issue_number" --json number,title,body,labels,url
}

# Check if a PR exists for an issue
get_pr_for_issue() {
    local issue_number=$1
    check_gh_auth
    # Search for PRs that mention the issue number in the body
    local pr_number=$(gh pr list --search "issue #${issue_number}" --json number --jq '.[0].number // empty')
    echo "$pr_number"
}

# Check if a PR is merged or closed
check_pr_status() {
    local pr_number=$1
    check_gh_auth
    local state=$(gh pr view "$pr_number" --json state --jq '.state')
    echo "$state"
}

# Add a label to an issue
add_label() {
    local issue_number=$1
    local label=$2
    check_gh_auth
    log_info "Adding label '${label}' to issue #${issue_number}"
    gh issue edit "$issue_number" --add-label "$label"
    log_success "Label added"
}

# Remove a label from an issue
remove_label() {
    local issue_number=$1
    local label=$2
    check_gh_auth
    log_info "Removing label '${label}' from issue #${issue_number}"
    gh issue edit "$issue_number" --remove-label "$label"
    log_success "Label removed"
}

# Remove all Claude queue labels from an issue
remove_all_queue_labels() {
    local issue_number=$1
    check_gh_auth
    log_info "Removing all queue labels from issue #${issue_number}"
    gh issue edit "$issue_number" --remove-label "$LABEL_QUEUE" --remove-label "$LABEL_IN_PROGRESS" --remove-label "$LABEL_PR_CREATED" 2>/dev/null || true
    log_success "Queue labels removed"
}

# Post a comment on an issue
post_comment() {
    local issue_number=$1
    local comment=$2
    check_gh_auth
    log_info "Posting comment to issue #${issue_number}"
    gh issue comment "$issue_number" --body "$comment"
    log_success "Comment posted"
}

# Start processing an issue (add in-progress label and post comment)
start_processing() {
    local issue_number=$1
    check_gh_auth
    log_info "Starting to process issue #${issue_number}"

    # Remove queue label, add in-progress label
    remove_label "$issue_number" "$LABEL_QUEUE"
    add_label "$issue_number" "$LABEL_IN_PROGRESS"

    # Post comment
    post_comment "$issue_number" "🤖 Claude is starting work on this issue..."

    log_success "Issue #${issue_number} marked as in progress"
}

# Mark issue as having PR created
mark_pr_created() {
    local issue_number=$1
    local pr_number=$2
    check_gh_auth
    log_info "Marking issue #${issue_number} as having PR created"

    # Add pr-created label
    add_label "$issue_number" "$LABEL_PR_CREATED"

    # Post comment with PR link
    post_comment "$issue_number" "🤖 Pull request #${pr_number} has been created for review. Once merged or closed, I'll move to the next issue in the queue."

    log_success "Issue #${issue_number} marked with PR created"
}

# Complete processing (remove all labels when PR is merged/closed)
complete_processing() {
    local issue_number=$1
    check_gh_auth
    log_info "Completing processing for issue #${issue_number}"

    # Remove all queue labels
    remove_all_queue_labels "$issue_number"

    # Post completion comment
    post_comment "$issue_number" "🤖 PR has been merged/closed. Moving to the next issue in the queue."

    log_success "Issue #${issue_number} processing completed"
}

# Generate a branch name from issue number and title
generate_branch_name() {
    local issue_number=$1
    local issue_title=$2

    # Slugify the title: lowercase, replace spaces/special chars with hyphens, remove consecutive hyphens
    local slug=$(echo "$issue_title" | tr '[:upper:]' '[:lower:]' | sed -e 's/[^a-z0-9]/-/g' -e 's/--*/-/g' -e 's/^-//' -e 's/-$//' | cut -c1-50)

    echo "claude/issue-${issue_number}-${slug}"
}

# Mark issue as failed
mark_failed() {
    local issue_number=$1
    local reason=$2
    check_gh_auth
    log_error "Marking issue #${issue_number} as failed"

    # Remove queue labels and add failed label
    remove_all_queue_labels "$issue_number"
    add_label "$issue_number" "$LABEL_FAILED"

    # Post failure comment
    post_comment "$issue_number" "❌ Claude failed to process this issue.

**Reason:** ${reason}

The issue has been marked as \`claude-failed\` and removed from the queue. Please review the error and either:
- Fix the issue description and re-add \`claude-queue\` label to retry
- Handle this issue manually

Check the GitHub Actions logs for more details."

    log_error "Issue #${issue_number} marked as failed"
}

# Check if an issue has timed out (been in-progress too long)
check_timeout() {
    local issue_number=$1
    check_gh_auth

    # Get when the issue was last updated
    local updated_at=$(gh issue view "$issue_number" --json updatedAt --jq '.updatedAt')

    # Convert to epoch time
    local updated_epoch=$(date -d "$updated_at" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$updated_at" +%s 2>/dev/null)
    local now_epoch=$(date +%s)
    local diff_hours=$(( (now_epoch - updated_epoch) / 3600 ))

    if [ $diff_hours -ge $TIMEOUT_HOURS ]; then
        echo "timeout"
    else
        echo "ok"
    fi
}

# Get list of files changed in a PR
get_file_changes() {
    local pr_number=$1
    check_gh_auth
    gh pr view "$pr_number" --json files --jq '.files[].path'
}

# Get all open PRs (returns list of PR numbers)
get_open_prs() {
    check_gh_auth
    gh pr list --state open --json number --jq '.[].number'
}

# Detect if an issue conflicts with open PRs
detect_conflicts() {
    local issue_number=$1
    check_gh_auth

    log_info "Checking for conflicts with open PRs..." >&2

    # Get issue details
    local issue_body=$(gh issue view "$issue_number" --json body --jq '.body // ""')
    local issue_title=$(gh issue view "$issue_number" --json title --jq '.title // ""')

    # Combine title and body for searching
    local issue_text="${issue_title} ${issue_body}"

    # Get all open PRs
    local open_prs=$(get_open_prs)

    if [ -z "$open_prs" ]; then
        log_info "No open PRs, no conflicts" >&2
        echo "no-conflicts"
        return 0
    fi

    # Check if any open PR modifies config.json (version conflict risk)
    for pr in $open_prs; do
        local files=$(get_file_changes "$pr")
        if echo "$files" | grep -q "config.json"; then
            log_warning "PR #${pr} modifies config.json (version conflict risk)" >&2
            echo "conflict-version:${pr}"
            return 1
        fi
    done

    # Extract potential file/directory mentions from issue text
    # Look for common patterns: path/to/file, file.ext, mentions in code blocks
    local mentioned_files=$(echo "$issue_text" | grep -oE '(\w+/)+\w+\.\w+|\b\w+\.(py|js|sh|yml|yaml|json|md)\b' | sort -u)

    if [ -z "$mentioned_files" ]; then
        log_info "No specific files mentioned in issue, assuming no conflicts" >&2
        echo "no-conflicts"
        return 0
    fi

    # Check each open PR for file conflicts
    for pr in $open_prs; do
        local pr_files=$(get_file_changes "$pr")

        for mentioned in $mentioned_files; do
            if echo "$pr_files" | grep -q "$mentioned"; then
                log_warning "Potential conflict: PR #${pr} modifies ${mentioned}" >&2
                echo "conflict-file:${pr}:${mentioned}"
                return 1
            fi
        done
    done

    log_success "No conflicts detected" >&2
    echo "no-conflicts"
    return 0
}

# Get repository owner
get_repo_owner() {
    check_gh_auth
    gh repo view --json owner --jq '.owner.login'
}

# Assign issue to repository owner
assign_to_owner() {
    local issue_number=$1
    check_gh_auth

    local owner=$(get_repo_owner)
    log_info "Assigning issue #${issue_number} to ${owner}"
    gh issue edit "$issue_number" --add-assignee "$owner"
    log_success "Issue assigned"
}

# Main command dispatcher
case "${1:-help}" in
    get-in-progress)
        issue=$(get_in_progress_issue)
        if [ -n "$issue" ]; then
            echo "$issue"
            exit 0
        else
            log_warning "No issue currently in progress"
            exit 1
        fi
        ;;

    get-next-queued)
        issue=$(get_next_queued_issue)
        if [ -n "$issue" ]; then
            echo "$issue"
            exit 0
        else
            log_warning "No issues in queue"
            exit 1
        fi
        ;;

    start-processing)
        if [ -z "$2" ]; then
            log_error "Usage: $0 start-processing <issue_number>"
            exit 1
        fi
        start_processing "$2"
        ;;

    mark-pr-created)
        if [ -z "$2" ] || [ -z "$3" ]; then
            log_error "Usage: $0 mark-pr-created <issue_number> <pr_number>"
            exit 1
        fi
        mark_pr_created "$2" "$3"
        ;;

    complete)
        if [ -z "$2" ]; then
            log_error "Usage: $0 complete <issue_number>"
            exit 1
        fi
        complete_processing "$2"
        ;;

    get-pr-status)
        if [ -z "$2" ]; then
            log_error "Usage: $0 get-pr-status <pr_number>"
            exit 1
        fi
        check_pr_status "$2"
        ;;

    generate-branch)
        if [ -z "$2" ] || [ -z "$3" ]; then
            log_error "Usage: $0 generate-branch <issue_number> <issue_title>"
            exit 1
        fi
        generate_branch_name "$2" "$3"
        ;;

    get-all-in-progress)
        get_all_in_progress
        ;;

    count-in-progress)
        count_in_progress
        ;;

    mark-failed)
        if [ -z "$2" ] || [ -z "$3" ]; then
            log_error "Usage: $0 mark-failed <issue_number> <reason>"
            exit 1
        fi
        mark_failed "$2" "$3"
        ;;

    check-timeout)
        if [ -z "$2" ]; then
            log_error "Usage: $0 check-timeout <issue_number>"
            exit 1
        fi
        check_timeout "$2"
        ;;

    detect-conflicts)
        if [ -z "$2" ]; then
            log_error "Usage: $0 detect-conflicts <issue_number>"
            exit 1
        fi
        detect_conflicts "$2"
        ;;

    get-file-changes)
        if [ -z "$2" ]; then
            log_error "Usage: $0 get-file-changes <pr_number>"
            exit 1
        fi
        get_file_changes "$2"
        ;;

    get-open-prs)
        get_open_prs
        ;;

    get-repo-owner)
        get_repo_owner
        ;;

    assign-to-owner)
        if [ -z "$2" ]; then
            log_error "Usage: $0 assign-to-owner <issue_number>"
            exit 1
        fi
        assign_to_owner "$2"
        ;;

    help|*)
        cat <<EOF
Claude Queue Management Helper Script

Usage: $0 <command> [arguments]

Commands:
  # Queue Management
  get-in-progress              Get the first issue being processed
  get-all-in-progress          Get all issues currently being processed
  count-in-progress            Count how many issues are in progress
  get-next-queued              Get the next issue number in the queue
  start-processing <issue>     Mark an issue as in-progress and post start comment
  mark-pr-created <issue> <pr> Mark that a PR has been created for an issue
  complete <issue>             Mark processing complete and remove labels

  # Error Handling
  mark-failed <issue> <reason> Mark an issue as failed and remove from queue
  check-timeout <issue>        Check if issue has timed out (>24h in progress)

  # Conflict Detection
  detect-conflicts <issue>     Check if issue conflicts with open PRs
  get-file-changes <pr>        Get list of files changed in a PR
  get-open-prs                 Get list of all open PR numbers

  # Assignment
  get-repo-owner               Get the repository owner username
  assign-to-owner <issue>      Assign issue to repository owner

  # Utilities
  get-pr-status <pr>           Get the status of a PR (OPEN, MERGED, CLOSED)
  generate-branch <issue> <title>  Generate a branch name for an issue
  help                         Show this help message

Labels used:
  $LABEL_QUEUE         - Issue is waiting in queue
  $LABEL_IN_PROGRESS   - Issue is currently being processed
  $LABEL_PR_CREATED    - PR has been created for this issue
  $LABEL_FAILED        - Issue failed processing

Configuration:
  MAX_CONCURRENT=$MAX_CONCURRENT       - Maximum concurrent issues
  TIMEOUT_HOURS=$TIMEOUT_HOURS      - Hours before issue times out

Examples:
  $0 count-in-progress
  $0 detect-conflicts 123
  $0 mark-failed 123 "Syntax error in code"
  $0 assign-to-owner 123

EOF
        ;;
esac
