#!/usr/bin/with-contenv bashio

bashio::log.info "YouTube Thumbs Rating Add-on Starting..."

# Read configuration from add-on options
bashio::log.info "Loading configuration..."
HOME_ASSISTANT_URL_CONFIG=$(bashio::config 'home_assistant_url')
HOME_ASSISTANT_TOKEN_CONFIG=$(bashio::config 'home_assistant_token')

# Use defaults if config is empty or "null"
if [ -z "${HOME_ASSISTANT_URL_CONFIG}" ] || [ "${HOME_ASSISTANT_URL_CONFIG}" = "null" ]; then
    export HOME_ASSISTANT_URL="http://supervisor/core"
    bashio::log.info "Using default Home Assistant URL: http://supervisor/core"
else
    export HOME_ASSISTANT_URL="${HOME_ASSISTANT_URL_CONFIG}"
    bashio::log.info "Using configured Home Assistant URL: ${HOME_ASSISTANT_URL_CONFIG}"
fi

if [ -z "${HOME_ASSISTANT_TOKEN_CONFIG}" ] || [ "${HOME_ASSISTANT_TOKEN_CONFIG}" = "null" ]; then
    export HOME_ASSISTANT_TOKEN=""
    bashio::log.info "No custom Home Assistant token configured, will use SUPERVISOR_TOKEN"
else
    export HOME_ASSISTANT_TOKEN="${HOME_ASSISTANT_TOKEN_CONFIG}"
    bashio::log.info "Using custom Home Assistant token"
fi

export MEDIA_PLAYER_ENTITY=$(bashio::config 'media_player_entity')
bashio::log.info "Media Player Entity: ${MEDIA_PLAYER_ENTITY}"

# Only export SUPERVISOR_TOKEN if it exists (it's automatically provided by Home Assistant)
# Don't set it to empty string, let it be unset so Python can check for it properly
if [ -n "${SUPERVISOR_TOKEN}" ]; then
    export SUPERVISOR_TOKEN
    bashio::log.info "SUPERVISOR_TOKEN is available for authentication"
else
    bashio::log.warning "SUPERVISOR_TOKEN not available - authentication may fail"
fi

export PORT=$(bashio::config 'port')
export HOST=$(bashio::config 'host')
export RATE_LIMIT_PER_MINUTE=$(bashio::config 'rate_limit_per_minute')
export RATE_LIMIT_PER_HOUR=$(bashio::config 'rate_limit_per_hour')
export RATE_LIMIT_PER_DAY=$(bashio::config 'rate_limit_per_day')
export LOG_LEVEL=$(bashio::config 'log_level')

bashio::log.info "Server configuration: ${HOST}:${PORT}"
bashio::log.info "Rate limits: ${RATE_LIMIT_PER_MINUTE}/min, ${RATE_LIMIT_PER_HOUR}/hr, ${RATE_LIMIT_PER_DAY}/day"
bashio::log.info "Log level: ${LOG_LEVEL}"

# Check what files exist and where
bashio::log.info "Checking for OAuth credentials..."

# Create the addon_config directory if it doesn't exist (also used for logs)
if [ ! -d /config/youtube_thumbs ]; then
    mkdir -p /config/youtube_thumbs
    bashio::log.info "Created directory /config/youtube_thumbs/ for logs and credentials"
else
    bashio::log.info "Directory /config/youtube_thumbs/ already exists"
fi

# Try multiple possible locations (prioritize addon_config location)
if [ -f /config/youtube_thumbs/credentials.json ]; then
    bashio::log.info "Found credentials.json in /config/youtube_thumbs/"
    ln -sf /config/youtube_thumbs/credentials.json /app/credentials.json
    bashio::log.info "Created symlink: /app/credentials.json -> /config/youtube_thumbs/credentials.json"
elif [ -f /data/credentials.json ]; then
    bashio::log.info "Found credentials.json in /data/"
    ln -sf /data/credentials.json /app/credentials.json
    bashio::log.info "Created symlink: /app/credentials.json -> /data/credentials.json"
else
    bashio::log.warning "credentials.json NOT found in /config/youtube_thumbs/ or /data/"
    bashio::log.warning "Please copy credentials.json to /addon_configs/XXXXXXXX_youtube_thumbs/"
    bashio::log.warning "Or via Samba to \\\\homeassistant.local\\addon_configs\\XXXXXXXX_youtube_thumbs\\"
fi

if [ -f /config/youtube_thumbs/token.pickle ]; then
    bashio::log.info "Found token.pickle in /config/youtube_thumbs/"
    ln -sf /config/youtube_thumbs/token.pickle /app/token.pickle
    bashio::log.info "Created symlink: /app/token.pickle -> /config/youtube_thumbs/token.pickle"
elif [ -f /data/token.pickle ]; then
    bashio::log.info "Found token.pickle in /data/"
    ln -sf /data/token.pickle /app/token.pickle
    bashio::log.info "Created symlink: /app/token.pickle -> /data/token.pickle"
else
    bashio::log.warning "token.pickle NOT found in /config/youtube_thumbs/ or /data/"
    bashio::log.warning "Please copy token.pickle to /addon_configs/XXXXXXXX_youtube_thumbs/"
    bashio::log.warning "Or via Samba to \\\\homeassistant.local\\addon_configs\\XXXXXXXX_youtube_thumbs\\"
fi

bashio::log.info "-------------------------------------------"
bashio::log.info "Starting YouTube Thumbs Rating Service"
bashio::log.info "-------------------------------------------"
bashio::log.info "Service endpoint: http://${HOST}:${PORT}"
bashio::log.info "Home Assistant URL: ${HOME_ASSISTANT_URL}"
bashio::log.info "Target media player: ${MEDIA_PLAYER_ENTITY}"
bashio::log.info "Log files location: /config/youtube_thumbs/"
bashio::log.info "-------------------------------------------"

APP_DIR="/app"
cd "${APP_DIR}"

DB_PATH="/config/youtube_thumbs/ratings.db"
export YTT_DB_PATH="${DB_PATH}"

if [ ! -f "${DB_PATH}" ]; then
    bashio::log.info "Initializing SQLite database at ${DB_PATH}"
    python3 - <<'EOF'
from database import get_database
get_database()
EOF
else
    bashio::log.info "Found existing SQLite database at ${DB_PATH}"
fi

SQLITE_WEB_PORT_CONFIG=$(bashio::config 'sqlite_web_port')
SQLITE_WEB_PORT_ENV="${SQLITE_WEB_PORT:-}"

if bashio::var.has_value "${SQLITE_WEB_PORT_ENV}"; then
    SQLITE_WEB_PORT="${SQLITE_WEB_PORT_ENV}"
    bashio::log.info "Using custom sqlite_web port from SQLITE_WEB_PORT=${SQLITE_WEB_PORT}"
elif bashio::var.has_value "${SQLITE_WEB_PORT_CONFIG}"; then
    SQLITE_WEB_PORT="${SQLITE_WEB_PORT_CONFIG}"
else
    SQLITE_WEB_PORT=8080
fi

SQLITE_WEB_LOG="/config/youtube_thumbs/sqlite_web.log"
SQLITE_WEB_PID=""

if command -v sqlite_web >/dev/null 2>&1; then
    bashio::log.info "Starting sqlite_web UI on port ${SQLITE_WEB_PORT}"
    sqlite_web "${DB_PATH}" \
        --no-browser \
        --host "${HOST}" \
        --port "${SQLITE_WEB_PORT}" \
        >> "${SQLITE_WEB_LOG}" 2>&1 &
    SQLITE_WEB_PID=$!
    bashio::log.info "sqlite_web UI log: ${SQLITE_WEB_LOG}"
    bashio::log.info "Access sqlite_web at http://${HOST}:${SQLITE_WEB_PORT}"
else
    bashio::log.warning "sqlite_web not found; database UI will be unavailable"
fi

cleanup() {
    if [ -n "${SQLITE_WEB_PID}" ]; then
        bashio::log.info "Stopping sqlite_web (PID ${SQLITE_WEB_PID})"
        kill "${SQLITE_WEB_PID}" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT

# Start the Flask application
exec python3 app.py
