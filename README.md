# YouTube Thumbs - Home Assistant Add-on

A Home Assistant add-on that lets you rate YouTube videos (👍/👎) for songs playing on your AppleTV. Perfect for Lutron remote integration or any automation that needs to rate music.

## About

This add-on provides a Flask service that integrates with Home Assistant to automatically rate YouTube videos based on what's currently playing on your AppleTV. Perfect for Lutron remote integration or any automation that needs to rate music.

## 🗄️ Database Interface

Access your playback history and ratings database directly through the built-in sqlite_web interface:

- **From Home Assistant:** Click the **OPEN WEB UI** button in the add-on page
- **Direct Access:** The interface runs on port 8080 (accessible via Home Assistant Ingress)
- **Features:** Browse, query, and export your music history and ratings data

## Features

- 🎵 Rate currently playing songs via REST API
- 🔍 Automatic YouTube video matching with fuzzy search
- 🛡️ Built-in rate limiting (configurable)
- 📝 Comprehensive logging integrated with Home Assistant
- 📊 Detailed user action audit trail
- 🕒 Background history tracker that logs every song even without ratings
- ⚡ Optimized performance with caching and connection pooling
- 💡 Reuses cached matches to avoid redundant YouTube searches
- 💾 Local SQLite history with built-in web interface (click **OPEN WEB UI** button)
- 🔒 OAuth authentication preservation

## Installation

### Quick Install

1. Add this GitHub repository to Home Assistant Add-on Store
2. Install the "YouTube Thumbs Rating" add-on
3. Copy your `credentials.json` to `/addon_configs/XXXXXXXX_youtube_thumbs/` (exposed at `/config/youtube_thumbs/` inside the container). Replace `XXXXXXXX` with the 8-character ID Home Assistant assigns your add-on; you can see it by opening **Settings → Add-ons → YouTube Thumbs Rating → Configuration**, then clicking **Show in File Editor** (or browsing via Samba).
4. Configure the add-on with your media player entity
5. Start the add-on

For detailed installation instructions, including OAuth setup and troubleshooting, see **[INSTALL.md](INSTALL.md)**

## Configuration

Add REST commands to your Home Assistant `configuration.yaml`:

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
Health check with rate limiter and quota guard stats.

```json
{
  "status": "healthy",
  "health_score": 85,
  "warnings": [],
  "rate_limiter": {
    "last_minute": 2,
    "last_hour": 15,
    "last_day": 47,
    "limits": { ... }
  },
  "quota_guard": {
    "blocked": false,
    "blocked_until": null,
    "remaining_seconds": 0,
    "reason": null,
    "detail": null,
    "message": "YouTube quota available"
  }
}
```

### `GET /metrics`
Comprehensive metrics for monitoring and analysis.

```json
{
  "health": {
    "score": 85,
    "status": "healthy",
    "warnings": []
  },
  "cache": {
    "total": {
      "hits": 1234,
      "misses": 567,
      "hit_rate": 68.5
    },
    "last_hour": { ... },
    "last_24h": { ... },
    "fuzzy_matches": {
      "total": 89,
      "last_hour": 12
    }
  },
  "api": {
    "total_calls": 3456,
    "success_rate": 95.2,
    "by_type": {
      "search": { ... },
      "rate": { ... }
    },
    "quota": {
      "trips": 2,
      "recoveries": 1
    }
  },
  "ratings": {
    "success": {
      "total": 234,
      "last_hour": 15
    },
    "failed": { ... },
    "queued": { ... }
  },
  "search": {
    "total_searches": 456,
    "failed_searches": {
      "total": 23,
      "by_reason": { ... }
    }
  }
}
```

## How It Works

1. Service fetches current media from Home Assistant.
2. Checks the SQLite cache for an exact `ha_title` match and reuses that video ID when found.
3. If no cache hit occurs, searches YouTube for matching video (by title, artist, duration ±2s).
4. Filters results using fuzzy title matching (50%+ word overlap).
5. Rates the best match on YouTube.

### Playback History Tracker

- Every 60 seconds the add-on polls Home Assistant for the currently playing song.
- New titles (title + duration) are matched against YouTube, stored in `ratings.db`, and receive an initial play count.
- Play count increments only when a new song starts playing - continuous playback of the same song counts as a single play, regardless of duration.
- Set `ENABLE_HISTORY_TRACKER=false` to disable the background thread or tweak the cadence with `HISTORY_POLL_INTERVAL=<seconds>` if you need a slower/faster poll rate (default 60s, exposed in the add-on config as `history_tracker_enabled` / `history_poll_interval`).

## Add-on Configuration Options

For safety the thumbs API (`/thumbs_up`, `/thumbs_down`) always binds to `127.0.0.1`
inside the add-on container. The sqlite_web helper also defaults to `127.0.0.1` and is
served through Home Assistant Ingress, so the **OPEN WEB UI** button works out of the box.
If you need to expose sqlite_web directly to your LAN, change the `sqlite_web_host`
option (be sure you trust the clients that will have access to the database UI).

Configure these in the add-on Configuration tab:

| Option | Default | Description |
|--------|---------|-------------|
| `media_player_entity` | (required) | Media player entity ID (e.g., `media_player.apple_tv`) |
| `port` | 21812 | Service port |
| `rate_limit_per_minute` | 10 | Max YouTube API calls in 60-second window |
| `rate_limit_per_hour` | 100 | Max YouTube API calls in 3600-second window |
| `rate_limit_per_day` | 500 | Max YouTube API calls in 24-hour period |
| `quota_cooldown_hours` | 12 | Hours to pause YouTube API access after a quota/rate-limit error |
| `log_level` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `sqlite_web_host` | 127.0.0.1 | Bind address for sqlite_web (set to `0.0.0.0` only if you need LAN access) |
| `sqlite_web_port` | 8080 | Port for sqlite_web when exposed to your LAN; ignored when using HA ingress (the default) |
| `history_tracker_enabled` | true | Toggle the background poller that logs every song |
| `history_poll_interval` | 60 | Seconds between Home Assistant polls (10–300 allowed) |
| `force_quota_unlock` | false | Clear the quota guard file on startup to immediately re-enable YouTube API calls |

**Note:** The add-on automatically handles authentication using the Supervisor token.

### Automatic Quota Cooldown

Any time Google responds with `quotaExceeded`, the add-on writes
`/config/youtube_thumbs/quota_guard.json`, logs the failure, and pauses all YouTube
API calls for 12 hours (configurable via the `quota_cooldown_hours` option or `YTT_QUOTA_COOLDOWN_SECONDS`). During the
cooldown the HTTP endpoints return `503` with a friendly error message. The
history tracker still polls Home Assistant and stores the metadata with a
placeholder ID so your play history remains intact, but it skips YouTube matching
until the cooldown expires. Delete the guard file only after your
quota resets if you need to re-enable access early.

## Data Storage & sqlite_web

- All history lives in `ratings.db` at `/config/youtube_thumbs/ratings.db` (perfect for easy backups with ZFS or snapshots).
- The add-on automatically starts [`sqlite_web`](https://github.com/coleifer/sqlite-web) and opens it via HA ingress.
  - **📊 Access the Database:** Click the **OPEN WEB UI** button in the add-on page to launch the sqlite_web interface
  - Home Assistant proxies the sqlite_web instance into your browser even when it is bound to `127.0.0.1`
  - Logs for the UI are written to `/config/youtube_thumbs/sqlite_web.log`.
- Each row includes a `source` column (default `ha_live`) so you can tag imports such as manual YouTube exports; set it when calling `db.upsert_video` to keep provenance straight.
- Failed thumbs requests are persisted in the `pending_ratings` table and automatically retried once the YouTube API/quota comes back, so every request is documented even when YouTube is offline.
- Prefer a different bind target? Keep `sqlite_web_host` at `127.0.0.1` for ingress/HA-only access or set it to `0.0.0.0` to expose the DB UI to your LAN. Pair it with the `sqlite_web_port` option (or the `SQLITE_WEB_HOST`/`SQLITE_WEB_PORT` env vars) if you need custom settings.
- When `sqlite_web_host` is not localhost, the **OPEN WEB UI** button is bypassed—browse to `http://<home-assistant-host>:<sqlite_web_port>` directly instead.
- Every record tracks both the Home Assistant-reported artist/channel and the YouTube channel metadata so you can audit mismatches later.
- Every successful match is cached, so follow-up requests for the exact same Home Assistant title reuse the stored video ID and skip the expensive YouTube search entirely.
- The `pending_ratings` table tracks queued thumbs requests; clear or inspect it via sqlite_web if you need to audit what still needs to sync.
- The `import_history` table records which external exports have already been ingested so you can safely rerun the importer without double-counting plays.
- If you repeat the same thumbs action as last time, the cached rating prevents us from pinging YouTube at all.

### Importing YouTube Activity HTML exports

Run the helper script to ingest the files you dropped in `youtube_exports/`:

```bash
./import_youtube_exports.py
```

Each `Watched …` entry becomes a cached video (`source='yt_export'`), the play is recorded with the original timestamp, and the `(filename, video_id, timestamp)` tuple is hashed into `import_history` so reruns stay idempotent.

### Manual import from the legacy `ratings.log`

Importing is a one-time operation, so feel free to do it manually:

1. Stop the add-on (to release the SQLite lock).
2. Open `/config/youtube_thumbs/ratings.log` alongside `sqlite_web` (or the `sqlite3` CLI).
3. For each entry you care about, add a record in the `video_ratings` table with the video ID, titles, and rating. Keep the `date_added`/`date_updated` timestamps aligned with the log if you want historical accuracy.
4. Start the add-on again; new plays/ratings will append automatically.

Tip: For larger imports, you can paste SQL like the snippet below directly into `sqlite3`:

```sql
INSERT OR IGNORE INTO video_ratings (
  yt_video_id, ha_title, yt_title, yt_channel, rating, date_added, play_count, rating_score
) VALUES (
  'ZmLIxKpgEPw', 'Song Title', 'Song Title', 'Artist', 'like',
  '2024-05-01 12:00:00', 1, 1
);
```

Because the new service performs UPSERTs, duplicates are safe—the latest metadata always wins.

## Troubleshooting

**No new videos being added to database**
- **Most common cause:** Missing YouTube API credentials
- Check if `credentials.json` and `token.pickle` exist in `/addon_configs/XXXXXXXX_youtube_thumbs/`
- Without these files, the addon cannot authenticate with YouTube API
- Solution: Copy both files from your project directory to the addon_configs location
- Restart the addon after copying credentials

**"No media currently playing"**
- Verify AppleTV is playing music
- Check media player entity ID is correct in add-on configuration

**"Video not found"**
- Ensure YouTube account is signed in on AppleTV
- Song must appear in your YouTube watch history
- Check duration matching (±2 seconds tolerance)

**OAuth/Credentials errors**
- Verify `credentials.json` is in `/addon_configs/XXXXXXXX_youtube_thumbs/`
- Also ensure `token.pickle` is present (contains authenticated session)
- Check add-on logs for specific error messages
- Look for: "credentials.json NOT found" or "token.pickle NOT found" in logs
- Ensure OAuth credentials are from Google Cloud Console with YouTube Data API v3 enabled
- The add-on will automatically create `token.pickle` on first run if only `credentials.json` exists

**`quotaExceeded` / 503 errors**
- Hitting the YouTube quota triggers an automatic 12-hour cooldown saved in `/config/youtube_thumbs/quota_guard.json` (set `quota_cooldown_hours` or `YTT_QUOTA_COOLDOWN_SECONDS` to tweak it).
- The HTTP API responds with 503 during that window; history tracking will skip new matches.
- Either wait for the cooldown to expire or delete the guard file after you’ve raised/reset your quota (only if you’re sure the quota has recovered).

**Check Logs**
- View in Home Assistant: Settings → Add-ons → YouTube Thumbs Rating → Log tab
- Set `log_level: DEBUG` in configuration for detailed output

## Logging

The add-on integrates with Home Assistant's logging system:

**Log Levels:**
- **INFO**: General application flow and successful operations
- **WARNING**: Rate limiting, multiple matches, non-critical issues
- **ERROR**: Failed operations with context
- **DEBUG**: Detailed tracebacks and debugging (set `log_level: DEBUG` in config)

**User Action Logging:**
User actions are logged with `[USER_ACTION]` prefix:
```
[USER_ACTION] LIKE | "Song Title" by Artist | ID: xyz123 | SUCCESS
[USER_ACTION] DISLIKE | "Another Song" | ID: abc456 | FAILED - Video not found
```

View logs in the add-on **Log** tab.

## Security

- OAuth credentials stored in `/addon_configs/` (persistent storage)
- Authentication handled automatically via Supervisor token
- The rating API always binds to `127.0.0.1`. sqlite_web defaults to `127.0.0.1` as well, but you can point `sqlite_web_host` to another interface if you intentionally want external access (consider SSH tunnels or trusted LANs only).
- ⚠️ Never share your `credentials.json` file

## Local Development

Running the Flask service outside the Home Assistant add-on? Spin up a virtual environment to isolate dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export HOME_ASSISTANT_URL="http://supervisor/core"  # or your actual HA URL
export MEDIA_PLAYER_ENTITY="media_player.apple_tv"
python app.py
```

Set `YTT_DB_PATH` if you want the SQLite file somewhere other than `/config/youtube_thumbs/ratings.db`.

## Support

For issues or questions:
- Check add-on logs first (Settings → Add-ons → YouTube Thumbs Rating → Log)
- Review [INSTALL.md](INSTALL.md) for complete documentation and troubleshooting

## Recent Updates (v1.28.0)

### ✅ Major Optimizations Completed

#### API Optimization & Performance (v1.23.0 - v1.24.0)
- ✅ **Phase 2: Enhanced Local Caching** - Implemented fuzzy title matching with 85% threshold using Levenshtein distance
- ✅ **Phase 5: Batch Pending Operations** - Batch processing for up to 50 video ratings per API call
- ✅ **Phase 6: Smarter Search Queries** - Sanitized search queries, pre-filtering with SQL LIKE clauses
- ✅ **Phase 8: Monitoring and Metrics** - Comprehensive `/metrics` endpoint with cache hit rates, API usage stats, and health scoring

#### Critical Bug Fixes (v1.25.0 - v1.26.0)
- Fixed Levenshtein algorithm memory issue (limited to 500 chars)
- Fixed QuotaGuard file lock race condition
- Fixed unbounded metrics deque growth
- Added SQL pre-filtering for better performance
- Improved error handling across all metrics categories

#### Code Quality Improvements (v1.27.0 - v1.28.0)
- Refactored large functions (100+ lines) into modular helpers
- Created dedicated helper modules: `rating_helpers.py`, `search_helpers.py`, `cache_helpers.py`
- Removed redundant code and optimized imports
- Improved code organization following Single Responsibility Principle

## API Optimization History

### ✅ Phase 1: Connection Pooling (Completed in earlier versions)
- Implemented connection reuse for YouTube API calls
- Reduced connection overhead significantly

### ✅ Phase 2: Enhanced Local Caching (v1.23.0)
- ✅ Added fuzzy title matching with Levenshtein distance
- ✅ Implemented 85% similarity threshold
- ✅ Check multiple variations before calling API

### ✅ Phase 3: Cache Negative Results (v1.18.0)
- ✅ Create `not_found_searches` table to track failed lookups
- ✅ Don't re-search same content for 24-48 hours
- ✅ Prevent repeated API calls for content that doesn't exist on YouTube

### ✅ Phase 4: Exponential Backoff for Quota Recovery (v1.19.0)
- ✅ Track attempt number in quota guard state
- ✅ Implement progressive cooldown: 2h → 4h → 8h → 16h → 24h (max)
- ✅ Reset attempt counter after successful API period
- ✅ Better recovery from quota exhaustion

### ✅ Phase 5: Batch Pending Operations (v1.24.0)
- ✅ Collect multiple video IDs for batch processing
- ✅ Use `videos.list` API with up to 50 IDs per call
- ✅ Reduce per-video API quota cost

### ✅ Phase 6: Smarter Search Queries (v1.23.0)
- ✅ Sanitize user input removing quotes and operators
- ✅ SQL pre-filtering to reduce dataset before fuzzy matching
- ✅ Consider channel filter if artist is consistently the channel

### ✅ Phase 8: Monitoring and Metrics (v1.24.0)
- ✅ Track cache hit rate, API calls per hour
- ✅ Add `/metrics` endpoint for API usage stats
- ✅ Health scoring system to detect performance issues
- ✅ Identify patterns in failed searches

## License

Provided as-is for personal use.
