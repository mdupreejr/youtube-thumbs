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
