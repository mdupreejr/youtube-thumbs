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
