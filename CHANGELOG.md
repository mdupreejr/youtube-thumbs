# Changelog

All notable changes to YouTube Thumbs Rating add-on.

## [1.81.x] - 2025 - Code Quality & Bug Fixes

### v1.81.3 - Fix Stats Page Crash
- Fixed format_relative_time() to handle both datetime objects and strings
- Database now returns datetime objects in some queries
- Added type checking and proper handling for both input types

### v1.81.2 - Critical Bug Fixes
- Fixed validate_youtube_video_id() incorrectly unpacking error response tuple
- Fixed wrong dictionary key in startup_checks.py (cooldown_remaining_seconds → remaining_seconds)
- Added database initialization error handling with graceful exit
- Fixed test_db endpoint returning wrong error message

### v1.81.1 - Security Hardening
- Added SQL identifier quoting in _build_data_query() for defense-in-depth
- Implemented log value sanitization to prevent log injection attacks
- Extracted DATA_VIEWER_COLUMNS to module-level constant
- Fixed bare except handler in _format_data_rows()
- Added assertion checks for programming error detection

### v1.81.0 - Code Maintainability
- Split data_viewer() function (173 lines → 30 lines)
- Split logs_viewer() function (209 lines → 45 lines)
- Created 7 focused helper functions
- Improved code organization and readability

## [1.72.x] - Retry System Improvements

### v1.72.4 - Reduce Retry Rate
- Changed retry batch sizes to prevent quota exhaustion
- Manual retry button now processes 1 video instead of 5
- Automatic QuotaProber processes 1 video per recovery cycle instead of 50
- Changed delays between videos from 10s to 60s
- Default config `pending_video_retry_batch_size` changed from 50 to 1

### v1.72.3 - Improve Retry Button Feedback
- Increased status message display time from 2 seconds to 5 seconds
- Page only reloads if videos were successfully resolved
- Failed retry messages stay visible for user to read

### v1.72.2 - Fix Stats Page AttributeError
- Fixed stats page crash when accessing pending video statistics
- Added `get_pending_summary()` method delegation to Database class

### v1.72.1 - Add QuotaProber Logs Tab
- Dedicated logs tab for QuotaProber system monitoring
- Event categorization: probe, retry, success, error, recovery with color coding
- Summary statistics: probe attempts, recoveries, retry batches, videos resolved

### v1.72.0 - Manual Pending Video Retry
- New "Retry 1 Video" button on stats page
- Added `/api/pending/retry` endpoint with rate limiting
- Added pending video statistics display
- 30-second cooldown between manual retry attempts

## [1.71.x] - UI Improvements

### v1.71.2 - Compact Bulk Rating Layout
- Bulk rating interface now uses single-line layout
- Song title, artist, and duration on left; rating buttons on right
- More compact and easier to scan

### v1.71.1 - Fix Datetime JSON Serialization
- Fixed stats caching errors for recent_activity, top_rated, most_played
- Added DateTimeEncoder class to handle datetime serialization

## [1.51.x] - Automatic Retry System

### v1.51.2 - Database Migration Fix
- Fixed "NOT NULL constraint failed" error during migration
- Added intelligent migration that detects column constraints
- Graceful handling of older database schemas

### v1.51.1 - Database Migration Fix
- Fixed "no such column: ha_content_id" error on startup
- Moved ha_content_id index creation from schema to migration

### v1.51.0 - Automatic Pending Video Retry
- Automatic retry mechanism for pending videos after quota recovery
- Videos stored as pending during quota exhaustion
- QuotaProber automatically retries matching pending videos
- Added `pending_video_retry_enabled` option (default: true)
- Added `pending_video_retry_batch_size` option (default: 50)
- Metrics tracking for retry operations

## [1.50.0] - Major Database Refactor

### Breaking Changes
- Database schema significantly refactored
- Moved ha_hash:* placeholder IDs from yt_video_id to new ha_content_id column
- Consolidated pending_ratings table into video_ratings columns
- yt_video_id now allows NULL for pending videos
- Automatic migration runs on first startup (preserves all data)

## [1.49.x] - Optimization & Fixes

### v1.49.7 - Optimize Database Viewer
- Reduced sqlite_web sidebar from ~33% screen width to 180px
- Improved content viewing area

### v1.49.6 - Fix Stats Page for Ingress
- Fixed statistics dashboard API calls through Home Assistant ingress
- Added BASE_PATH detection

### v1.49.5 - Fix Rating Endpoint
- Fixed NameError in thumbs_up/thumbs_down endpoints
- Rating endpoints now work correctly

### v1.49.4 - Fix Stats Page Loading
- Fixed statistics dashboard showing as blank/black page
- Changed hardcoded `/static/` paths to use Flask's `url_for()`

### v1.49.3 - Fix Bulk Rating
- Fixed missing `get_unrated_videos()` method exposure
- Bulk rating interface now works correctly

### v1.49.2 - Critical Bug Fixes
- Fixed pagination semantic inconsistency
- Added negative duration validation
- Added page bounds validation

### v1.49.1 - Edge Case Fixes
- Fixed duration=0 handling
- Improved cache metrics type detection
- Better error messages

### v1.49.0 - Major Optimization
- 50% fewer database queries
- 60% less memory usage
- 100% proper abstraction layer
- Removed 96 lines of inline SQL

## [1.48.0] - Code Cleanup

- Removed duplicate API endpoints
- Consolidated to kebab-case naming
- Updated all endpoints to use database abstraction
- Removed 83 lines of redundant code

## [1.47.x] - Web Interface Fixes

### v1.47.3 - Fix Links for Ingress
- Fixed Advanced Statistics Dashboard link to use BASE_PATH
- Removed target="_blank" from footer links
- Added HTML formatting to /health and /metrics

### v1.47.2 - Fix Cached Video Rating
- Fixed TypeError when rating videos from cache
- Timestamp() method now handles both string and datetime inputs

## [1.40.0] - Database Viewer

- Added `/database` proxy route to sqlite_web
- Database viewer accessible through main web UI
- Opens in full-size window
- All access through ingress

## [1.39.0] - Bulk Rating Interface

- New tabbed web interface (System Tests, Bulk Rating)
- Rate 50 unrated songs per page
- Sorted by play count (most played first)
- Pagination support

## [1.38.0] - Web Interface

- Added system test buttons
- Health check and metrics endpoints
- Modern responsive UI

## [1.31.0] - Simplification

- Removed 820+ lines of fuzzy matching logic
- Simplified to exact title + duration matching
- Improved reliability and performance

## [1.30.0] - Duration Fix

- Fixed exact duration matching (YouTube = HA + 1 always)
- Removed incorrect tolerance logic

---

For complete version history and minor updates, see git commit history.
