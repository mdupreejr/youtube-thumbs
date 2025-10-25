# YouTube Thumbs - Rate Songs from Home Assistant

A Flask service that lets you rate YouTube videos (👍/👎) for songs playing on your AppleTV through Home Assistant. Perfect for Lutron remote integration.

## Features

- 🎵 Rate currently playing songs via REST API
- 🔍 Automatic YouTube video matching with fuzzy search
- 🛡️ Built-in rate limiting (10/min, 100/hour, 500/day)
- 📝 Comprehensive logging with separate log files for actions and errors
- 📊 Detailed user action audit trail
- ⚡ Optimized with regex caching and connection pooling

## Quick Start

### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**⚠️ Important:** Always activate the venv before running any Python commands or making changes to the project.

### 2. Setup YouTube API

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **YouTube Data API v3**
3. Create **OAuth Desktop** credentials
4. Download and save as `credentials.json`

### 3. Configure Environment

```bash
cp .env.example .env
nano .env
```

Fill in your details:
```env
HOME_ASSISTANT_URL=http://homeassistant.local:8123
HOME_ASSISTANT_TOKEN=your_long_lived_access_token
MEDIA_PLAYER_ENTITY=media_player.apple_tv
PORT=21812
```

**Get HA Token:** Profile → Long-Lived Access Tokens → Create Token

### 4. First Run - OAuth Setup

```bash
python simple_oauth.py
```

This opens your browser to authorize. After granting access, `token.pickle` is created automatically.

### 5. Configure Home Assistant

Add to your `configuration.yaml`:

```yaml
rest_command:
  youtube_thumbs_up:
    url: "http://YOUR_SERVER_IP:21812/thumbs_up"
    method: POST
    timeout: 30
    
  youtube_thumbs_down:
    url: "http://YOUR_SERVER_IP:21812/thumbs_down"
    method: POST
    timeout: 30
```

Restart Home Assistant.

### 6. Create Automations

Example Lutron remote automation:

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

## Run the Service

### Development
```bash
python app.py
```

### Production (systemd)

Create `/etc/systemd/system/youtube-thumbs.service`:

```ini
[Unit]
Description=YouTube Thumbs Rating Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/youtube_thumbs
ExecStart=/path/to/youtube_thumbs/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable --now youtube-thumbs
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

## Configuration

Environment variables (`.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 21812 | Service port |
| `RATE_LIMIT_PER_MINUTE` | 10 | Max requests/minute |
| `RATE_LIMIT_PER_HOUR` | 100 | Max requests/hour |
| `RATE_LIMIT_PER_DAY` | 500 | Max requests/day |
| `LOG_FILE` | app.log | General application log file |
| `USER_ACTION_LOG_FILE` | user_actions.log | User action audit log |
| `ERROR_LOG_FILE` | errors.log | Error log file |
| `LOG_LEVEL` | INFO | Logging level |
| `LOG_MAX_SIZE_MB` | 10 | Log rotation size |

## Troubleshooting

**"No media currently playing"**
- Verify AppleTV is playing music
- Check `MEDIA_PLAYER_ENTITY` matches your HA entity

**"Video not found"**
- Ensure YouTube account is signed in on AppleTV
- Song must appear in your YouTube watch history
- Check duration matching (±2 seconds tolerance)

**OAuth Issues**
- Delete `token.pickle` and re-run `python simple_oauth.py`
- Ensure `credentials.json` is present

**Check Logs**
```bash
# General application logs
tail -f app.log

# User actions (thumbs up/down audit trail)
tail -f user_actions.log

# Errors only
tail -f errors.log
```

## Logging

The service uses three separate log files for better organization:

### **user_actions.log** - User Action Audit Trail
Clean, structured log of every thumbs up/down action:
```
[2025-10-25 03:54:00] LIKE | "Song Title" by Artist | ID: xyz123 | SUCCESS
[2025-10-25 03:55:00] DISLIKE | "Another Song" | ID: abc456 | FAILED - Video not found
[2025-10-25 03:56:00] LIKE | "Third Song" by Artist | ID: def789 | ALREADY_RATED
```

### **errors.log** - Error Tracking
All errors with detailed context and stack traces:
```
[2025-10-25 03:54:00] ERROR: Video not found | Context: rate_video (like) | Media: "Song Title" by Artist
[2025-10-25 03:55:00] ERROR: YouTube API HttpError in search_video_globally | Query: 'Song' | Error: ...
```

### **app.log** - General Application Logs
Info, warnings, and debug messages for application flow.

All log files use rotating file handlers (configurable size and backup count).

## File Structure

```
youtube_thumbs/
├── app.py                  # Main Flask app
├── youtube_api.py          # YouTube API with caching
├── homeassistant_api.py    # HA integration with connection pooling
├── matcher.py              # Fuzzy title matching
├── rate_limiter.py         # Memory-efficient rate limiting
├── logger.py               # Multi-logger setup with rotation
├── requirements.txt        # Dependencies
├── .env.example            # Configuration template
└── README.md               # This file
```

## Performance Optimizations

- **Regex caching** - Duration parsing ~10-50x faster
- **Connection pooling** - HTTP requests reuse TCP connections
- **Memory efficient** - Single deque for rate limiting (67% less memory)
- **Type hints** - Full type annotations for better IDE support

## Development Workflow

When making changes to the project, follow this workflow:

### 1. Always Use Virtual Environment
```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Make Your Changes
Edit code, test functionality, etc.

### 3. Test Your Changes
```bash
python app.py
# Test the endpoints
```

### 4. Version and Commit Checklist
Before considering your work complete:

- [ ] Activate venv (`source venv/bin/activate`)
- [ ] Test all changes work as expected
- [ ] Update README.md if needed
- [ ] Bump version number in commit message (v1.0, v1.1, v2.0, etc.)
- [ ] Commit with descriptive message and todo list of what was completed
- [ ] Example commit:
  ```bash
  git add .
  git commit -m "v1.1 - Feature description
  
  - [x] Item 1 completed
  - [x] Item 2 completed
  - [x] Item 3 completed"
  ```

### Version Numbering
- **Major version (v2.0)**: Breaking changes or major features
- **Minor version (v1.1)**: New features, non-breaking changes
- **Patch version (v1.0.1)**: Bug fixes only

## Security

- ⚠️ Never commit `.env`, `credentials.json`, or `token.pickle`
- Service runs on local network only
- OAuth tokens stored locally
- Keep HA token secure

## License

Provided as-is for personal use.
