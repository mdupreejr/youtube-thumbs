# YouTube Thumbs Rating Add-on Documentation

**Version: 1.3.5**

Rate YouTube videos (👍/👎) for songs playing on your AppleTV through Home Assistant.

## Features

- 🎵 Rate currently playing songs via REST API
- 🔍 Automatic YouTube video matching with fuzzy search
- 🛡️ Built-in rate limiting (configurable)
- 📝 Comprehensive logging with separate log files
- ⚡ Optimized with regex caching and connection pooling

## Installation

### Step 1: Add Local Add-on Repository

1. Copy the entire `addon/youtube_thumbs` directory to your Home Assistant's local add-ons directory:
   ```
   /addons/local/youtube_thumbs/
   ```

2. You can do this via:
   - **Samba/SMB share**: Browse to `\\homeassistant.local\addons\` (Windows) or `smb://homeassistant.local/addons/` (Mac), then create/navigate to the `local` subdirectory
   - **Terminal & SSH Add-on**: 
     ```bash
     cd /addons
     mkdir -p local
     # Then extract tar.gz to local/ or copy files to local/youtube_thumbs/
     ```

### Step 2: Copy OAuth Credentials

**IMPORTANT**: You must copy your existing OAuth files to preserve your authentication:

1. Copy `credentials.json` to `/addons/local/youtube_thumbs/credentials.json` (via Samba: `\\homeassistant.local\addons\local\youtube_thumbs\credentials.json`)
2. Copy `token.pickle` to `/addons/local/youtube_thumbs/token.pickle` (via Samba: `\\homeassistant.local\addons\local\youtube_thumbs\token.pickle`)

These files will be automatically moved to persistent storage (`/data/`) on first run.

### Step 3: Install the Add-on

1. Navigate to **Settings** → **Add-ons** → **Add-on Store**
2. Click the **⋮** (three dots) menu in the top right
3. Select **Repositories**
4. Add: `file:///config/addon` (if not already added for local add-ons)
5. Refresh the page
6. Find **YouTube Thumbs Rating** in the list
7. Click on it and press **INSTALL**

### Step 4: Configure the Add-on

Before starting, configure the add-on:

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
- **log_max_size_mb**: Default is `10` MB

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

The add-on creates three log files in `/data/` (persistent storage):

- **app.log**: General application logs
- **user_actions.log**: User action audit trail (thumbs up/down)
- **errors.log**: Error tracking with stack traces

View logs via:
- Add-on **Log** tab (shows app.log)
- File Editor add-on to view individual log files in `/addon_configs/youtube_thumbs/`

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
2. Verify `credentials.json` and `token.pickle` are in `/addons/local/youtube_thumbs/`
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

1. Replace files in `/addons/local/youtube_thumbs/` (via Samba share `\\homeassistant.local\addons\local\youtube_thumbs\`)
2. Go to Add-on Info tab
3. Click **Rebuild**
4. Restart the add-on

Your OAuth credentials and configuration will persist.

## Support

For issues, check:
- Add-on logs (Info tab)
- Home Assistant logs (Settings → System → Logs)
- Developer Tools → States (verify media player entity)
