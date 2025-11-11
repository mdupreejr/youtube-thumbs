# YouTube Thumbs - Home Assistant Add-on

Rate YouTube videos (👍/👎) for songs playing on your AppleTV through Home Assistant. Perfect for Lutron Pico remote integration or any automation that needs to rate music.

## Features

- 🎵 **Rate YouTube videos** - Like/dislike songs via REST API or Web UI
- ⚡ **Bulk Rating Interface** - Rate multiple unrated songs at once
- 🔍 **Smart video matching** - Automatic YouTube search with duration matching and caching
- 📊 **Statistics & Analytics** - Track playback stats, most played songs, and rating distribution
- 🛡️ **Quota protection** - Queue-based processing prevents quota exhaustion
- 💾 **SQLite database** - Local storage with comprehensive metadata tracking
- 📈 **API monitoring** - Detailed logging of all YouTube API calls and quota usage

## Quick Start

See **[INSTALL.md](INSTALL.md)** for complete installation and OAuth setup instructions.

### Basic Steps

1. Add this repository to Home Assistant
2. Install "YouTube Thumbs Rating" add-on
3. Copy `credentials.json` to `/addon_configs/XXXXXXXX_youtube_thumbs/`
4. Configure media player entity in add-on configuration
5. Start the add-on

**First run**: The add-on will automatically generate `token.json` and prompt you to authorize via the OAuth flow.

## Configuration

### Add-on Options

| Option | Default | Description |
|--------|---------|-------------|
| `media_player_entity` | (required) | Your AppleTV media player entity ID |
| `log_level` | INFO | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `search_max_results` | 25 | Max YouTube search results to fetch |
| `search_max_candidates` | 10 | Max duration-matched candidates to check |
| `debug_endpoints_enabled` | false | Enable debug API endpoints |

### Home Assistant Integration

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

Create automations to call these services:

```yaml
automation:
  - alias: "Lutron Pico - Thumbs Up"
    trigger:
      - platform: device
        device_id: your_pico_remote_id
        type: press
        subtype: button_1
    action:
      - service: rest_command.youtube_thumbs_up

  - alias: "Lutron Pico - Thumbs Down"
    trigger:
      - platform: device
        device_id: your_pico_remote_id
        type: press
        subtype: button_2
    action:
      - service: rest_command.youtube_thumbs_down
```

## Web Interface

Access via **OPEN WEB UI** button in the add-on page:

- **Tests** - System status with live health checks, queue worker status, quota usage, cache performance, and detailed metrics
- **Bulk Rating** - Rate multiple unrated songs at once with pagination
- **Stats** - Playback statistics, rating distribution, most played videos, and top channels
- **Database** - Browse and filter database tables (video ratings, queue, search cache)
- **Rated Songs** - View history of all rated videos with timestamps and ratings
- **Matches** - Browse matched videos showing search results and duration matching
- **Recent** - Recent activity log across all operations
- **Errors** - Error log for troubleshooting failed operations
- **API Calls** - Detailed YouTube API call history with quota tracking and costs
- **Queue** - View pending and processing queue items (searches and ratings)
- **DB Admin** - Full sqlite_web interface for advanced database queries and management

## How It Works

When you trigger a rating (via REST API or Web UI), the addon:
1. Fetches current media from Home Assistant
2. Checks database cache for exact match (content hash or title+duration)
3. If no cache hit: Queues search operation for background processing
4. Queue worker searches YouTube, filters by duration, and caches the match
5. Queues and processes the rating operation via YouTube API
6. Updates database with rating and metadata

**See [ARCHITECTURE.md](ARCHITECTURE.md#video-matching-system) for detailed matching algorithm and caching logic.**

### Queue Architecture

All YouTube API calls are processed through a unified queue system with automatic rate limiting and quota protection. The queue worker processes operations sequentially with 1-minute delays between API calls. Ratings are prioritized over searches.

**See [ARCHITECTURE.md](ARCHITECTURE.md#queue-system) for detailed queue architecture and implementation.**

## Quota Management

YouTube Data API v3 has a daily quota of **10,000 units** that resets at **midnight Pacific Time**. Common operations cost: Search (100 units), Rate video (50 units), Get details (1 unit).

When quota is exceeded, the queue worker automatically pauses until midnight Pacific. New requests continue to queue and will be processed after quota resets.

**See [ARCHITECTURE.md](ARCHITECTURE.md#quota-management) for detailed quota costs, monitoring, and management strategies.**

## API Endpoints

### Rate Current Song

- `POST /thumbs_up` - Rate currently playing song as like
- `POST /thumbs_down` - Rate currently playing song as dislike

### Direct Video Rating

- `POST /api/rate/<video_id>/like` - Rate specific YouTube video as like
- `POST /api/rate/<video_id>/dislike` - Rate specific YouTube video as dislike

### System Status

- `GET /health` - Health check with detailed system stats
- `GET /metrics` - Prometheus-compatible metrics

### Data Access

- `GET /api/unrated?page=1` - Paginated list of unrated songs
- `GET /api/stats/summary` - Statistics summary

For complete API documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Database

All data is stored in SQLite database at `/config/youtube_thumbs/ratings.db`. The database includes tables for video ratings, queue operations, API call logs, and caching.

Access via **Database Admin** in the web interface or explore using the **Data Viewer** page.

**See [ARCHITECTURE.md](ARCHITECTURE.md#database-schema) for complete database schema and field documentation.**

## Troubleshooting

### No videos being rated

**Check credentials:**
```bash
# Verify files exist in addon_configs directory
ls -la /addon_configs/XXXXXXXX_youtube_thumbs/
# Should show: credentials.json and token.json
```

**Check queue worker:**
- Open add-on **Log** tab
- Look for `[QUEUE]` prefixed messages
- Worker processes one item from queue then waits 1 minute before starting the next item from the queue

### "No media currently playing"

- Verify media player is playing YouTube content on AppleTV
- Check `media_player_entity` in add-on configuration
- Test entity in Home Assistant Developer Tools

### OAuth/Authentication errors

- Ensure `credentials.json` is from Google Cloud Console
- Verify YouTube Data API v3 is enabled in your Google Cloud project
- Delete `token.json` and restart to re-authenticate

### Quota exceeded

- **Wait**: Quota automatically resets at midnight Pacific Time
- **Check usage**: View API Calls page in web UI
- **Optimize**: Reduce `search_max_results` in configuration

**Always check logs first**: Settings → Add-ons → YouTube Thumbs Rating → Log

## Security

- OAuth credentials stored in `/addon_configs/` (persistent across updates)
- Authentication via Home Assistant Supervisor token (automatic)
- Uses host networking (`host_network: true`) for seamless HA integration
- API bound to `0.0.0.0:21812` (accessible via `localhost:21812` from Home Assistant)
- Web UI accessible through Home Assistant ingress proxy
- Database viewer bound to `127.0.0.1` by default (localhost only)
- ⚠️ **Never share your `credentials.json` or `token.json` files**

## Documentation

- **[INSTALL.md](INSTALL.md)** - Detailed installation and OAuth setup guide
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technical architecture, database schema, and implementation details

## Contributing

Issues and pull requests welcome! Please include:
- Home Assistant version
- Add-on version
- Relevant log excerpts
- Steps to reproduce

## License

Provided as-is for personal use.
