# Claude Instructions for YouTube Thumbs Rating

This document provides guidance for Claude when working on this Home Assistant addon project.

## Project Overview

YouTube Thumbs Rating is a Home Assistant addon that allows users to rate YouTube videos (thumbs up/down) for songs playing on AppleTV through Home Assistant.

## Version Management

### Version Location
The version is stored in `config.json` at line 3:
```json
"version": "1.51.2"
```

### Semantic Versioning
Follow semantic versioning (MAJOR.MINOR.PATCH):
- **MAJOR**: Breaking changes or major feature overhauls
- **MINOR**: New features, enhancements, or significant improvements (backward compatible)
- **PATCH**: Bug fixes, small improvements, documentation updates

### When to Bump Versions
**ALWAYS bump the version** when making changes to:
- Source code (Python files, JavaScript, etc.)
- Configuration files
- Database schema
- Dependencies
- Features or bug fixes

**Determine the appropriate version bump:**
- Bug fixes and small improvements → PATCH (1.51.2 → 1.51.3)
- New features or enhancements → MINOR (1.51.2 → 1.52.0)
- Breaking changes → MAJOR (1.51.2 → 2.0.0)

### Version Bumping Process
1. Update the `version` field in `config.json`
2. Ensure the version follows semantic versioning
3. Include the version in your commit message

## Commit Message Format

Use this standardized format for all commits:

```
v{VERSION}: Brief description of the change

- Detailed bullet point explaining change 1
- Detailed bullet point explaining change 2
- Additional context if needed

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### Commit Message Examples

**For a bug fix (PATCH):**
```
v1.51.3: Fix database migration error

- Fixed NOT NULL constraint error during schema updates
- Added proper default values for new columns
- Improved error handling in migration script

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**For a new feature (MINOR):**
```
v1.52.0: Add bulk video retry functionality

- Implemented batch processing for pending videos
- Added configurable retry batch size option
- Improved quota management for retries

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

## Git Workflow

### Queue-Based Processing

Issues are processed through a queue system using GitHub labels:
- **`claude-queue`** - Issue is waiting to be processed
- **`claude-in-progress`** - Currently being worked on
- **`claude-pr-created`** - Pull request has been created, awaiting review

Only ONE issue is processed at a time. When a PR is merged or closed, the system automatically moves to the next queued issue.

### PR-Based Workflow

**IMPORTANT:** All changes MUST be submitted via Pull Requests. DO NOT push directly to master.

When processing an issue from the queue:

1. **Read and understand** the issue or request thoroughly
2. **Make the necessary code changes**
3. **Bump the version** in `config.json` appropriately
4. **Test if possible** (check for syntax errors, validate JSON, etc.)
5. **Create a new branch** with the format: `claude/issue-{number}-{title-slug}`
6. **Commit changes** to the new branch with proper commit message format
7. **Push the branch** to origin
8. **Create a Pull Request** linking back to the original issue

### Git Commands for PR Workflow

```bash
# Create and checkout new branch (name will be provided by workflow)
git checkout -b claude/issue-123-fix-database-error

# Stage all changes
git add .

# Commit with proper format
git commit -m "$(cat <<'EOF'
v3.40.0: Fix database migration error

- Fixed NOT NULL constraint error during schema updates
- Added proper default values for new columns
- Improved error handling in migration script

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"

# Push branch to remote
git push -u origin claude/issue-123-fix-database-error

# Create pull request (linking to the issue)
gh pr create \
  --base master \
  --head claude/issue-123-fix-database-error \
  --title "v3.40.0: Fix database migration error" \
  --body "Fixes #123

## Summary
- Fixed NOT NULL constraint error during schema updates
- Added proper default values for new columns
- Improved error handling in migration script

## Testing
- Validated JSON syntax
- Checked Python code for errors
- Tested migration logic

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

### Important Notes

- **Never push directly to master** - Always create a PR
- **Include issue reference** - Use "Fixes #123" in PR description
- **Wait for merge** - The queue system won't process the next issue until the current PR is merged or closed
- **Branch naming** - Follow the format: `claude/issue-{number}-{title-slug}`

## Code Style and Conventions

- Follow existing code style and patterns in the repository
- Use descriptive variable and function names
- Add comments for complex logic
- Validate JSON files after editing
- Check Python syntax before committing

## Testing Guidelines

- Validate JSON configuration files
- Check for Python syntax errors
- Ensure database migrations are reversible
- Test rate limiting logic carefully
- Verify Home Assistant API integrations

## Important Files

- `config.json` - Addon configuration and version
- `run.sh` - Main startup script
- Database schema files - Handle migrations carefully
- Home Assistant integration code - Test with HA API

## Notes for GitHub Issues

### How the Queue System Works

#### Smart Parallel Processing (Up to 3 Concurrent Issues)

The queue system can process up to **3 issues simultaneously** using intelligent conflict detection:

1. **Adding to Queue:** Label an issue with `claude-queue` to add it to the processing queue
2. **Smart Processing:** The system:
   - Processes issues in order by issue number (oldest first)
   - Can work on up to 3 issues concurrently
   - Runs **conflict detection** before starting each issue
   - Only processes issues that won't conflict with active PRs
   - Automatically skips conflicting issues and tries the next one
3. **Status Updates:** The system automatically:
   - Assigns issue to repository owner
   - Adds `claude-in-progress` label when work begins
   - Posts a comment when starting work
   - Creates a pull request with review request when work is complete
   - Adds `claude-pr-created` label and posts PR link
   - Removes all labels when PR is merged/closed
   - Moves to next issues in queue automatically

#### Conflict Detection

Before processing an issue, the system checks:
- **Version Conflicts:** If any open PR modifies `config.json`, blocks processing to avoid version conflicts
- **File Conflicts:** Scans issue description for file mentions and checks against files changed in open PRs
- **Smart Queuing:** If conflicts detected, skips that issue and tries the next queued issue

This allows the system to safely process multiple non-conflicting issues in parallel!

#### Error Handling & Timeout Protection

- **Fail-Fast Policy:** If processing fails, issue is immediately marked as `claude-failed` and removed from queue
- **Timeout Protection:** Issues in-progress for >24 hours are automatically failed
- **Auto-Recovery:** Queue checks run hourly to recover from missed events
- **Branch Cleanup:** Merged PR branches are automatically deleted

### When Working on Issues

- Read the entire issue description and any comments carefully
- Ask clarifying questions if requirements are unclear
- Reference the issue number in PR title and body (use "Fixes #123")
- Provide clear explanations of changes in the PR description
- The PR will be reviewed by a human before merging
- Once merged, the system automatically processes the next queued issue

### Queue Labels

The system uses these labels to track issue status:
- `claude-queue` - Issue is waiting to be processed
- `claude-in-progress` - Issue is currently being worked on (max 3 at a time)
- `claude-pr-created` - Pull request has been created, awaiting review
- `claude-failed` - Issue failed processing and needs attention

### Metrics Dashboard

Track queue performance and status in the **📊 Claude Queue Metrics & Analytics** issue (pinned):
- Current queue status (queued, in-progress, failed)
- Processing statistics (success rate, total processed)
- Recent activity and completed PRs
- Failed issues requiring attention

The dashboard updates automatically after each queue action.

### For Direct Assistance (Not Queued)

You can still mention @claude in PR comments or review comments for immediate assistance without going through the queue system. This is useful for:
- Requesting changes to an existing PR
- Getting help with code reviews
- Quick questions or clarifications
