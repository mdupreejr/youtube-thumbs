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
- History tracker continues but skips YouTube matching
- Configurable via `quota_cooldown_hours`

## Data Storage

All data stored in `/config/youtube_thumbs/ratings.db`:

- **video_ratings** table - All matched videos with metadata, play counts, ratings
- **pending_ratings** table - Queued ratings (synced when API available)
- **import_history** table - Tracks imported YouTube exports
- **not_found_searches** table - Caches failed searches (24-48h)

Access via the **Database Viewer** link in the web interface.

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
