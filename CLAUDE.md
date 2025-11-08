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

When addressing issues or making changes:

1. **Read and understand** the issue or request thoroughly
2. **Make the necessary code changes**
3. **Bump the version** in `config.json` appropriately
4. **Test if possible** (check for syntax errors, validate JSON, etc.)
5. **Commit all changes** with the proper commit message format
6. **Push the changes** to the repository

### Standard Git Commands
```bash
# Stage all changes
git add .

# Commit with proper format
git commit -m "$(cat <<'EOF'
v1.51.3: Brief description

- Change detail 1
- Change detail 2

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"

# Push to remote
git push
```

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

When working on tagged GitHub issues:
- Read the entire issue description and any comments
- Ask clarifying questions if requirements are unclear
- Reference the issue number in commits when relevant
- Provide clear explanations of changes made
- Update the issue with progress or completion status
- Always pull latest code before starting work!