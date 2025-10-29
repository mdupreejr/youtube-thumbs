## 1.20.0 - 2025-10-29

### Security - CRITICAL
- **SQL Injection Prevention**: Added regex validation for timestamp format to prevent SQL injection attacks
- **Race Condition Fix**: Implemented file locking (fcntl) in QuotaGuard to prevent concurrent access corruption
- **Data Validation**: Added comprehensive validation for YouTube API responses:
  - Video IDs must be exactly 11 alphanumeric characters
  - Descriptions automatically truncated to 5000 characters
  - Duration validated (0-86400 seconds max)

### Fixed
- Timestamp strings now validated before use in SQL queries
- State file operations in QuotaGuard are now atomic with exclusive locking
- Invalid YouTube video data rejected before database insertion
- Memory exhaustion prevented from extremely long video descriptions

### Technical
- Added `_validate_video_id()` method with regex pattern validation
- Added `_validate_and_truncate_description()` to prevent memory issues
- Added `_validate_duration()` with reasonable bounds checking
- Implemented fcntl.LOCK_EX for exclusive file locking in record_success()
- Timestamp validation pattern: `^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}`

## 1.19.0 - 2025-10-29

### Added
- **Phase 4: Exponential Backoff for Quota Recovery** - Better recovery from API quota exhaustion
- Progressive cooldown periods: 2h → 4h → 8h → 16h → 24h (max)
- Success tracking to reset attempt counter after 10 successful API calls
- Automatic attempt counter reset after recovery period

### Changed
- Default cooldown reduced from 12h to 2h (first attempt)
- Quota guard now tracks attempt numbers and success counts
- Added detailed backoff information in error messages
- YouTube API now records successful calls for recovery tracking

### Performance
- Smarter quota recovery with exponential backoff prevents premature retries
- Successful API usage automatically reduces future cooldown periods
- Better resilience against repeated quota exhaustion

### Technical
- `QuotaGuard` class now implements exponential backoff algorithm
- New `BACKOFF_PERIODS` constant defines escalating cooldown periods
- `record_success()` method tracks successful API calls
- Success threshold (10 calls) triggers attempt counter reset
- State file now includes `attempt_number` and `success_count` fields

## 1.18.1 - 2025-10-29

### Security
- **CRITICAL FIX**: Fixed SQL injection vulnerability in database table operations
- Added input validation for table names, column names, and column types
- Whitelist validation prevents arbitrary SQL execution

### Fixed
- Fixed race condition in `record_not_found()` using SQLite UPSERT syntax
- Fixed silent exception swallowing - now returns boolean for success/failure
- Added automatic cleanup of old cache entries on startup (2+ days old)
- Improved error handling with critical error re-raising

### Improved
- Added type hints to all database methods for better IDE support
- Made cache duration configurable via `NOT_FOUND_CACHE_HOURS` environment variable
- Better thread safety with atomic UPSERT operations
- Added documentation explaining artist parameter design choice

### Technical
- Validates table/column names against whitelist to prevent SQL injection
- Uses `INSERT ... ON CONFLICT` for race-condition-free cache updates
- Cleanup runs silently on startup to prevent unbounded table growth
- Returns success indicators from cache operations for better error handling

## 1.18.0 - 2025-10-29

### Added
- **Phase 3: Cache Negative Results** - Prevent repeated YouTube API calls for content not found
- New `not_found_searches` table to cache failed search attempts for 24 hours
- Added `database/not_found_operations.py` module for managing the not-found cache
- Both `rate_video()` and history tracker now check the cache before searching YouTube
- Automatic recording of failed searches to prevent repeat API calls

### Performance
- Significant reduction in YouTube API usage for content that doesn't exist on YouTube
- Failed searches are now cached for 24 hours, preventing unnecessary repeat API calls
- History tracker now skips cached not-found content immediately

### Technical
- New `NotFoundOperations` class handles all not-found cache operations
- Uses content hash (SHA-256 of title+duration) for consistent cache keys
- Added `is_recently_not_found()` to check cache before searching
- Added `record_not_found()` to cache failed searches with search query
- Added `cleanup_old_entries()` for cache maintenance (2-day default)
- Added `get_stats()` for cache statistics

## 1.17.1 - 2025-10-28

### Fixed
- Fixed database migration error for existing databases
- Added proper migration logic to add ha_content_hash column to existing databases
- Fixed "no such column: ha_content_hash" error on startup

### Technical
- Added _add_column_if_missing() method for safe schema migrations
- Moved ha_content_hash index creation to occur after column is added

## 1.17.0 - 2025-10-28

### Added
- **Skip Non-YouTube Content**: Addon now detects and skips non-YouTube content based on channel/app name, saving API calls
- **Content Hash Detection**: Added hash-based duplicate detection using SHA-256 hash of title+duration
- New `ha_content_hash` field in database for tracking seen content combinations
- New helper functions: `is_youtube_content()` and `get_content_hash()`

### Changed
- Enhanced caching: Now checks content hash first before searching YouTube API
- Both `rate_video` and history tracker now skip non-YouTube content immediately
- Better logging when non-YouTube content is detected and skipped

### Performance
- Significant reduction in YouTube API usage by skipping non-YouTube content
- Faster duplicate detection using content hash lookups
- Improved cache hit rate through hash-based matching

### Technical
- Added `ha_content_hash` field to video_ratings table with index for fast lookups
- New `find_by_content_hash()` method for hash-based duplicate detection
- Updated `upsert_video()` to calculate and store content hash

## 1.16.4 - 2025-10-28

### Fixed
- Fixed date_last_played being NULL for all videos
- Videos now properly record date_last_played when first inserted
- Changed initial play_count from 0 to 1 when video is first added (since it's being played)

### Technical
- Added date_last_played to INSERT statement in upsert_video, set to same value as date_added
- Ensures date_last_played is never NULL for videos in the database

## 1.16.3 - 2025-10-28

### Fixed
- Actually fixed date_added NULL bug (previous fix wasn't working)
- Changed all timestamp calls to pass empty string '' instead of no argument
- The timestamp() function returns None when called with None, now we explicitly request current time

### Technical
- Fixed calls to self._timestamp() to use self._timestamp('') for current timestamp
- Affected files: video_operations.py and pending_operations.py

## 1.16.2 - 2025-10-28

### Fixed
- Fixed date_added field being NULL for all new videos
- Database now properly records timestamp when videos are first discovered from HA API or YouTube API
- Fixed upsert_video, record_play, and record_rating methods to use current timestamp instead of NULL

### Technical
- All database insert operations now properly set date_added to current timestamp when creating new records
- Preserves ability to override date_added for imports and migrations

## 1.16.1 - 2025-10-28

### Fixed
- Fixed Docker build to include database module directory
- Fixed ModuleNotFoundError preventing addon from starting
- Startup health checks now run properly on addon initialization
- Removed unused database_old.py backup file

### Technical
- Updated Dockerfile to copy database/ directory and all new helper files
- Ensures all Python modules are properly packaged in the Docker image

## 1.16.0 - 2025-10-28

### Changed
- **MAJOR REFACTOR**: Split large database.py (526 lines) into modular components
- Database operations now organized into focused modules:
  - `database/connection.py` - Connection management and schema (151 lines)
  - `database/video_operations.py` - Video CRUD operations (244 lines)
  - `database/pending_operations.py` - Pending queue management (107 lines)
  - `database/import_operations.py` - Import tracking (36 lines)
  - `database/__init__.py` - Unified interface (105 lines)
- Maintained 100% backward compatibility - no code changes needed

### Improved
- **Much easier debugging** - Each module has single responsibility
- **Better maintainability** - Smaller files are easier to understand
- **Cleaner separation of concerns** - Clear boundaries between operations
- **Reduced complexity** - No more 75-line methods in a 500+ line file
- **Better testability** - Can test each module independently

### Technical
- Database operations split from 526 lines to 5 files averaging ~130 lines each
- Longest method reduced from 75 lines to manageable chunks
- All existing imports continue to work unchanged
- Singleton pattern preserved for database instance

## 1.15.2 - 2025-10-28

### Fixed
- Fixed duplicated `FALSE_VALUES` constants with different values
  - `app.py` had `{'false', '0', 'no', 'off'}`
  - `quota_guard.py` had `{'false', '0', 'no', 'off', ''}` (included empty string)
  - Could cause subtle bugs with environment variable parsing
  - Now using shared constant from `constants.py`
- Fixed inconsistent parameter naming in `youtube_api.py`
  - Methods now use `yt_video_id` instead of `video_id` for consistency

### Improved
- Eliminated ~30 lines of duplicated code between `app.py` and `history_tracker.py`
  - Created `video_helpers.py` with shared `prepare_video_upsert()` function
  - Reduces maintenance burden and ensures consistency
- Better code organization with new modules:
  - `constants.py` for shared constants
  - `video_helpers.py` for shared video operations

### Technical
- No duplicate processes found running
- Codebase now has consistent naming throughout all modules
- Better separation of concerns with helper modules

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
