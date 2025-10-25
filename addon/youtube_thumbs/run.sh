#!/usr/bin/with-contenv bashio

# Read configuration from add-on options
HOME_ASSISTANT_URL_CONFIG=$(bashio::config 'home_assistant_url')
HOME_ASSISTANT_TOKEN_CONFIG=$(bashio::config 'home_assistant_token')

# Use defaults if config is empty
export HOME_ASSISTANT_URL="${HOME_ASSISTANT_URL_CONFIG:-http://supervisor/core}"
export HOME_ASSISTANT_TOKEN="${HOME_ASSISTANT_TOKEN_CONFIG}"
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
export LOG_MAX_SIZE_MB=$(bashio::config 'log_max_size_mb')

# Set log file paths to /data directory for persistence
export LOG_FILE=/data/app.log
export USER_ACTION_LOG_FILE=/data/user_actions.log
export ERROR_LOG_FILE=/data/errors.log

# Check if credentials.json and token.pickle exist in /data, if not copy from /app
if [ ! -f /data/credentials.json ] && [ -f /app/credentials.json ]; then
    bashio::log.info "Copying credentials.json to /data for persistence..."
    cp /app/credentials.json /data/credentials.json
fi

if [ ! -f /data/token.pickle ] && [ -f /app/token.pickle ]; then
    bashio::log.info "Copying token.pickle to /data for persistence..."
    cp /app/token.pickle /data/token.pickle
fi

# Create symlinks so the app can find the files
if [ -f /data/credentials.json ]; then
    ln -sf /data/credentials.json /app/credentials.json
fi

if [ -f /data/token.pickle ]; then
    ln -sf /data/token.pickle /app/token.pickle
fi

bashio::log.info "Starting YouTube Thumbs service on ${HOST}:${PORT}..."
bashio::log.info "Home Assistant URL: ${HOME_ASSISTANT_URL}"
bashio::log.info "Media Player Entity: ${MEDIA_PLAYER_ENTITY}"

# Start the Flask application
cd /app
exec python3 app.py
