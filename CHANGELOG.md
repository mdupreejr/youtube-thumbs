## 1.15.1 - 2025-10-28

### Fixed
- Fixed critical rating score logic bug that incorrectly calculated score transitions
  - When users changed ratings (e.g., like to dislike), the score wasn't properly updated
  - Now correctly accounts for the previous rating when calculating score changes
- Fixed all parameter naming inconsistencies
  - All database methods now consistently use `yt_video_id` parameter instead of `video_id`
  - Makes codebase more maintainable and less confusing
- Updated documentation with correct field names in SQL examples
- Removed potentially unsafe SQL string interpolation patterns

### Improved
- Consistent parameter naming throughout entire codebase
- Better code clarity and maintainability
- Safer SQL query construction

### Technical
- All database method parameters renamed from `video_id` to `yt_video_id`
- Updated all calling code in app.py, history_tracker.py, and import_youtube_exports.py
- Cleaned up leftover test processes from development

## 1.15.0 - 2025-10-28

### Changed
- **BREAKING CHANGE**: Complete database schema overhaul for consistency
- All YouTube fields now use `yt_` prefix (e.g., `video_id` → `yt_video_id`)
- All Home Assistant fields use `ha_` prefix for clarity
- Renamed `youtube_url` to `yt_url` for consistency
- Removed redundant `date_updated` column (using `date_last_played` only)
- Renamed `rating_count` to `rating_score` with proper +1/-1 scoring system

### Improved
- Rating system now uses cumulative scoring: +1 for like, -1 for dislike
- Videos can now have negative scores if disliked more than liked
- Cleaner, more consistent field naming throughout codebase

### Technical
- Updated all SQL queries and database methods to use new field names
- Updated all Python modules to use consistent field references
- Fixed pending_ratings table to use `yt_video_id` consistently
- Fixed import_history table to use `yt_video_id` consistently

### Note
- **Database Reset Required**: Delete `/config/youtube_thumbs/ratings.db` before updating
- The database will be recreated automatically with the new schema
- All existing data will be lost - export any important data before updating

## 1.14.1 - 2025-10-28

### Note
- Checkpoint release before major schema refactoring
- Preparing for consistent field naming and removal of redundant columns

## 1.14.0 - 2025-10-28

### Added
- Capture ALL YouTube metadata without additional API calls
- New database columns for rich YouTube data:
  - `yt_channel_id` - Unique channel identifier
  - `yt_description` - Full video description
  - `yt_published_at` - When video was published
  - `yt_category_id` - YouTube category (10=Music, etc)
  - `yt_live_broadcast` - Live content status
  - `yt_location` - Recording location (if available)
  - `yt_recording_date` - When video was recorded (if available)
- Added indexes on yt_channel_id and yt_category_id for faster queries

### Changed
- YouTube API now requests all available snippet fields
- Added recordingDetails to API parts for location/date data
- No increase in API quota usage - same single API call

### Technical
- Expanded VIDEO_FIELDS to include all snippet and recordingDetails fields
- Updated _timestamp() to handle None values for optional fields
- All modules updated to pass through new metadata fields

## 1.13.2 - 2025-10-28

### Changed
- Removed all database migration logic - fresh start approach
- Simplified database initialization code
- Cleaner codebase without complex migration handling

### Removed
- `_rebuild_video_ratings_schema_if_needed()` method
- `_cleanup_pending_metadata()` method
- `_add_column_if_missing()` method
- All backward compatibility migration code

### Note
- Delete `/config/youtube_thumbs/ratings.db` before updating for a clean start
- Database will be recreated with the new schema automatically

## 1.13.1 - 2025-10-28

### Changed
- Renamed database column `channel` to `yt_channel` for consistency (ha_* for Home Assistant, yt_* for YouTube)
- Removed redundant `yt_artist` column (was always identical to channel/yt_channel)
- Cleaner schema with no duplicate data storage

### Fixed
- Database migration now properly handles the column rename
- Removed confusion about artist data (only comes from Home Assistant, not YouTube)

### Technical Details
- YouTube API only provides channel name, not artist information
- Artist information exclusively comes from Home Assistant media player
- Schema now clearly differentiates data sources with consistent naming

## 1.13.0 - 2025-10-28

### Added
- Comprehensive startup health checks for all components
- On startup, addon now tests:
  - Home Assistant API connectivity and media player status
  - YouTube API authentication and quota availability
  - Database connectivity and shows video count statistics
- Detailed status report in logs showing what's working and what's not
- Shows recent plays and pending ratings count in database check

### Changed
- Improved startup logging with clear status indicators (✓/✗/⚠)
- Better error messages when components aren't configured properly

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
