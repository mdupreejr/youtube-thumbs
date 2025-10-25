# YouTube Thumbs Rating Add-on Documentation

Rate YouTube videos (👍/👎) for songs playing on your AppleTV through Home Assistant.

## Features

- 🎵 Rate currently playing songs via REST API
- 🔍 Automatic YouTube video matching with fuzzy search
- 🛡️ Built-in rate limiting (configurable)
- 📝 Comprehensive logging with separate log files
- ⚡ Optimized with regex caching and connection pooling

## Installation

For quick installation instructions, see [INSTALL.md](INSTALL.md).

### Prerequisites

Before installing, you need YouTube OAuth credentials:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable **YouTube Data API v3**
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Choose **Desktop app** as the application type
6. Download the credentials and save as `credentials.json`
7. Run the OAuth flow once (outside Home Assistant) to generate `token.pickle`:
   ```bash
   # On your computer (not in HA), with Python installed:
   python3 -m venv venv
   source venv/bin/activate
   pip install google-auth-oauthlib google-api-python-client
   # Place credentials.json in current directory
   # Run a quick OAuth flow script or use the app.py from this repo
   ```
8. After authorizing, you'll have both `credentials.json` and `token.pickle`

### Step 1: Add Repository to Home Assistant

1. Navigate to **Settings** → **Add-ons** → **Add-on Store**
2. Click the **⋮** (three dots) menu in the top right
3. Select **Repositories**
4. Add: `https://github.com/mdupreejr/youtube-thumbs`
5. Click **Add** → **Close**

### Step 2: Install the Add-on

1. Refresh the Add-on Store
2. Find **YouTube Thumbs Rating** in the available add-ons
3. Click **INSTALL**

### Step 3: Copy OAuth Credentials

Copy your OAuth files to the add-on's config directory:

1. Navigate to `/addon_configs/XXXXXXXX_youtube_thumbs/` (via File Editor or Samba)
2. Copy both files:
   - `credentials.json`
   - `token.pickle`

**Samba path**: `\\homeassistant.local\addon_configs\XXXXXXXX_youtube_thumbs\`

### Step 4: Configure the Add-on

Configure the add-on before starting:

1. Go to the **Configuration** tab
2. Set the following options:

#### Required Configuration

- **home_assistant_token**: Your Home Assistant Long-Lived Access Token
  - Get this from: Profile → Long-Lived Access Tokens → Create Token
  
- **media_player_entity**: Your media player entity ID (e.g., `media_player.apple_tv`)
  - Find this in Developer Tools → States

#### Optional Configuration

- **home_assistant_url**: Default is `http://supervisor/core` (recommended for add-ons)
- **port**: Default is `21812` (change if needed)
- **host**: Default is `0.0.0.0` (usually no need to change)
- **rate_limit_per_minute**: Default is `10`
- **rate_limit_per_hour**: Default is `100`
- **rate_limit_per_day**: Default is `500`
- **log_level**: Default is `INFO` (options: DEBUG, INFO, WARNING, ERROR, CRITICAL)

### Step 5: Start the Add-on

1. Go to the **Info** tab
2. Enable **Start on boot** (recommended)
3. Enable **Watchdog** (auto-restart on crashes)
4. Click **START**

### Step 6: Check Logs

1. Go to the **Log** tab
2. Verify the service started successfully
3. You should see:
   ```
   Starting YouTube Thumbs service on 0.0.0.0:21812...
   Home Assistant URL: http://supervisor/core
   Media Player Entity: media_player.apple_tv
   ```

## Home Assistant Configuration

### Add REST Commands

Add this to your `configuration.yaml`:

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

**Note**: Use `localhost` since the add-on uses `host_network: true`.

Restart Home Assistant after adding this configuration.

### Create Automations

Example automation for Lutron remote:

```yaml
automation:
  - alias: "Music - Thumbs Up"
    trigger:
      - platform: device
        device_id: your_lutron_device_id
        type: press
        subtype: button_1
    action:
      - service: rest_command.youtube_thumbs_up

  - alias: "Music - Thumbs Down"
    trigger:
      - platform: device
        device_id: your_lutron_device_id
        type: press
        subtype: button_2
    action:
      - service: rest_command.youtube_thumbs_down
```

### Test the Integration

1. Play a song on your AppleTV
2. In Home Assistant, go to Developer Tools → Services
3. Call the service `rest_command.youtube_thumbs_up`
4. Check the add-on logs to verify it worked

## Logs

The add-on integrates with Home Assistant's logging system.

View logs via:
- Add-on **Log** tab (shows real-time application logs)
- Set `log_level: DEBUG` in configuration for detailed output

## API Endpoints

### `POST /thumbs_up`
Rate the currently playing song as "like".

### `POST /thumbs_down`
Rate the currently playing song as "dislike".

### `GET /health`
Health check with rate limiter statistics.

Response:
```json
{
  "status": "healthy",
  "rate_limiter": {
    "last_minute": 2,
    "last_hour": 15,
    "last_day": 47
  }
}
```

## Troubleshooting

### Add-on Won't Start

1. Check the **Log** tab for errors
2. Verify `credentials.json` and `token.pickle` are in `/addon_configs/XXXXXXXX_youtube_thumbs/`
3. Ensure Home Assistant token is valid
4. Check media player entity ID is correct

### "No media currently playing" Error

- Verify AppleTV is actually playing music
- Check `media_player_entity` matches your entity ID exactly
- Test the media player in Developer Tools → States

### OAuth/YouTube API Errors

- Verify `credentials.json` is from Google Cloud Console with YouTube Data API v3 enabled
- Check `token.pickle` is valid (not expired)
- If needed, delete `token.pickle` and re-run OAuth flow (may require manual intervention)

### Rate Limiting Issues

- Check current limits via `GET /health` endpoint
- Adjust rate limits in add-on configuration
- Restart add-on after changing configuration

### Can't Access Logs

- Main logs appear in the add-on **Log** tab
- Detailed logs are in `/addon_configs/youtube_thumbs/` (use File Editor or SSH)
- Enable DEBUG log level for more verbose output

## Security Notes

- ⚠️ OAuth tokens are stored in `/data/` (persistent, but container-local)
- Home Assistant token is stored in add-on options (encrypted by Supervisor)
- Service only accessible from localhost (not exposed to network)
- No external access unless you explicitly configure port forwarding

## Updates

To update the add-on:

1. Go to **Settings** → **Add-ons** → **YouTube Thumbs Rating**
2. Click the **Info** tab
3. If an update is available, click **Update**
4. The add-on will automatically restart with the new version

Your OAuth credentials (in `/addon_configs/`) and configuration will persist.

## Support

For issues, check:
- Add-on logs (Info tab)
- Home Assistant logs (Settings → System → Logs)
- Developer Tools → States (verify media player entity)
