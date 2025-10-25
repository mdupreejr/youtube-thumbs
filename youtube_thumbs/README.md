# YouTube Thumbs Rating Add-on

**Version: 1.3.4**

Rate YouTube videos (👍/👎) for songs playing on your AppleTV through Home Assistant.

## About

This add-on provides a Flask service that integrates with Home Assistant to automatically rate YouTube videos based on what's currently playing on your AppleTV. Perfect for Lutron remote integration or any automation that needs to rate music.

## Features

- 🎵 Automatic YouTube video matching with fuzzy search
- 🛡️ Built-in rate limiting (configurable)
- 📝 Comprehensive logging with separate audit trails
- ⚡ Optimized performance with caching and connection pooling
- 🔒 OAuth authentication preservation

## Installation

1. Copy this entire directory to `/addons/youtube_thumbs/` on your Home Assistant (accessible via Samba at `\\homeassistant.local\addons\`)
2. Copy your `credentials.json` and `token.pickle` to the same directory
3. In Home Assistant, go to Settings → Add-ons → Add-on Store
4. Refresh the page - the local add-on should be automatically detected
5. Find "YouTube Thumbs Rating" in the Local Add-ons section and click Install

## Configuration

**Required:**
- `home_assistant_token`: Your HA long-lived access token
- `media_player_entity`: Your media player entity ID (e.g., `media_player.apple_tv`)

**Optional:**
- `port`: Service port (default: 21812)
- `rate_limit_per_minute`: Max requests per minute (default: 10)
- `rate_limit_per_hour`: Max requests per hour (default: 100)
- `rate_limit_per_day`: Max requests per day (default: 500)
- `log_level`: Logging verbosity (default: INFO)

See DOCS.md for detailed installation and configuration instructions.

## Usage

After installation and configuration, add REST commands to your `configuration.yaml`:

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

Then create automations to call these services based on button presses or other triggers.

## Support

Check the add-on logs for troubleshooting. For detailed documentation, see DOCS.md.
