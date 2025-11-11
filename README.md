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

- **System Tests** - Health check with live status of Home Assistant, YouTube API, and database
- **Bulk Rating** - Rate unrated songs with pagination
- **Statistics** - Playback stats, rating distribution, most played videos, top channels
- **Logs** - Browse activity logs, API calls, matches, and recent activity
- **Data Viewer** - Browse database tables with sorting and filtering
- **Database Admin** - Full sqlite_web interface for advanced queries

## How It Works

### Rating Flow

1. **User triggers rating** (via REST API or Web UI)
2. **Fetch current media** from Home Assistant
3. **Check database cache** for exact match (content hash or title+duration)
4. **If no cache hit**: Enqueue search operation
5. **Queue worker processes**:
   - Searches YouTube with cleaned title + artist/album metadata
   - Filters by duration match (YouTube always reports +1s longer than HA)
   - Uses ±2s tolerance to handle variations
   - Caches match for future lookups
6. **Enqueue rating operation**
7. **Queue worker rates** the video on YouTube
8. **Update database** with rating and metadata

### Queue Architecture

**All YouTube API calls go through a single background queue worker:**

- **Queue worker** - Separate process that processes 1 item per minute
- **Priority system** - Ratings (priority 1) processed before searches (priority 2)
- **Quota protection** - Automatically pauses until midnight PT when quota exceeded
- **Crash recovery** - Resets stuck items on restart
- **No threading** - Simple, reliable processing

**Why this matters:** The queue prevents quota exhaustion by rate-limiting API calls and provides a central point for logging, monitoring, and quota management.

## Quota Management

YouTube Data API v3 has a daily quota of **10,000 units** that resets at **midnight Pacific Time**.

### Quota Costs

- Search: **100 units**
- Get video details: **1 unit**
- Rate video: **50 units**
- Get rating: **1 unit**
- Channel info (startup check): **1 unit**

### When Quota is Exceeded

1. Queue worker detects quota error
2. Worker pauses until midnight Pacific Time
3. New requests continue to queue but aren't processed
4. Web UI shows quota exceeded status
5. Automatic resume after quota resets

**Check quota usage**: View API Calls page in web UI for detailed quota tracking.

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

## Database Schema

All data stored in `/config/youtube_thumbs/ratings.db`:

| Table | Purpose |
|-------|---------|
| `video_ratings` | All matched videos with metadata, ratings, and play counts |
| `queue` | Unified queue for search and rating operations |
| `api_call_log` | Detailed log of every YouTube API call with timestamps and quota costs |
| `search_results_cache` | Cached YouTube search results (30 day TTL) |
| `stats_cache` | Cached statistics for web UI performance |

Access via **Database Admin** in the web interface or explore using the **Data Viewer** page.

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
- Worker should process 1 item per minute

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

### Web UI shows errors

- Check add-on logs for stack traces
- Try clearing browser cache
- Rebuild add-on: Settings → Add-ons → YouTube Thumbs → ⋮ → Rebuild

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
