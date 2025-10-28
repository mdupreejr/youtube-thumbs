## 1.12.4 - 2025-10-28

### Fixed
- Improved history tracker logging to show when it's actively polling
- Added log message when new media is detected
- Reduced log verbosity for routine polling operations

### Changed
- Home Assistant API polling now logs at DEBUG level instead of INFO
- Media player state changes now log at DEBUG level instead of WARNING
- Added periodic heartbeat logging every 10 polls to confirm tracker is running
- History tracker now logs when media starts/stops playing at INFO level

## 1.12.3 - 2025-10-28

### Fixed
- Fixed database schema migration that was incorrectly rebuilding on every restart
- The migration now properly handles missing columns and deprecated columns
- Schema rebuild will only occur once when actually needed, not repeatedly

### Technical Details
- Dynamic column detection prevents trying to select non-existent columns during migration
- Properly excludes deprecated columns (yt_channel, ha_channel) from migration
- Adds proper defaults for new columns that don't exist in old schema

## 1.12.2 - 2025-10-28

### Fixed
- Enhanced troubleshooting documentation for missing YouTube API credentials issue
- Added clear instructions for when videos aren't being added to the database
- Improved credential setup documentation in README

### Documentation
- Added "No new videos being added to database" as the first troubleshooting item
- Clarified that both `credentials.json` and `token.pickle` are required for authentication
- Added specific log messages to look for when diagnosing credential issues

## 1.12.1 - 2025-10-26

### Fixed
- Resolved a regression in the history tracker that caused the add-on to crash at startup due to a stray block executing during module import.

## 1.12.0 - 2025-10-26

### Added
- Queue thumbs requests when YouTube’s API/quota is unavailable and retry automatically once access returns.
- `pending_ratings` and `import_history` tables to keep track of queued ratings and imported exports.
- `force_quota_unlock` option to drop the quota guard file at startup when you know the API is available again.
- `import_youtube_exports.py` helper plus docs for ingesting Google “My Activity” / watch-history HTML files with `source='yt_export'` metadata.

### Changed
- Default history tracker poll interval increased to 60 seconds to reduce API chatter.
- YouTube search requests trimmed (smaller `fields`, fewer candidates) to conserve quota.
- README updated with new workflow details and data-import instructions.

### Fixed
- Ratings are now recorded locally even when YouTube is offline, guaranteeing every thumbs event is logged.
