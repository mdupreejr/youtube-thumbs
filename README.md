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
- ⚡ Optimized performance with caching and connection pooling
- 🔒 OAuth authentication preservation

## Installation

### Quick Install

1. Add this GitHub repository to Home Assistant Add-on Store
2. Install the "YouTube Thumbs Rating" add-on
3. Copy your `credentials.json` to `/addon_configs/XXXXXXXX_youtube_thumbs/`
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

1. Service fetches current media from Home Assistant
2. Searches YouTube for matching video (by title, artist, duration ±2s)
3. Filters results using fuzzy title matching (50%+ word overlap)
4. Rates the best match on YouTube

## Add-on Configuration Options

Configure these in the add-on Configuration tab:

| Option | Default | Description |
|--------|---------|-------------|
| `media_player_entity` | (required) | Media player entity ID (e.g., `media_player.apple_tv`) |
| `port` | 21812 | Service port |
| `rate_limit_per_minute` | 10 | Max YouTube API calls in 60-second window |
| `rate_limit_per_hour` | 100 | Max YouTube API calls in 3600-second window |
| `rate_limit_per_day` | 500 | Max YouTube API calls in 24-hour period |
| `log_level` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

**Note:** The add-on automatically handles authentication using the Supervisor token.

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
- Service only accessible from localhost (not exposed to network)
- ⚠️ Never share your `credentials.json` file

## Support

For issues or questions:
- Check add-on logs first (Settings → Add-ons → YouTube Thumbs Rating → Log)
- Review [INSTALL.md](INSTALL.md) for complete documentation and troubleshooting

## License

Provided as-is for personal use.
