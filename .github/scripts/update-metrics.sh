#!/bin/bash

# Metrics tracking script for Claude queue system
# Updates a pinned GitHub issue with queue statistics and analytics

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
METRICS_ISSUE_TITLE="📊 Claude Queue Metrics & Analytics"
METRICS_ISSUE_NUMBER=1  # Will be created if doesn't exist

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

# Get or create metrics issue
get_metrics_issue() {
    check_gh_auth

    # Try to find existing metrics issue
    local existing=$(gh issue list --label "metrics" --search "in:title $METRICS_ISSUE_TITLE" --json number --jq '.[0].number // empty')

    if [ -n "$existing" ]; then
        echo "$existing"
    else
        # Create new metrics issue
        log_info "Creating metrics issue..."
        local new_issue=$(gh issue create \
            --title "$METRICS_ISSUE_TITLE" \
            --label "metrics,documentation" \
            --body "Initializing metrics...")

        # Extract issue number from URL
        local issue_number=$(echo "$new_issue" | grep -oE '[0-9]+$')

        # Pin the issue
        log_info "Pinning metrics issue #${issue_number}"
        gh issue pin "$issue_number" 2>/dev/null || log_warning "Could not pin issue (may require admin rights)"

        echo "$issue_number"
    fi
}

# Collect current queue statistics
collect_stats() {
    check_gh_auth

    local stats_json="{}"

    # Count issues in each state
    local queued=$(gh issue list --label "claude-queue" --json number --jq 'length')
    local in_progress=$(gh issue list --label "claude-in-progress" --json number --jq 'length')
    local pr_created=$(gh issue list --label "claude-pr-created" --json number --jq 'length')
    local failed=$(gh issue list --label "claude-failed" --json number --jq 'length')

    # Get list of in-progress issues
    local in_progress_list=$(gh issue list --label "claude-in-progress" --json number,title --jq '.[] | "#\(.number): \(.title)"' | head -3)

    # Get recent completed PRs (merged claude/* PRs in last 7 days)
    local completed_prs=$(gh pr list --state merged --search "head:claude/ merged:>=$(date -d '7 days ago' +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d)" --json number,title,mergedAt --jq 'length')

    # Get recent failed issues
    local failed_list=$(gh issue list --label "claude-failed" --json number,title --jq '.[] | "- #\(.number): \(.title)"' | head -5)

    # Calculate total processed (approximation based on closed issues with claude labels in last 30 days)
    local total_processed=$(gh issue list --state closed --search "label:claude-in-progress closed:>=$(date -d '30 days ago' +%Y-%m-%d 2>/dev/null || date -v-30d +%Y-%m-%d)" --json number --jq 'length')

    # Export variables
    echo "QUEUED=$queued"
    echo "IN_PROGRESS=$in_progress"
    echo "PR_CREATED=$pr_created"
    echo "FAILED=$failed"
    echo "COMPLETED_LAST_7_DAYS=$completed_prs"
    echo "TOTAL_PROCESSED_30_DAYS=$total_processed"
    echo "IN_PROGRESS_LIST<<EOF"
    echo "$in_progress_list"
    echo "EOF"
    echo "FAILED_LIST<<EOF"
    echo "$failed_list"
    echo "EOF"
}

# Generate metrics report
generate_report() {
    local queued=$1
    local in_progress=$2
    local pr_created=$3
    local failed=$4
    local completed_7d=$5
    local total_30d=$6
    local in_progress_list=$7
    local failed_list=$8

    # Calculate success rate
    local total_attempts=$((completed_7d + failed))
    local success_rate=0
    if [ $total_attempts -gt 0 ]; then
        success_rate=$((completed_7d * 100 / total_attempts))
    fi

    # Get current timestamp
    local timestamp=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

    cat <<EOF
# 📊 Claude Queue Metrics & Analytics

Last updated: **${timestamp}**

---

## Current Queue Status

| State | Count | Description |
|-------|-------|-------------|
| 🟦 Queued | **${queued}** | Issues waiting to be processed |
| 🟨 In Progress | **${in_progress}** | Currently being worked on (max 3) |
| 🟩 PR Created | **${pr_created}** | Pull requests awaiting review |
| 🟥 Failed | **${failed}** | Issues that failed processing |

---

## Currently Processing

$(if [ -n "$in_progress_list" ]; then
    echo "$in_progress_list"
else
    echo "_No issues currently in progress_"
fi)

---

## Statistics (Last 30 Days)

- **Total Processed:** ${total_30d} issues
- **Completed (Last 7 Days):** ${completed_7d} PRs merged
- **Success Rate:** ${success_rate}% (based on last 7 days)
- **Failed Issues:** ${failed} (see below)

---

## Failed Issues (Needs Attention)

$(if [ -n "$failed_list" ]; then
    echo "$failed_list"
else
    echo "_No failed issues_"
fi)

$(if [ $failed -gt 0 ]; then
    echo ""
    echo "⚠️ **Action Required:** Review failed issues above and either:"
    echo "- Fix the issue description and re-add \`claude-queue\` label"
    echo "- Handle manually and close the issue"
fi)

---

## How to Use the Queue

1. **Add to Queue:** Label an issue with \`claude-queue\`
2. **Automatic Processing:** Claude processes up to 3 issues concurrently
3. **Conflict Detection:** System checks for conflicts before starting work
4. **PR Creation:** Creates pull request for review (not direct commits)
5. **Auto-Progress:** Moves to next issue after PR merge/close

---

## Queue Configuration

- **Max Concurrent Issues:** 3
- **Timeout:** 24 hours per issue
- **Failure Policy:** Fail fast (1 attempt, then mark as failed)
- **Conflict Detection:** Blocks processing if version (config.json) conflicts detected

---

_This issue is automatically updated by the metrics tracking system._
_For questions or issues, check the [GitHub Actions logs](../../actions)._
EOF
}

# Main execution
main() {
    log_info "Collecting queue metrics..."

    # Get or create metrics issue
    ISSUE_NUMBER=$(get_metrics_issue)
    log_info "Using metrics issue #${ISSUE_NUMBER}"

    # Collect statistics
    eval "$(collect_stats)"

    # Generate report
    REPORT=$(generate_report \
        "${QUEUED:-0}" \
        "${IN_PROGRESS:-0}" \
        "${PR_CREATED:-0}" \
        "${FAILED:-0}" \
        "${COMPLETED_LAST_7_DAYS:-0}" \
        "${TOTAL_PROCESSED_30_DAYS:-0}" \
        "${IN_PROGRESS_LIST:-}" \
        "${FAILED_LIST:-}")

    # Update issue
    log_info "Updating metrics issue..."
    echo "$REPORT" | gh issue edit "$ISSUE_NUMBER" --body-file -

    log_success "Metrics updated successfully in issue #${ISSUE_NUMBER}"
}

# Run main function
main
