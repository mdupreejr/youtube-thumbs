#!/usr/bin/with-contenv bashio

# Read configuration from add-on options
HOME_ASSISTANT_URL_CONFIG=$(bashio::config 'home_assistant_url')
HOME_ASSISTANT_TOKEN_CONFIG=$(bashio::config 'home_assistant_token')

# Use defaults if config is empty or "null"
if [ -z "${HOME_ASSISTANT_URL_CONFIG}" ] || [ "${HOME_ASSISTANT_URL_CONFIG}" = "null" ]; then
    export HOME_ASSISTANT_URL="http://supervisor/core"
else
    export HOME_ASSISTANT_URL="${HOME_ASSISTANT_URL_CONFIG}"
fi

if [ -z "${HOME_ASSISTANT_TOKEN_CONFIG}" ] || [ "${HOME_ASSISTANT_TOKEN_CONFIG}" = "null" ]; then
    export HOME_ASSISTANT_TOKEN=""
else
    export HOME_ASSISTANT_TOKEN="${HOME_ASSISTANT_TOKEN_CONFIG}"
fi

export MEDIA_PLAYER_ENTITY=$(bashio::config 'media_player_entity')

# Only export SUPERVISOR_TOKEN if it exists (it's automatically provided by Home Assistant)
# Don't set it to empty string, let it be unset so Python can check for it properly
if [ -n "${SUPERVISOR_TOKEN}" ]; then
    export SUPERVISOR_TOKEN
    bashio::log.info "SUPERVISOR_TOKEN is available for authentication"
fi
export PORT=$(bashio::config 'port')
export HOST=$(bashio::config 'host')
export RATE_LIMIT_PER_MINUTE=$(bashio::config 'rate_limit_per_minute')
export RATE_LIMIT_PER_HOUR=$(bashio::config 'rate_limit_per_hour')
export RATE_LIMIT_PER_DAY=$(bashio::config 'rate_limit_per_day')
export LOG_LEVEL=$(bashio::config 'log_level')

# Check what files exist and where
bashio::log.info "Checking for OAuth credentials..."

# Create the addon_config directory if it doesn't exist
if [ ! -d /config/youtube_thumbs ]; then
    mkdir -p /config/youtube_thumbs
    bashio::log.info "Created directory /config/youtube_thumbs/"
fi

# Try multiple possible locations (prioritize addon_config location)
if [ -f /config/youtube_thumbs/credentials.json ]; then
    bashio::log.info "Found credentials.json in /config/youtube_thumbs/"
    ln -sf /config/youtube_thumbs/credentials.json /app/credentials.json
    bashio::log.info "Created symlink: /app/credentials.json -> /config/youtube_thumbs/credentials.json"
elif [ -f /share/youtube_thumbs/credentials.json ]; then
    bashio::log.info "Found credentials.json in /share/youtube_thumbs/"
    ln -sf /share/youtube_thumbs/credentials.json /app/credentials.json
    bashio::log.info "Created symlink: /app/credentials.json -> /share/youtube_thumbs/credentials.json"
elif [ -f /data/credentials.json ]; then
    bashio::log.info "Found credentials.json in /data/"
    ln -sf /data/credentials.json /app/credentials.json
    bashio::log.info "Created symlink: /app/credentials.json -> /data/credentials.json"
else
    bashio::log.warning "credentials.json NOT found in /config/youtube_thumbs/, /share/youtube_thumbs/, or /data/"
    bashio::log.warning "Please copy credentials.json to /addon_configs/XXXXXXXX_youtube_thumbs/"
    bashio::log.warning "Or via Samba to \\\\homeassistant.local\\addon_configs\\XXXXXXXX_youtube_thumbs\\"
fi

if [ -f /config/youtube_thumbs/token.pickle ]; then
    bashio::log.info "Found token.pickle in /config/youtube_thumbs/"
    ln -sf /config/youtube_thumbs/token.pickle /app/token.pickle
    bashio::log.info "Created symlink: /app/token.pickle -> /config/youtube_thumbs/token.pickle"
elif [ -f /share/youtube_thumbs/token.pickle ]; then
    bashio::log.info "Found token.pickle in /share/youtube_thumbs/"
    ln -sf /share/youtube_thumbs/token.pickle /app/token.pickle
    bashio::log.info "Created symlink: /app/token.pickle -> /share/youtube_thumbs/token.pickle"
elif [ -f /data/token.pickle ]; then
    bashio::log.info "Found token.pickle in /data/"
    ln -sf /data/token.pickle /app/token.pickle
    bashio::log.info "Created symlink: /app/token.pickle -> /data/token.pickle"
else
    bashio::log.warning "token.pickle NOT found in /config/youtube_thumbs/, /share/youtube_thumbs/, or /data/"
    bashio::log.warning "Please copy token.pickle to /addon_configs/XXXXXXXX_youtube_thumbs/"
    bashio::log.warning "Or via Samba to \\\\homeassistant.local\\addon_configs\\XXXXXXXX_youtube_thumbs\\"
fi

bashio::log.info "Starting YouTube Thumbs service on ${HOST}:${PORT}..."
bashio::log.info "Home Assistant URL: ${HOME_ASSISTANT_URL}"
bashio::log.info "Media Player Entity: ${MEDIA_PLAYER_ENTITY}"

# Start the Flask application
cd /app
exec python3 app.py
