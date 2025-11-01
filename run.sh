#!/usr/bin/with-contenv bashio

bashio::log.info "YouTube Thumbs Rating Add-on Starting..."

# Read configuration from add-on options
bashio::log.info "Loading configuration..."

export HOME_ASSISTANT_URL="${HOME_ASSISTANT_URL:-http://supervisor/core}"
bashio::log.info "Home Assistant URL fixed to ${HOME_ASSISTANT_URL}"

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

PORT_CONFIG=$(bashio::config 'port')
if bashio::var.has_value "${PORT_CONFIG}"; then
    export PORT="${PORT_CONFIG}"
else
    export PORT=21812
fi

# Bind to all interfaces so ingress and direct access work
export HOST="0.0.0.0"
bashio::log.info "API binding to all interfaces (${HOST}:${PORT})"

SQLITE_WEB_HOST_CONFIG=$(bashio::config 'sqlite_web_host')
SQLITE_WEB_HOST_ENV="${SQLITE_WEB_HOST:-}"
if bashio::var.has_value "${SQLITE_WEB_HOST_ENV}"; then
    export SQLITE_WEB_HOST="${SQLITE_WEB_HOST_ENV}"
elif bashio::var.has_value "${SQLITE_WEB_HOST_CONFIG}"; then
    export SQLITE_WEB_HOST="${SQLITE_WEB_HOST_CONFIG}"
else
    export SQLITE_WEB_HOST="127.0.0.1"
fi
bashio::log.info "sqlite_web binding: ${SQLITE_WEB_HOST}"

export RATE_LIMIT_PER_MINUTE=$(bashio::config 'rate_limit_per_minute')
export RATE_LIMIT_PER_HOUR=$(bashio::config 'rate_limit_per_hour')
export RATE_LIMIT_PER_DAY=$(bashio::config 'rate_limit_per_day')
export LOG_LEVEL=$(bashio::config 'log_level')
export ENABLE_HISTORY_TRACKER=$(bashio::config 'history_tracker_enabled')
export HISTORY_POLL_INTERVAL=$(bashio::config 'history_poll_interval')
export PENDING_VIDEO_RETRY_ENABLED=$(bashio::config 'pending_video_retry_enabled')
export PENDING_VIDEO_RETRY_BATCH_SIZE=$(bashio::config 'pending_video_retry_batch_size')

# YouTube search configuration
SEARCH_MAX_RESULTS_CONFIG=$(bashio::config 'search_max_results')
if bashio::var.has_value "${SEARCH_MAX_RESULTS_CONFIG}" && [ "${SEARCH_MAX_RESULTS_CONFIG}" != "null" ]; then
    export YTT_SEARCH_MAX_RESULTS="${SEARCH_MAX_RESULTS_CONFIG}"
fi

SEARCH_MAX_CANDIDATES_CONFIG=$(bashio::config 'search_max_candidates')
if bashio::var.has_value "${SEARCH_MAX_CANDIDATES_CONFIG}" && [ "${SEARCH_MAX_CANDIDATES_CONFIG}" != "null" ]; then
    export YTT_SEARCH_MAX_CANDIDATES="${SEARCH_MAX_CANDIDATES_CONFIG}"
fi

if bashio::config.true 'force_quota_unlock'; then
    export YTT_FORCE_QUOTA_UNLOCK=1
    bashio::log.warning "force_quota_unlock enabled; quota guard state will be cleared on startup"
else
    unset YTT_FORCE_QUOTA_UNLOCK
fi

QUOTA_COOLDOWN_ENV="${YTT_QUOTA_COOLDOWN_SECONDS:-}"
if bashio::var.has_value "${QUOTA_COOLDOWN_ENV}"; then
    export YTT_QUOTA_COOLDOWN_SECONDS="${QUOTA_COOLDOWN_ENV}"
else
    QUOTA_COOLDOWN_CONFIG=$(bashio::config 'quota_cooldown_hours')
    if bashio::var.has_value "${QUOTA_COOLDOWN_CONFIG}" && [ "${QUOTA_COOLDOWN_CONFIG}" != "null" ]; then
        QUOTA_COOLDOWN_SECONDS=$((QUOTA_COOLDOWN_CONFIG * 3600))
    else
        QUOTA_COOLDOWN_SECONDS=43200
    fi
    export YTT_QUOTA_COOLDOWN_SECONDS="${QUOTA_COOLDOWN_SECONDS}"
fi
bashio::log.info "Quota cooldown: ${YTT_QUOTA_COOLDOWN_SECONDS}s"

bashio::log.info "API server binding: ${HOST}:${PORT}"
bashio::log.info "Rate limits: ${RATE_LIMIT_PER_MINUTE}/min, ${RATE_LIMIT_PER_HOUR}/hr, ${RATE_LIMIT_PER_DAY}/day"
bashio::log.info "Log level: ${LOG_LEVEL}"
bashio::log.info "History tracker: enabled=${ENABLE_HISTORY_TRACKER}, interval=${HISTORY_POLL_INTERVAL}s"
bashio::log.info "Pending retry: enabled=${PENDING_VIDEO_RETRY_ENABLED}, batch_size=${PENDING_VIDEO_RETRY_BATCH_SIZE}"

# Check what files exist and where
bashio::log.info "Checking for OAuth credentials in /config/youtube_thumbs (add-on config directory)..."

# Create the addon_config directory if it doesn't exist (also used for logs)
CONFIG_DIR="/config/youtube_thumbs"
mkdir -p "${CONFIG_DIR}"
bashio::log.info "Ensured directory ${CONFIG_DIR} exists"

if [ -f "${CONFIG_DIR}/credentials.json" ]; then
    bashio::log.info "Found credentials.json in ${CONFIG_DIR}"
    ln -sf "${CONFIG_DIR}/credentials.json" /app/credentials.json
    bashio::log.info "Created symlink: /app/credentials.json -> ${CONFIG_DIR}/credentials.json"
else
    bashio::log.warning "credentials.json NOT found in ${CONFIG_DIR}"
    bashio::log.warning "Please copy credentials.json to /addon_configs/XXXXXXXX_youtube_thumbs/ (exposed as ${CONFIG_DIR})"
fi

if [ -f "${CONFIG_DIR}/token.pickle" ]; then
    bashio::log.info "Found token.pickle in ${CONFIG_DIR}"
    ln -sf "${CONFIG_DIR}/token.pickle" /app/token.pickle
    bashio::log.info "Created symlink: /app/token.pickle -> ${CONFIG_DIR}/token.pickle"
else
    bashio::log.warning "token.pickle NOT found in ${CONFIG_DIR}"
    bashio::log.warning "Please copy token.pickle to /addon_configs/XXXXXXXX_youtube_thumbs/ (exposed as ${CONFIG_DIR})"
fi

bashio::log.info "-------------------------------------------"
bashio::log.info "Starting YouTube Thumbs Rating Service"
bashio::log.info "-------------------------------------------"
bashio::log.info "Service endpoint: http://${HOST}:${PORT}"
if [ "${HOST}" = "127.0.0.1" ] || [ "${HOST}" = "localhost" ] || [ "${HOST}" = "::1" ]; then
    bashio::log.info "API is restricted to local calls from Home Assistant/Supervisor."
fi
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

# sqlite_web always uses port 8080 or configured port, NOT the ingress port
# (ingress port is now used by Flask app for bulk rating interface)
if bashio::var.has_value "${SQLITE_WEB_PORT_ENV}"; then
    SQLITE_WEB_PORT="${SQLITE_WEB_PORT_ENV}"
    bashio::log.info "Using custom sqlite_web port from SQLITE_WEB_PORT=${SQLITE_WEB_PORT}"
elif bashio::var.has_value "${SQLITE_WEB_PORT_CONFIG}"; then
    SQLITE_WEB_PORT="${SQLITE_WEB_PORT_CONFIG}"
else
    SQLITE_WEB_PORT=8080
fi

bashio::log.info "sqlite_web will run on port ${SQLITE_WEB_PORT}"
bashio::log.info "Note: Ingress 'Open Web UI' button opens Flask app on port ${PORT}, not sqlite_web"

SQLITE_WEB_LOG="/config/youtube_thumbs/sqlite_web.log"
SQLITE_WEB_PID=""

if command -v sqlite_web >/dev/null 2>&1; then
    bashio::log.info "Starting sqlite_web UI on port ${SQLITE_WEB_PORT}"
    sqlite_web "${DB_PATH}" \
        --no-browser \
        --host "${SQLITE_WEB_HOST}" \
        --port "${SQLITE_WEB_PORT}" \
        >> "${SQLITE_WEB_LOG}" 2>&1 &
    SQLITE_WEB_PID=$!
    bashio::log.info "sqlite_web UI log: ${SQLITE_WEB_LOG}"
    if [ "${SQLITE_WEB_HOST}" = "127.0.0.1" ] || [ "${SQLITE_WEB_HOST}" = "localhost" ] || [ "${SQLITE_WEB_HOST}" = "::1" ]; then
        bashio::log.info "sqlite_web bound to ${SQLITE_WEB_HOST}; use the Home Assistant Web UI button or an SSH tunnel to access it."
    else
        bashio::log.info "Access sqlite_web at http://${SQLITE_WEB_HOST}:${SQLITE_WEB_PORT}"
    fi
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

bashio::log.info "Running startup health checks..."

# Start the Flask application
exec python3 app.py
