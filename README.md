# YouTube Thumbs - Home Assistant Add-on

A Home Assistant add-on that lets you rate YouTube videos (👍/👎) for songs playing on your AppleTV. Perfect for Lutron remote integration or any automation that needs to rate music.

## Features

- 🎵 **Rate YouTube videos** via REST API based on currently playing content
- ⚡ **Bulk Rating Interface** - Quickly rate up to 50 unrated songs at once
- 🔍 **Smart matching** - Automatic YouTube video matching with caching
- 📊 **Database Viewer** - Built-in sqlite_web interface
- 🕒 **History tracking** - Automatic background tracking of all songs
- 🛡️ **Quota protection** - Built-in rate limiting and cooldown
- 💾 **SQLite storage** - Local database with comprehensive metadata

## Quick Start

See **[INSTALL.md](INSTALL.md)** for complete installation instructions including OAuth setup.

### Basic Steps

1. Add this repository to Home Assistant
2. Install "YouTube Thumbs Rating" add-on
3. Copy `credentials.json` to `/addon_configs/XXXXXXXX_youtube_thumbs/`
4. Configure media player entity
5. Start the add-on

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

| Option | Default | Description |
|--------|---------|-------------|
| `media_player_entity` | (required) | Media player entity ID |
| `port` | 21812 | Service port |
| `rate_limit_per_minute` | 10 | Max API calls per minute |
| `rate_limit_per_hour` | 100 | Max API calls per hour |
| `rate_limit_per_day` | 500 | Max API calls per day |
| `quota_cooldown_hours` | 12 | Hours to pause after quota error |
| `log_level` | INFO | Logging level |
| `history_tracker_enabled` | true | Background history tracking |
| `history_poll_interval` | 60 | Seconds between polls |

For all options, see config.json.

## Web Interface

Access the web interface by clicking **OPEN WEB UI** in the addon page:

- **System Tests** - Test connectivity and view system status
- **Bulk Rating** - Rate multiple unrated songs quickly
- **Statistics** - View playback stats and top songs
- **Logs** - Browse activity logs
- **Data Viewer** - Browse database (column selection, sorting, pagination)
- **Database Viewer** - Full sqlite_web interface

## How It Works

1. Fetches current media from Home Assistant (YouTube content only)
2. Checks SQLite cache for exact matches (content hash or title+duration)
3. If no cache hit, searches YouTube with cleaned title
4. Filters results by exact duration match
5. Rates the best match on YouTube and stores in database

### Quota Protection

- Automatic 12-hour cooldown after `quotaExceeded` errors
- HTTP endpoints return `503` during cooldown
- Videos stored as "pending" during quota exhaustion
- Automatic quota recovery detection and retry
- See [ARCHITECTURE.md](ARCHITECTURE.md) for details

## API Endpoints

### Rate Current Song
- `POST /thumbs_up` - Rate currently playing song as like
- `POST /thumbs_down` - Rate currently playing song as dislike

### Direct Rating
- `POST /api/rate/<video_id>/like` - Rate specific video as like
- `POST /api/rate/<video_id>/dislike` - Rate specific video as dislike

### System
- `GET /health` - Health check with rate limiter and quota stats
- `GET /metrics` - Comprehensive metrics for monitoring

### Bulk Rating
- `GET /api/unrated?page=1` - Get paginated unrated songs

For complete API documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Data Storage

All data stored in `/config/youtube_thumbs/ratings.db`:

- **video_ratings** - All matched videos with metadata, ratings, play counts
- **not_found_searches** - Caches failed searches (7 days)
- **import_history** - Tracks imported YouTube exports

Access via the **Database Viewer** link in the web interface.

For database schema details, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Troubleshooting

### No videos being added
- Check `/addon_configs/XXXXXXXX_youtube_thumbs/` for `credentials.json` and `token.pickle`
- Restart addon after copying credentials

### "No media currently playing"
- Verify AppleTV is playing music
- Check media player entity ID in configuration

### OAuth/Credentials errors
- Ensure `credentials.json` is from Google Cloud Console
- YouTube Data API v3 must be enabled

### Quota exceeded / 503 errors
- Automatic 12-hour cooldown activated
- Wait for cooldown or delete `/config/youtube_thumbs/quota_guard.json` (only if quota reset)

### Test buttons not working
- Rebuild the addon (Settings → Add-ons → 3 dots → Rebuild)

**Check Logs**: Settings → Add-ons → YouTube Thumbs Rating → Log tab

## Documentation

- **[INSTALL.md](INSTALL.md)** - Installation and OAuth setup
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technical details, database schema, matching system
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and updates
- **[RETRY_SYSTEM.md](RETRY_SYSTEM.md)** - Pending video retry system

## Security

- OAuth credentials stored in `/addon_configs/` (persistent)
- Authentication via Supervisor token (automatic)
- Rating API bound to `127.0.0.1` (localhost only)
- Database viewer accessible through ingress only
- ⚠️ Never share your `credentials.json` file

## License

Provided as-is for personal use.
