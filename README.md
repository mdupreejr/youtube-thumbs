# YouTube Thumbs - Home Assistant Add-on

A Home Assistant add-on that lets you rate YouTube videos (👍/👎) for songs playing on your AppleTV. Perfect for Lutron remote integration or any automation that needs to rate music.

## About

This add-on provides a Flask service that integrates with Home Assistant to automatically rate YouTube videos based on what's currently playing on your AppleTV. Perfect for Lutron remote integration or any automation that needs to rate music.

## Features

- 🎵 Rate currently playing songs via REST API
- 🔍 Automatic YouTube video matching with fuzzy search
- 🛡️ Built-in rate limiting (configurable)
- 📝 Comprehensive logging integrated with Home Assistant
- 📊 Detailed user action audit trail
- 🕒 Background history tracker that logs every song even without ratings
- ⚡ Optimized performance with caching and connection pooling
- 💡 Reuses cached matches to avoid redundant YouTube searches
- 💾 Local SQLite history + sqlite_web UI on port 8080
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
Health check with rate limiter stats.

```json
{
  "status": "healthy",
  "rate_limiter": {
    "last_minute": 2,
    "last_hour": 15,
    "last_day": 47,
    "limits": { ... }
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

- Every 30 seconds the add-on polls Home Assistant for the currently playing song.
- New titles (title + duration) are matched against YouTube, stored in `ratings.db`, and receive an initial play count.
- Continuous playback only records once per hour; a second play increments `play_count` only if at least 60 minutes have passed since the last recorded listen (tweak via `HISTORY_PLAY_WINDOW_SECONDS` if needed).
- Set `ENABLE_HISTORY_TRACKER=false` to disable the background thread or tweak the cadence with `HISTORY_POLL_INTERVAL=<seconds>` if you need a slower/faster poll rate (exposed in the add-on config as `history_tracker_enabled` / `history_poll_interval`).

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
| `log_level` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `sqlite_web_host` | 127.0.0.1 | Bind address for sqlite_web (set to `0.0.0.0` only if you need LAN access) |
| `sqlite_web_port` | 8080 | Port for sqlite_web when exposed to your LAN; ignored when using HA ingress (the default) |
| `history_tracker_enabled` | true | Toggle the background poller that logs every song |
| `history_poll_interval` | 30 | Seconds between Home Assistant polls (10–300 allowed) |

**Note:** The add-on automatically handles authentication using the Supervisor token.

### Automatic Quota Cooldown

Any time Google responds with `quotaExceeded`, the add-on writes
`/config/youtube_thumbs/quota_guard.json`, logs the failure, and pauses all YouTube
API calls for 24 hours (configurable via `YTT_QUOTA_COOLDOWN_SECONDS`). During the
cooldown the HTTP endpoints return `503` with a friendly error message, and the
history tracker skips matching attempts. Delete the guard file only after your
quota resets if you need to re-enable access early.

## Data Storage & sqlite_web

- All history lives in `ratings.db` at `/config/youtube_thumbs/ratings.db` (perfect for easy backups with ZFS or snapshots).
- The add-on automatically starts [`sqlite_web`](https://github.com/coleifer/sqlite-web) and opens it via HA ingress.
  - Use the add-on's **OPEN WEB UI** button; Home Assistant proxies the sqlite_web instance into your browser even when it is bound to `127.0.0.1`.
  - Logs for the UI are written to `/config/youtube_thumbs/sqlite_web.log`.
- Prefer a different bind target? Keep `sqlite_web_host` at `127.0.0.1` for ingress/HA-only access or set it to `0.0.0.0` to expose the DB UI to your LAN. Pair it with the `sqlite_web_port` option (or the `SQLITE_WEB_HOST`/`SQLITE_WEB_PORT` env vars) if you need custom settings.
- When `sqlite_web_host` is not localhost, the **OPEN WEB UI** button is bypassed—browse to `http://<home-assistant-host>:<sqlite_web_port>` directly instead.
- Every successful match is cached, so follow-up requests for the exact same Home Assistant title reuse the stored video ID and skip the expensive YouTube search entirely.
- If you repeat the same thumbs action as last time, the cached rating prevents us from pinging YouTube at all.

### Manual import from the legacy `ratings.log`

Importing is a one-time operation, so feel free to do it manually:

1. Stop the add-on (to release the SQLite lock).
2. Open `/config/youtube_thumbs/ratings.log` alongside `sqlite_web` (or the `sqlite3` CLI).
3. For each entry you care about, add a record in the `video_ratings` table with the video ID, titles, and rating. Keep the `date_added`/`date_updated` timestamps aligned with the log if you want historical accuracy.
4. Start the add-on again; new plays/ratings will append automatically.

Tip: For larger imports, you can paste SQL like the snippet below directly into `sqlite3`:

```sql
INSERT OR IGNORE INTO video_ratings (
  video_id, ha_title, yt_title, channel, rating, date_added, date_updated, play_count, rating_count
) VALUES (
  'ZmLIxKpgEPw', 'Song Title', 'Song Title', 'Artist', 'like',
  '2024-05-01 12:00:00', '2024-05-01 12:00:00', 1, 1
);
```

Because the new service performs UPSERTs, duplicates are safe—the latest metadata always wins.

## Troubleshooting

**"No media currently playing"**
- Verify AppleTV is playing music
- Check media player entity ID is correct in add-on configuration

**"Video not found"**
- Ensure YouTube account is signed in on AppleTV
- Song must appear in your YouTube watch history
- Check duration matching (±2 seconds tolerance)

**OAuth/Credentials errors**
- Verify `credentials.json` is in `/addon_configs/XXXXXXXX_youtube_thumbs/`
- Check add-on logs for specific error messages
- Ensure OAuth credentials are from Google Cloud Console with YouTube Data API v3 enabled
- The add-on will automatically create `token.pickle` on first run

**`quotaExceeded` / 503 errors**
- Hitting the YouTube quota triggers an automatic 24-hour cooldown saved in `/config/youtube_thumbs/quota_guard.json`.
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

## License

Provided as-is for personal use.
