# YouTube Thumbs - Home Assistant Add-on

A Home Assistant add-on that lets you rate YouTube videos (👍/👎) for songs playing on your AppleTV. Perfect for Lutron remote integration or any automation that needs to rate music.

## Features

- 🎵 **Rate YouTube videos** via REST API based on currently playing content
- ⚡ **Bulk Rating Interface** - Quickly rate up to 50 unrated songs at once (sorted by play count)
- 🔍 **Smart matching** - Automatic YouTube video matching with exact title and duration
- 📊 **Database Viewer** - Built-in sqlite_web interface accessible through ingress
- 🕒 **History tracking** - Automatic background tracking of all songs played
- 🛡️ **Quota protection** - Built-in rate limiting and quota cooldown
- 💾 **SQLite storage** - Local database with comprehensive metadata
- 📝 **Audit trails** - Detailed logging of all user actions
- 💡 **Smart caching** - Reuses matches to avoid redundant YouTube searches
- 🔒 **OAuth preserved** - Credentials and tokens stored in addon_configs

## Quick Start

See **[INSTALL.md](INSTALL.md)** for complete installation instructions including OAuth setup.

### Basic Steps

1. Add this repository to Home Assistant
2. Install "YouTube Thumbs Rating" add-on
3. Copy `credentials.json` to `/addon_configs/XXXXXXXX_youtube_thumbs/`
4. Configure media player entity
5. Start the add-on

## Web Interface

Access the web interface by clicking **OPEN WEB UI** in the addon page:

### System Tests Tab
- Test YouTube API connectivity
- Test Home Assistant API connectivity
- Test Database connectivity
- View system health and status

### Bulk Rating Tab
- View 50 unrated songs per page (sorted by play count)
- Quick thumbs up/down buttons for rapid rating
- Songs disappear immediately after rating
- Pagination to browse all unrated songs
- Helps improve YouTube's recommendation algorithm

### Database Viewer
- Click "🗄️ Database Viewer" link
- Opens in new window at full size
- Browse, query, and export playback history
- All access goes through ingress (no separate port needed)

## Configuration

Add REST commands to your `configuration.yaml`:

```yaml
rest_command:
  youtube_thumbs_up:
    url: "http://localhost:21812/thumbs_up"
    method: POST
    timeout: 30

  youtube_thumbs_down:
    url: "http://localhost:21812/thumbs_down"
    method: POST
    timeout: 30
```

Then create automations to call these services. Example for Lutron remote:

```yaml
automation:
  - alias: "Thumbs Up Button"
    trigger:
      - platform: device
        device_id: your_device_id
        type: press
        subtype: button_1
    action:
      - service: rest_command.youtube_thumbs_up
```

### Addon Options

Configure in the addon **Configuration** tab:

| Option | Default | Description |
|--------|---------|-------------|
| `media_player_entity` | (required) | Media player entity ID |
| `port` | 21812 | Service port |
| `rate_limit_per_minute` | 10 | Max API calls per minute |
| `rate_limit_per_hour` | 100 | Max API calls per hour |
| `rate_limit_per_day` | 500 | Max API calls per day |
| `quota_cooldown_hours` | 12 | Hours to pause after quota error |
| `log_level` | INFO | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `history_tracker_enabled` | true | Background history tracking |
| `history_poll_interval` | 60 | Seconds between HA polls (10-300) |
| `force_quota_unlock` | false | Clear quota block on startup |
| `pending_video_retry_enabled` | true | Auto-retry pending videos after quota recovery |
| `pending_video_retry_batch_size` | 50 | Max pending videos to retry per recovery (1-500) |

## API Endpoints

### `POST /thumbs_up` / `POST /thumbs_down`
Rate the currently playing song.

**Response:**
```json
{
  "success": true,
  "message": "Successfully rated like",
  "video_id": "zmLIxKpgEPw",
  "title": "Song Title"
}
```

### `GET /health`
Health check with rate limiter and quota stats.

### `GET /metrics`
Comprehensive metrics for monitoring (cache performance, API usage, ratings, search patterns).

### `GET /api/unrated?page=1`
Get 50 unrated songs (used by bulk rating interface).

### `POST /api/rate/<video_id>/like`
### `POST /api/rate/<video_id>/dislike`
Direct rating by video ID (used by bulk rating interface).

### `GET /database`
Proxy to sqlite_web database viewer.

## How It Works

1. Fetches current media from Home Assistant (YouTube content only)
2. Checks SQLite cache for exact matches:
   - Content hash (title + duration + artist)
   - Exact title + exact duration (YouTube = HA + 1 second)
3. If no cache hit, searches YouTube with cleaned title
4. Filters results by exact duration match
5. Rates the best match on YouTube

### History Tracking

- Polls Home Assistant every 60 seconds for currently playing song
- New songs are matched, stored in database, and play count tracked
- Play count increments only when a new song starts (not on continuous playback)
- Configurable via `history_tracker_enabled` and `history_poll_interval`

### Quota Protection

- Automatic 12-hour cooldown after `quotaExceeded` errors
- Cooldown state saved in `/config/youtube_thumbs/quota_guard.json`
- HTTP endpoints return `503` during cooldown
- History tracker continues but skips YouTube matching (videos stored as pending)
- Automatic quota recovery detection probes YouTube API every hour during cooldown
- Pending videos automatically retried after quota recovery (v1.51.0)
- Configurable via `quota_cooldown_hours`, `pending_video_retry_enabled`, `pending_video_retry_batch_size`

## Data Storage

All data stored in `/config/youtube_thumbs/ratings.db`:

- **video_ratings** table - All matched videos with metadata, play counts, ratings, and pending rating queue
  - Real YouTube videos have `yt_video_id` populated
  - Pending videos (quota blocked) have `ha_content_id` with NULL `yt_video_id`
  - Pending ratings stored in `yt_rating_pending`, `yt_rating_attempts`, `yt_rating_last_error` columns
- **import_history** table - Tracks imported YouTube exports
- **not_found_searches** table - Caches failed searches (7 days default)

**Note:** v1.50.0 removed the separate `pending_ratings` table - all data now in `video_ratings`.

Access via the **Database Viewer** link in the web interface.

## Matching System & Database Schema

### How Video Matching Works

The addon uses a multi-stage matching system to find YouTube videos for songs playing on your Apple TV:

#### 1. Cache Lookup (Instant, No API Calls)
When a new song is detected, the addon first checks the local database cache:

1. **Content Hash Lookup**: Calculates SHA1 hash of `title + duration + artist` and searches for exact match
   - Most flexible - handles minor formatting differences
   - Example: "Song Name" vs "Song Name " (trailing space) both match
2. **Title + Duration Lookup**: Searches for exact `ha_title` and `ha_duration` match
   - Fallback if content hash doesn't match
   - YouTube duration = HA duration + 1 second (YouTube rounds up)

**Cache Hit**: Returns existing video immediately, increments play count, no YouTube API call needed.

#### 2. YouTube Search (API Call Required)
If no cache match found:

1. **Clean title**: Removes special characters, normalizes spacing
2. **Search YouTube**: Query YouTube Data API with cleaned title
3. **Filter by duration**: Only consider results where YouTube duration matches HA duration ± 1 second
4. **Select best match**: First result with exact duration match
5. **Store in database**: Save video metadata, mark as matched (`pending_match = 0`)

**Search Hit**: Video matched and cached for future plays.

#### 3. Not Found Cache (Prevents Repeated Searches)
If YouTube search returns no results:

1. **Record in not_found_searches table**: Title + artist + duration + timestamp
2. **Cache duration**: 7 days (prevents searching again for same song)
3. **Future lookups**: Skip YouTube search if in not_found cache

**Not Found Hit**: Logged but no database entry created.

#### 4. Quota Exceeded Handling (v1.50.0+)
If YouTube quota is exhausted during search:

1. **Store as pending**: Creates database entry with `pending_match = 1`
2. **Use placeholder ID**: `ha_content_id = ha_hash:abc123` (content hash)
3. **Set pending_reason**: `quota_exceeded`
4. **Skip YouTube calls**: All future searches delayed until quota recovers
5. **Automatic retry**: After quota recovery, QuotaProber retries all pending videos (v1.51.0)

### Database Tables

#### video_ratings (Main Table)
Primary table storing all video metadata, play history, ratings, and pending states.

**YouTube Metadata Fields** (yt_* prefix):
- `yt_video_id` (TEXT, PRIMARY KEY) - YouTube video ID (e.g., "dQw4w9WgXcQ")
  - NULL for pending videos awaiting YouTube match
  - Populated after successful match
- `yt_title` (TEXT) - Official YouTube video title
- `yt_channel` (TEXT) - YouTube channel name
- `yt_channel_id` (TEXT) - YouTube channel ID
- `yt_description` (TEXT) - Video description
- `yt_published_at` (TIMESTAMP) - YouTube upload date
- `yt_category_id` (INTEGER) - YouTube category (10=Music, etc.)
- `yt_live_broadcast` (TEXT) - Live stream status (none/upcoming/live/completed)
- `yt_location` (TEXT) - Geographic location if available
- `yt_recording_date` (TIMESTAMP) - Original recording date if available
- `yt_duration` (INTEGER) - YouTube video duration in seconds
- `yt_url` (TEXT) - Full YouTube URL

**Home Assistant Metadata Fields** (ha_* prefix):
- `ha_content_id` (TEXT) - Placeholder ID for pending videos (v1.50.0)
  - Format: `ha_hash:abc123` (SHA1 of title+duration+artist)
  - Used when `yt_video_id` is NULL (quota blocked)
  - Replaced with real `yt_video_id` after successful match
- `ha_title` (TEXT, INDEXED) - Song title from HA media player
- `ha_artist` (TEXT) - Artist/channel from HA media player
- `ha_app_name` (TEXT) - Source app (e.g., "YouTube Music")
- `ha_duration` (INTEGER, INDEXED) - Song duration in seconds from HA
- `ha_content_hash` (TEXT, INDEXED) - SHA1 hash for duplicate detection
  - Format: SHA1(lowercase(title) + duration + lowercase(artist))
  - Enables fuzzy matching across formatting differences

**Playback & Rating Fields**:
- `rating` (TEXT) - User rating: 'like', 'dislike', or 'none'
- `rating_score` (INTEGER) - Net rating score (likes - dislikes)
  - Incremented/decremented on rating changes
  - Used for "Top Rated" statistics
- `play_count` (INTEGER) - Number of times played
- `date_added` (TIMESTAMP) - When video was first added to database
- `date_last_played` (TIMESTAMP, INDEXED) - Most recent play timestamp

**Pending Video Fields** (v1.50.0):
- `pending_match` (INTEGER) - Boolean flag (0=matched, 1=pending YouTube match)
  - Set to 1 when quota exhausted during search
  - Set to 0 after successful YouTube match
- `pending_reason` (TEXT) - Why video is pending
  - `quota_exceeded` - Quota was exhausted, retry after recovery
  - `not_found` - No YouTube match exists (marked by retry mechanism)
  - NULL - Not pending (successfully matched)
- `source` (TEXT) - How video was added
  - `ha_live` - Playing on Home Assistant media player
  - `import_youtube` - Imported from YouTube export
  - `manual` - Manually added

**Pending Rating Queue Fields** (v1.50.0):
When rating fails due to quota/network issues, queued for retry:
- `yt_rating_pending` (TEXT) - Pending rating action: 'like', 'dislike', or NULL
- `yt_rating_requested_at` (TIMESTAMP) - When rating was first requested
- `yt_rating_attempts` (INTEGER) - Number of retry attempts
- `yt_rating_last_attempt` (TIMESTAMP) - Last retry attempt timestamp
- `yt_rating_last_error` (TEXT) - Last error message

**Example Records**:

```sql
-- Fully matched video (normal case)
yt_video_id: "dQw4w9WgXcQ"
ha_content_id: NULL
ha_title: "Never Gonna Give You Up"
yt_title: "Rick Astley - Never Gonna Give You Up (Official Video)"
pending_match: 0
pending_reason: NULL
rating: "like"
play_count: 5

-- Pending video (quota exhausted)
yt_video_id: NULL
ha_content_id: "ha_hash:a1b2c3d4e5f6"
ha_title: "Some New Song"
yt_title: NULL
pending_match: 1
pending_reason: "quota_exceeded"
rating: "none"
play_count: 1

-- Pending video marked as not found
yt_video_id: NULL
ha_content_id: "ha_hash:x9y8z7w6v5u4"
ha_title: "Obscure Local Recording"
yt_title: NULL
pending_match: 1
pending_reason: "not_found"
```

#### not_found_searches (Search Cache)
Prevents repeatedly searching YouTube for songs that don't exist.

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment ID
- `title` (TEXT, INDEXED) - Song title that wasn't found
- `artist` (TEXT) - Artist name (can be NULL)
- `duration` (INTEGER) - Duration in seconds (can be NULL)
- `search_query` (TEXT) - Actual query sent to YouTube
- `content_hash` (TEXT, INDEXED) - SHA1 hash (title+duration+artist)
- `timestamp` (TIMESTAMP, INDEXED) - When search failed
- `expires_at` (TIMESTAMP, INDEXED) - When cache entry expires (timestamp + 7 days)

**Behavior**:
- Before searching YouTube, checks if title+duration+artist in this table
- If found and not expired, skips YouTube search (saves quota)
- Expired entries cleaned up automatically on addon startup
- Default expiration: 7 days (configurable via `cleanup_old_not_found()`)

**Example**:
```sql
title: "My Home Recording Demo"
artist: "Unknown Artist"
duration: 237
content_hash: "sha1_hash_here"
timestamp: "2025-01-15 10:30:00"
expires_at: "2025-01-22 10:30:00"
```

#### import_history (Deduplication)
Tracks YouTube export imports to prevent duplicate entries.

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment ID
- `entry_id` (TEXT, UNIQUE) - Hash of import entry (timestamp + video_id + action)
- `source` (TEXT) - Import source ('youtube_export', 'manual', etc.)
- `yt_video_id` (TEXT) - YouTube video ID that was imported
- `action` (TEXT) - What was imported ('watch', 'like', 'dislike')
- `imported_at` (TIMESTAMP) - When import occurred

**Behavior**:
- Before importing a YouTube export entry, checks if `entry_id` already exists
- Prevents duplicate play counts and ratings from re-importing same file
- Used by import_youtube_export.py script

### Video States Explained

A video in the database can be in one of these states:

1. **✓ Matched** (`pending_match = 0`, `yt_video_id` populated)
   - Successfully found on YouTube
   - All YouTube metadata populated
   - Can be rated, played, tracked
   - Shows in all statistics

2. **⏳ Pending - Quota Exceeded** (`pending_match = 1`, `pending_reason = 'quota_exceeded'`)
   - Quota was exhausted when attempting to match
   - Only Home Assistant data available (no YouTube metadata)
   - Will be retried automatically after quota recovery (v1.51.0)
   - Shows in startup check as "pending (quota_exceeded)"

3. **✗ Pending - Not Found** (`pending_match = 1`, `pending_reason = 'not_found'`)
   - Searched YouTube but no match found
   - Marked by retry mechanism after failed search
   - Won't be retried again (no YouTube video exists)
   - Also added to `not_found_searches` table

4. **Not in Database** (no record)
   - In `not_found_searches` table only
   - YouTube search was attempted but failed
   - No database entry created to save space
   - Prevents future searches for 7 days

### Content Hash Algorithm

The content hash enables fuzzy matching despite formatting differences:

```python
def get_content_hash(title, duration, artist=None):
    # Normalize inputs
    title_norm = (title or "").strip().lower()
    artist_norm = (artist or "").strip().lower()
    duration_str = str(duration or 0)

    # Combine and hash
    combined = f"{title_norm}:{duration_str}:{artist_norm}"
    return hashlib.sha1(combined.encode('utf-8')).hexdigest()
```

**Why it works**:
- Lowercases everything (handles "Song Name" vs "song name")
- Strips whitespace (handles "Song  Name" vs "Song Name")
- Includes duration (prevents matching different versions)
- Optional artist (handles missing artist metadata)

**Example matches** (same hash):
- "Never Gonna Give You Up" / "never gonna give you up"
- "Song Name  " / "Song Name" (trailing space)
- "Title - Artist" / "Title - artist" (case difference)

### Pending Video Retry Workflow (v1.51.0)

1. **Quota Exhaustion**: New song plays, quota exceeded
   - Create video_ratings entry with `pending_match = 1`
   - Set `ha_content_id = ha_hash:abc123`
   - Set `pending_reason = 'quota_exceeded'`
   - Set `yt_video_id = NULL`

2. **Quota Recovery Detection**: QuotaProber runs every hour
   - Probes YouTube API with test search
   - If successful, clears quota guard

3. **Automatic Retry**: QuotaProber calls `_retry_pending_videos()`
   - Queries: `SELECT * FROM video_ratings WHERE pending_match = 1 AND pending_reason = 'quota_exceeded' LIMIT 50`
   - For each pending video:
     - Search YouTube with ha_title + ha_duration + ha_artist
     - **If found**: Update with YouTube data, set `pending_match = 0`, populate `yt_video_id`
     - **If not found**: Set `pending_reason = 'not_found'`, add to `not_found_searches`

4. **Metrics Recording**: Track retry statistics
   - Total videos attempted
   - Successfully matched count
   - Not found count
   - Error count
   - Success rate percentage

**Configuration**:
- `pending_video_retry_enabled` (default: true) - Enable/disable automatic retry
- `pending_video_retry_batch_size` (default: 50) - Max videos per retry to prevent re-exhausting quota

## Troubleshooting

### No videos being added
- Most common: Missing `credentials.json` or `token.pickle`
- Check `/addon_configs/XXXXXXXX_youtube_thumbs/` for both files
- Restart addon after copying credentials

### "No media currently playing"
- Verify AppleTV is playing music
- Check media player entity ID in configuration

### OAuth/Credentials errors
- Ensure `credentials.json` is from Google Cloud Console
- YouTube Data API v3 must be enabled
- Check addon logs for specific errors

### Quota exceeded / 503 errors
- Automatic 12-hour cooldown activated
- Wait for cooldown or delete `/config/youtube_thumbs/quota_guard.json`
- Only delete if quota has actually reset

### Test buttons not working
- Rebuild the addon (not just restart)
- Click 3 dots → Rebuild
- Wait for build to complete

**Check Logs**: Settings → Add-ons → YouTube Thumbs Rating → Log tab

## Recent Updates

### v1.51.1 - Database Migration Fix
- **Bug Fix:** Fixed "no such column: ha_content_id" error on addon startup
- Moved ha_content_id index creation from schema to migration
- Ensures proper migration path for both new and existing databases
- Added comprehensive "Matching System & Database Schema" documentation section

### v1.51.0 - Automatic Pending Video Retry
- **New Feature:** Automatic retry mechanism for pending videos after quota recovery
- When quota is exhausted, unmatched videos are stored as pending (pending_match=1)
- After quota recovers, QuotaProber automatically retries matching pending videos
- Added `pending_video_retry_enabled` option (default: true)
- Added `pending_video_retry_batch_size` option (default: 50, max: 500)
- Database methods: `get_pending_videos()`, `resolve_pending_video()`, `mark_pending_not_found()`
- Metrics tracking for retry operations (total, matched, not_found, errors)
- Prevents quota re-exhaustion with configurable batch size
- Logs detailed retry progress and statistics

### v1.50.0 - Major Database Schema Refactor
- **Breaking Change:** Database schema has been significantly refactored
- Moved ha_hash:* placeholder IDs from yt_video_id to new ha_content_id column
- Consolidated pending_ratings table into video_ratings columns
- Added yt_rating_pending, yt_rating_requested_at, yt_rating_attempts, yt_rating_last_attempt, yt_rating_last_error columns
- Automatic migration runs on first startup after upgrade
- yt_video_id now allows NULL for pending videos (those without YouTube match yet)
- Cleaner schema separation: yt_video_id for real YouTube IDs, ha_content_id for pending placeholders
- Dropped pending_ratings table after migrating all data
- No user action required - migration is automatic and preserves all data
- **Recommendation:** Backup database before upgrading (automatic backup created during migration)

### v1.49.7 - Optimize Database Viewer Sidebar Width
- Added custom CSS injection to database proxy
- Reduced sqlite_web sidebar from ~33% screen width to 180px
- Improved content viewing area (now takes majority of screen)
- Responsive design: 150px sidebar on mobile devices
- CSS injected automatically when viewing database through ingress

### v1.49.6 - Fix Stats Page API Calls for Ingress
- Fixed statistics dashboard API calls to work through Home Assistant ingress
- Added BASE_PATH detection in stats.html (same as index.html)
- Updated fetchWithErrorHandling in stats.js to prepend BASE_PATH to all API calls
- Updated direct fetch calls in explorer filter and export functions
- Stats page now fully functional with all charts, tabs, and data loading

### v1.49.5 - Fix Rating Endpoint NameError
- Fixed NameError in thumbs_up/thumbs_down endpoints
- Changed undefined `find_cached_video` to `_cache_wrapper`
- Changed undefined `search_and_match_video` to `_search_wrapper`
- Rating endpoints now work correctly

### v1.49.4 - Fix Stats Page Loading Through Ingress
- Fixed statistics dashboard showing as blank/black page
- Changed hardcoded `/static/` paths to use Flask's `url_for()` function
- CSS and JavaScript now load correctly through Home Assistant ingress
- Stats page now fully functional when accessed through web UI

### v1.49.3 - Fix Bulk Rating Interface
- Fixed missing `get_unrated_videos()` method exposure in Database class
- Added `find_cached_video_combined()` method exposure
- Methods were implemented but not exposed through Database wrapper
- Bulk rating interface now works correctly

### v1.49.2 - Critical Bug Fixes (Code Review)
- Fixed pagination semantic inconsistency (total_pages=0 when empty)
- Added negative duration validation with data corruption detection
- Added page bounds validation (page must be ≥1)
- Automatic page clamping to valid range prevents empty responses
- Improved error messages for API consumers

### v1.49.1 - Edge Case Fixes (Code Review)
- Fixed duration=0 handling (now accepts 0-second videos like YouTube Shorts)
- Improved cache metrics type detection with robust null checking
- Added try-except blocks for all integer parameter parsing
- Better error messages with expected value ranges

### v1.49.0 - Major Optimization
- **50% fewer database queries** - Combined cache lookups into single query
- **60% less memory usage** - Reduced metrics tracker from 20k to 8k items
- **100% proper abstraction** - Eliminated all direct database access from endpoints
- Added `get_unrated_videos()` and `find_cached_video_combined()` methods
- Removed 96 lines of inline SQL from app.py

### v1.48.0 - Code Cleanup
- Removed duplicate API endpoints (most_played, channels)
- Consolidated to kebab-case naming convention
- Updated all endpoints to use database abstraction layer
- Removed 83 lines of redundant code

### v1.47.3 - Web Interface Fixes
- Fixed Advanced Statistics Dashboard link to use BASE_PATH
- Removed target="_blank" from footer links
- Added HTML formatting to /health and /metrics endpoints
- All links now work correctly through Home Assistant ingress

### v1.47.2 - Bug Fix: Cached Video Rating
- Fixed TypeError when rating videos retrieved from database cache
- SQLite's datetime conversion was causing `.replace()` to fail
- timestamp() method now handles both string and datetime inputs

### v1.40.0 - Database Viewer Integration
- Added `/database` proxy route to sqlite_web
- Database viewer accessible through main web UI
- Opens in full-size window
- All access through ingress (no separate port)

### v1.39.0 - Bulk Rating Interface
- New tabbed web interface (System Tests, Bulk Rating)
- Rate 50 unrated songs per page
- Sorted by play count (most played first)
- Quick thumbs up/down buttons
- Pagination support

### v1.38.0 - Web Interface
- Added system test buttons
- Health check and metrics endpoints
- Modern responsive UI

### v1.31.0 - Simplification
- Removed 820+ lines of fuzzy matching logic
- Simplified to exact title + duration matching
- Improved reliability and performance

### v1.30.0 - Duration Fix
- Fixed exact duration matching (YouTube = HA + 1 always)
- Removed incorrect tolerance logic

## Support

For issues or questions:
- Check addon logs first (Settings → Add-ons → Log tab)
- Review [INSTALL.md](INSTALL.md) for complete documentation
- Enable `log_level: DEBUG` for detailed output

## Security

- OAuth credentials stored in `/addon_configs/` (persistent)
- Authentication via Supervisor token (automatic)
- Rating API bound to `127.0.0.1` (localhost only)
- Database viewer accessible through ingress only
- ⚠️ Never share your `credentials.json` file

## Development

See [INSTALL.md](INSTALL.md) for local development setup instructions.

## License

Provided as-is for personal use.
