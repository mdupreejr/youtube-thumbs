# Quick Installation Guide


### 3. Install the Add-on

1. Open Home Assistant web interface
2. Navigate to **Settings** → **Add-ons** → **Add-on Store**
3. Click the **⋮** (three dots) menu in top right corner
4. Select **Repositories**
5. If not already present, the local add-ons should be automatically detected
6. Click **Refresh** or reload the page
7. Scroll down to find **"YouTube Thumbs Rating"** in the Local Add-ons section
8. Click on it and press **INSTALL**

### 4. Configure the Add-on

Before starting the add-on, you MUST configure it:

1. After installation, click on the add-on to open it
2. Go to the **Configuration** tab
3. Fill in the required fields:

```yaml
home_assistant_url: http://supervisor/core
home_assistant_token: "YOUR_LONG_LIVED_ACCESS_TOKEN_HERE"
media_player_entity: media_player.apple_tv
port: 21812
host: 0.0.0.0
rate_limit_per_minute: 10
rate_limit_per_hour: 100
rate_limit_per_day: 500
log_level: INFO
log_max_size_mb: 10
```

**To get your Home Assistant token:**
1. Click your profile (bottom left)
2. Scroll down to "Long-Lived Access Tokens"
3. Click "Create Token"
4. Give it a name like "YouTube Thumbs"
5. Copy the token and paste it in the configuration

**To find your media player entity:**
1. Go to Developer Tools → States
2. Search for your AppleTV (e.g., `media_player.apple_tv`)
3. Copy the exact entity ID

4. Click **SAVE** at the bottom of the configuration page

### 5. Start the Add-on

1. Go to the **Info** tab
2. Toggle **"Start on boot"** to ON (recommended)
3. Toggle **"Watchdog"** to ON (auto-restart on crashes)
4. Click **START**

### 7. Configure Home Assistant

Add REST commands to your `configuration.yaml`:

1. Go to **Settings** → **Add-ons** → **File Editor** (or use your preferred editor)
2. Open `configuration.yaml`
3. Add this configuration:

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

4. Save the file
5. Go to **Developer Tools** → **YAML** → **Restart** (or **Check Configuration** first)
6. Wait for Home Assistant to restart

### 8. Test the Integration

1. Start playing music on your AppleTV
2. Go to **Developer Tools** → **Services**
3. Search for `rest_command.youtube_thumbs_up`
4. Click **CALL SERVICE**
5. Check the add-on logs (Settings → Add-ons → YouTube Thumbs Rating → Log tab)
6. You should see a success message with the video that was rated

### 9. Create Automations (Optional)

Example for Lutron remote buttons:

```yaml
automation:
  - alias: "Music - Thumbs Up"
    trigger:
      - platform: device
        device_id: YOUR_LUTRON_DEVICE_ID
        type: press
        subtype: button_1
    action:
      - service: rest_command.youtube_thumbs_up

  - alias: "Music - Thumbs Down"
    trigger:
      - platform: device
        device_id: YOUR_LUTRON_DEVICE_ID
        type: press
        subtype: button_2
    action:
      - service: rest_command.youtube_thumbs_down
```

## Troubleshooting

### Add-on won't start
- Check logs for specific error messages
- Verify Home Assistant token is valid
- Verify media player entity ID is correct

### "No media currently playing" error
- Make sure music is actually playing on your AppleTV
- Verify the entity ID matches exactly (check Developer Tools → States)

### OAuth errors
- Verify `credentials.json` is from Google Cloud Console with YouTube Data API v3 enabled
- Check `token.pickle` hasn't expired

### Can't find the add-on in the store
- Try refreshing the Add-on Store page
- Check Settings → Add-ons → Add-on Store → ⋮ → Check for updates
- Restart Home Assistant if the add-on still doesn't appear

## Next Steps

Once everything is working:
- Monitor the logs to ensure ratings are working correctly
- Adjust rate limits if needed in the add-on configuration

For detailed documentation, see DOCS.md.
