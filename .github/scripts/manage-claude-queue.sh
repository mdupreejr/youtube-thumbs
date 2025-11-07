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

# Find issue currently in progress
get_in_progress_issue() {
    check_gh_auth
    local issue_number=$(gh issue list --label "$LABEL_IN_PROGRESS" --json number --jq '.[0].number // empty')
    echo "$issue_number"
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

    help|*)
        cat <<EOF
Claude Queue Management Helper Script

Usage: $0 <command> [arguments]

Commands:
  get-in-progress              Get the issue number currently being processed (if any)
  get-next-queued              Get the next issue number in the queue
  start-processing <issue>     Mark an issue as in-progress and post start comment
  mark-pr-created <issue> <pr> Mark that a PR has been created for an issue
  complete <issue>             Mark processing complete and remove labels
  get-pr-status <pr>           Get the status of a PR (OPEN, MERGED, CLOSED)
  generate-branch <issue> <title>  Generate a branch name for an issue
  help                         Show this help message

Labels used:
  $LABEL_QUEUE         - Issue is waiting in queue
  $LABEL_IN_PROGRESS   - Issue is currently being processed
  $LABEL_PR_CREATED    - PR has been created for this issue

Examples:
  $0 get-next-queued
  $0 start-processing 123
  $0 mark-pr-created 123 456
  $0 complete 123
  $0 generate-branch 123 "Fix database migration error"

EOF
        ;;
esac
