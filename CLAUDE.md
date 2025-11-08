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

### Working with @claude Mentions

Claude is triggered by mentioning `@claude` in issues, pull requests, or comments. When you @mention Claude:

1. **Claude reads** the issue/PR and all context
2. **Makes necessary code changes** directly in the repository
3. **Commits changes** with proper formatting
4. **Creates a Pull Request** (if working on an issue) or updates existing PR

### PR-Based Workflow

**IMPORTANT:** All changes MUST be submitted via Pull Requests. DO NOT push directly to master.

When Claude processes an issue:

1. **Reads and understands** the issue or request thoroughly
2. **Makes the necessary code changes**
3. **Bumps the version** in `config.json` appropriately
4. **Tests if possible** (checks for syntax errors, validates JSON, etc.)
5. **Creates a new branch** with the format: `claude/issue-{number}-{title-slug}`
6. **Commits changes** to the new branch with proper commit message format
7. **Pushes the branch** to origin
8. **Creates a Pull Request** linking back to the original issue

### How to Use

Simply comment `@claude` on any issue when you're ready for it to be processed:
- Add context in your comment about what needs to be done
- Claude will respond and make the necessary changes
- Review the PR Claude creates before merging

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

### Working with Claude on Issues

When you have an issue that needs work:

1. **Comment with @claude** on the issue
2. **Add context** - Explain what needs to be done (Claude reads the full issue too)
3. **Claude responds** and begins working
4. **Claude creates a PR** when done
5. **Review and merge** the PR

### Best Practices

- **Be Specific:** Clearly describe what needs to change in your @claude comment
- **One Thing at a Time:** Focus each issue on a single concern
- **Review PRs:** Always review Claude's changes before merging
- **Provide Feedback:** If the solution isn't quite right, comment on the PR with guidance

### Optional Labels for Organization

You can use labels to organize issues:
- `claude-queue` - Issues waiting for you to @mention Claude
- `documentation` - Documentation improvements
- `bug` - Bug fixes
- `enhancement` - New features or improvements

### Helper Utilities Available

The repository includes useful utilities in `.github/scripts/`:
- `manage-claude-queue.sh` - Helper functions for issue management
- `update-metrics.sh` - Generate metrics reports about issue processing

These can be run manually if needed for reporting or management.
