import atexit
from flask import Flask, jsonify, Response, render_template, request, send_from_directory, url_for
from flask_wtf.csrf import CSRFProtect, CSRFError
from typing import Tuple, Optional, Dict, Any
from pathlib import Path
import os
import re
import time
import traceback
import secrets
import json
import types
from datetime import datetime, timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import safe_join
from logger import logger, user_action_logger, rating_logger
from homeassistant_api import ha_api
from youtube_api import get_youtube_api, set_database as set_youtube_api_database
from database import get_database
from quota_manager import init_quota_manager, get_quota_manager, set_quota_guard_compat
from stats_refresher import StatsRefresher
from startup_checks import run_startup_checks, check_home_assistant_api, check_youtube_api, check_database
from constants import FALSE_VALUES, MAX_BATCH_SIZE, MEDIA_INACTIVITY_TIMEOUT
from helpers.video_helpers import is_youtube_content, get_video_title, get_video_artist
from metrics_tracker import metrics
from helpers.search_helpers import search_and_match_video
from helpers.cache_helpers import find_cached_video
from database_proxy import create_database_proxy_handler
from routes.data_api import bp as data_api_bp, init_data_api_routes
from routes.logs_routes import bp as logs_bp, init_logs_routes
from routes.data_viewer_routes import bp as data_viewer_bp, init_data_viewer_routes
from routes.stats_routes import bp as stats_bp, init_stats_routes
from routes.rating_routes import bp as rating_bp, init_rating_routes
from routes.system_routes import bp as system_bp, init_system_routes
from helpers.pagination_helpers import generate_page_numbers
from helpers.response_helpers import error_response, success_response
from helpers.validation_helpers import validate_page_param, validate_youtube_video_id
from helpers.time_helpers import parse_timestamp, format_duration, format_relative_time

# ============================================================================
# SECURITY HELPER FUNCTIONS
# ============================================================================

def _sanitize_log_value(value: str, max_length: int = 50) -> str:
    """
    Sanitize value for safe logging to prevent log injection.

    Args:
        value: The value to sanitize
        max_length: Maximum length before truncation

    Returns:
        Sanitized string safe for logging
    """
    if not isinstance(value, str):
        value = str(value)
    # Remove newlines to prevent log injection
    value = value.replace('\n', '\\n').replace('\r', '\\r')
    # Truncate long values
    if len(value) > max_length:
        value = value[:max_length] + '...'
    return value



app = Flask(__name__)

# ============================================================================
# FLASK CONFIGURATION
# ============================================================================

# SECURITY: Generate or load persistent secret key for session/CSRF protection
def _get_or_create_secret_key() -> str:
    """Get secret key from env, file, or generate new one."""
    # First priority: environment variable (for explicit configuration)
    env_key = os.environ.get('FLASK_SECRET_KEY')
    if env_key:
        return env_key

    # Second priority: persistent file (survives restarts)
    secret_file = Path('/data/flask_secret.key')
    try:
        if secret_file.exists():
            # Read existing key
            with open(secret_file, 'r') as f:
                return f.read().strip()
        else:
            # Generate new key and persist it
            new_key = secrets.token_hex(32)
            # Save with secure permissions (600 - owner read/write only)
            old_umask = os.umask(0o077)
            try:
                with open(secret_file, 'w') as f:
                    f.write(new_key)
                os.chmod(secret_file, 0o600)
                logger.info("Generated and persisted new Flask secret key")
            finally:
                os.umask(old_umask)
            return new_key
    except Exception as e:
        logger.warning(f"Failed to persist secret key: {e}. Using session-only key.")
        return secrets.token_hex(32)

app.config['SECRET_KEY'] = _get_or_create_secret_key()

# CSRF Configuration
# Disable SSL/referrer checks since we're behind Home Assistant ingress proxy
# The CSRF token check is still enforced and provides sufficient protection
app.config['WTF_CSRF_SSL_STRICT'] = False

# SECURITY: Enable CSRF protection for all POST/PUT/DELETE requests
csrf = CSRFProtect(app)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Handle CSRF validation errors with helpful message."""
    logger.warning(f"CSRF validation failed: {e.description}")
    return jsonify({'error': 'CSRF validation failed', 'message': e.description}), 400

# Configure Flask to work behind Home Assistant ingress proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ============================================================================
# TEMPLATE CONTEXT PROCESSORS
# ============================================================================

@app.context_processor
def inject_static_url():
    """
    Inject static_url function into all templates for ingress-aware static file URLs.
    This ensures static files work correctly through Home Assistant ingress.
    """
    def static_url(filename):
        """Generate static URL with ingress path support."""
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
        base_url = url_for('static', filename=filename)
        if ingress_path:
            return f"{ingress_path}{base_url}"
        return base_url

    return dict(static_url=static_url)

# ============================================================================
# REQUEST/RESPONSE MIDDLEWARE
# ============================================================================

# SECURITY: Headers that should never be logged in full
SENSITIVE_HEADERS = {
    'Authorization', 'Cookie', 'X-API-Key', 'X-Auth-Token',
    'X-CSRFToken', 'X-Session-Token', 'API-Key', 'Bearer'
}

def _sanitize_headers(headers: dict) -> dict:
    """Sanitize sensitive headers before logging."""
    sanitized = {}
    for key, value in headers.items():
        if key in SENSITIVE_HEADERS or key.lower() in {'authorization', 'cookie'}:
            sanitized[key] = '***REDACTED***'
        else:
            sanitized[key] = value
    return sanitized

@app.before_request
def log_request_info():
    """Log all incoming requests with sanitized headers."""
    logger.debug("="*60)
    logger.debug(f"INCOMING REQUEST: {request.method} {request.path}")
    logger.debug(f"  Remote addr: {request.remote_addr}")
    logger.debug(f"  Query string: {request.query_string.decode('utf-8')}")
    logger.debug(f"  Headers: {_sanitize_headers(dict(request.headers))}")
    logger.debug("="*60)

@app.after_request
def log_response_info(response):
    """Log all outgoing responses and add security headers."""
    logger.debug("-"*60)
    logger.debug(f"OUTGOING RESPONSE: {request.method} {request.path}")
    logger.debug(f"  Status: {response.status_code}")
    logger.debug(f"  Content-Type: {response.content_type}")
    if response.content_type and 'json' in response.content_type:
        logger.debug(f"  JSON Body: {response.get_data(as_text=True)[:500]}")  # First 500 chars
    elif response.content_type and 'html' in response.content_type:
        logger.debug(f"  HTML Body (first 200 chars): {response.get_data(as_text=True)[:200]}")
    logger.debug("-"*60)

    # SECURITY: Add security headers to all responses
    # Prevent clickjacking attacks
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'

    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'

    # Enable XSS protection in older browsers
    response.headers['X-XSS-Protection'] = '1; mode=block'

    # Content Security Policy - allow same origin and inline scripts (needed for templates)
    # Restrict to self and allow inline scripts/styles for embedded web UI
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https://i.ytimg.com; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'"
    )

    # Referrer policy - only send referrer for same-origin
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # Permissions policy - disable dangerous features
    response.headers['Permissions-Policy'] = (
        "geolocation=(), "
        "microphone=(), "
        "camera=(), "
        "payment=(), "
        "usb=(), "
        "magnetometer=(), "
        "gyroscope=(), "
        "accelerometer=()"
    )

    return response

# Add error handler to show actual errors
@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all error handler - returns JSON for API routes, HTML for pages."""
    from flask import request

    logger.error(f"Unhandled exception on {request.path}: {e}")
    logger.error(traceback.format_exc())

    # SECURITY: Check if debug mode is enabled (set via environment variable)
    # But forcibly disable in production environments
    debug_requested = os.getenv('DEBUG', 'false').lower() == 'true'

    # Detect production environment indicators
    is_production = (
        os.path.exists('/data/options.json') or  # Home Assistant addon indicator
        os.getenv('HASSIO', 'false').lower() == 'true' or  # Home Assistant supervisor
        os.getenv('PRODUCTION', 'false').lower() == 'true'  # Explicit production flag
    )

    # Force disable debug mode in production
    if is_production and debug_requested:
        logger.warning("SECURITY: DEBUG mode was requested but forcibly disabled in production environment")
        debug_mode = False
    else:
        debug_mode = debug_requested

    # Check if this is an API route - return JSON
    if request.path.startswith('/api/') or request.path.startswith('/test/') or request.path.startswith('/health') or request.path.startswith('/metrics'):
        if debug_mode:
            # SECURITY: Stack trace exposure is acceptable in debug mode only
            # Debug mode should NEVER be enabled in production (check DEBUG env var)
            # Do not expose stack trace; only log it on the server
            return jsonify({
                'success': False,
                'error': str(e),
                'type': type(e).__name__
            }), 500
        else:
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500

    # For regular pages, return HTML
    if debug_mode:
        # SECURITY: Stack trace exposure acceptable in debug mode only
        # Debug mode should NEVER be enabled in production (check DEBUG env var)
        # nosec - debug mode only, controlled by environment variable
        html = f"""
        <html>
        <head><title>Error</title></head>
        <body style="font-family: monospace; padding: 20px; background: #f5f5f5;">
            <h1 style="color: #f44336;">Error: {type(e).__name__}</h1>
            <p><strong>Message:</strong> {str(e)}</p>
            <h2>Traceback:</h2>
            <pre style="background: white; padding: 15px; border: 1px solid #ccc; overflow: auto;">
{traceback.format_exc()}
            </pre>
        </body>
        </html>
        """
        return html, 500
    else:
        # SECURITY: Generic error message in production
        html = """
        <html>
        <head><title>Error</title></head>
        <body style="font-family: sans-serif; padding: 40px; background: #f5f7fa; text-align: center;">
            <h1 style="color: #1e293b;">An error occurred</h1>
            <p style="color: #64748b;">The server encountered an internal error. Please try again later.</p>
            <p style="color: #64748b; font-size: 0.9em; margin-top: 20px;">
                <a href="/" style="color: #2563eb;">Return to Home</a>
            </p>
        </body>
        </html>
        """
        return html, 500

# SECURITY: Add specific error handlers to prevent information disclosure
@app.errorhandler(400)
def bad_request_error(e):
    """Handle 400 Bad Request errors."""
    logger.warning(f"Bad request on {request.path}: {e}")
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Bad request'}), 400
    return "Bad request", 400

@app.errorhandler(403)
def forbidden_error(e):
    """Handle 403 Forbidden errors."""
    logger.warning(f"Forbidden access attempt on {request.path} from {request.remote_addr}")
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403
    return "Forbidden", 403

@app.errorhandler(404)
def not_found_error(e):
    """Handle 404 Not Found errors."""
    logger.debug(f"Not found: {request.path}")
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return "Not found", 404

@app.errorhandler(429)
def rate_limit_error(e):
    """Handle 429 Rate Limit errors."""
    logger.warning(f"Rate limit exceeded on {request.path} from {request.remote_addr}")
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429
    return "Rate limit exceeded", 429

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

try:
    db = get_database()
except Exception as e:
    logger.critical(f"Failed to initialize database: {e}")
    logger.critical(traceback.format_exc())
    logger.critical("Application cannot start without database. Exiting.")
    raise SystemExit(1)

# Inject database into youtube_api module for API usage tracking
set_youtube_api_database(db)

# Initialize and register data API blueprint
init_data_api_routes(db)
app.register_blueprint(data_api_bp)

# SECURITY: CSRF protection now enabled for all endpoints
# Frontend JavaScript sends X-CSRFToken header with fetch() requests
# Flask-WTF automatically checks both form fields and X-CSRFToken header

# Initialize and register logs blueprint
init_logs_routes(db)
app.register_blueprint(logs_bp)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# Wrapper functions for compatibility with quota prober
def _search_wrapper(ha_media: Dict[str, Any]) -> Optional[Dict]:
    """Wrapper for search_helpers.search_and_match_video."""
    yt_api = get_youtube_api()
    return search_and_match_video(ha_media, yt_api, db)


def _cache_wrapper(ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Wrapper for cache_helpers.find_cached_video."""
    return find_cached_video(db, ha_media)


def _pending_retry_enabled() -> bool:
    value = os.getenv('PENDING_VIDEO_RETRY_ENABLED', 'true')
    return value.lower() not in FALSE_VALUES if isinstance(value, str) else True


def _pending_retry_batch_size() -> int:
    raw_size = os.getenv('PENDING_VIDEO_RETRY_BATCH_SIZE', '50')
    try:
        size = int(raw_size)
        return size if 1 <= size <= 500 else 50
    except ValueError:
        logger.warning(
            "Invalid PENDING_VIDEO_RETRY_BATCH_SIZE '%s'; using default 50",
            raw_size,
        )
        return 50


logger.info("Initializing unified quota manager...")
quota_manager = init_quota_manager(
    youtube_api_getter=get_youtube_api,
    db=db,
    search_wrapper=_search_wrapper,
    retry_enabled=_pending_retry_enabled(),
    retry_batch_size=_pending_retry_batch_size(),
    metrics_tracker=metrics,
)
set_quota_guard_compat()  # Set quota_guard variable for backwards compatibility
quota_guard = quota_manager  # Alias for backwards compatibility
quota_prober = quota_manager  # Alias for backwards compatibility (system routes)
logger.info("Starting quota manager background thread...")
quota_manager.start()
atexit.register(quota_manager.stop)
logger.info("Quota manager started successfully")

# Start stats refresher background task (refreshes every hour)
logger.info("Initializing stats refresher...")
stats_refresher = StatsRefresher(db=db, interval_seconds=3600)
logger.info("Starting stats refresher...")
stats_refresher.start()
atexit.register(stats_refresher.stop)
logger.info("Stats refresher started successfully")

# Initialize rating worker for background queue processing (smart sleep intervals)
logger.info("Initializing rating worker...")
from rating_worker import init_rating_worker
rating_worker = init_rating_worker(
    db=db,
    youtube_api_getter=get_youtube_api,
    quota_guard=quota_guard,
    search_wrapper=_search_wrapper,
    poll_interval=60  # Base interval (overridden by smart sleep: 1h/30s/60s)
)
logger.info("Starting rating worker...")
rating_worker.start()
atexit.register(rating_worker.stop)
logger.info("Rating worker started successfully (smart sleep: 1h blocked / 30s processed / 60s empty)")

# ============================================================================
# BLUEPRINT REGISTRATION
# ============================================================================

# Initialize and register data viewer blueprint
init_data_viewer_routes(db)
app.register_blueprint(data_viewer_bp)

# Initialize and register stats blueprint
init_stats_routes(db)
app.register_blueprint(stats_bp)

# Initialize and register rating blueprint
init_rating_routes(
    database=db,
    quota_guard=quota_guard,
    csrf=csrf,
    ha_api=ha_api,
    get_youtube_api_func=get_youtube_api,
    metrics_tracker=metrics,
    is_youtube_content_func=is_youtube_content,
    search_wrapper_func=_search_wrapper,
    cache_wrapper_func=_cache_wrapper
)
app.register_blueprint(rating_bp)

# Apply CSRF exemption to API endpoints for external/programmatic calls
# Legacy endpoints (backward compatibility with Home Assistant automations)
csrf.exempt(app.view_functions['rating.thumbs_up'])
csrf.exempt(app.view_functions['rating.thumbs_down'])
# Bulk rating API endpoints (RESTful API for programmatic access)
csrf.exempt(app.view_functions['rating.rate_song_like'])
csrf.exempt(app.view_functions['rating.rate_song_dislike'])

# Initialize and register system routes blueprint
init_system_routes(
    ha_api=ha_api,
    quota_guard=quota_guard,
    quota_prober=quota_prober,
    get_youtube_api_func=get_youtube_api,
    database=db,
    metrics_tracker=metrics,
    check_home_assistant_api_func=check_home_assistant_api,
    check_youtube_api_func=check_youtube_api,
    check_database_func=check_database
)
app.register_blueprint(system_bp)

# ============================================================================
# STATIC FILE ROUTES
# ============================================================================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """
    Explicitly serve static files to work through Home Assistant ingress.
    Flask's default static serving doesn't respect ingress paths properly.
    """
    try:
        # SECURITY: Prevent path traversal attacks using safe_join and realpath
        static_dir = os.path.join(app.root_path, 'static')

        # Use safe_join to construct path (handles .. and absolute paths)
        safe_path = safe_join(static_dir, filename)
        if not safe_path:
            logger.warning(f"Path traversal attempt blocked: {filename} from {request.remote_addr}")
            return "Invalid filename", 400

        # Verify resolved path is within static directory using realpath
        # This prevents symlink attacks and ensures canonical path verification
        try:
            real_static = os.path.realpath(static_dir)
            real_requested = os.path.realpath(safe_path)

            if not real_requested.startswith(real_static + os.sep):
                logger.warning(f"Path escape attempt blocked: {filename} from {request.remote_addr}")
                return "Invalid path", 400
        except (OSError, ValueError) as e:
            logger.warning(f"Path resolution failed for {filename}: {e}")
            return "Invalid path", 400

        # Verify file exists before serving
        if not os.path.isfile(safe_path):
            logger.error(f"Static file not found: {filename} in {static_dir}")
            return "File not found", 404

        logger.debug(f"Serving static file: {filename} from {static_dir}")
        response = send_from_directory(static_dir, filename)
        # Add cache headers for static files
        response.headers['Cache-Control'] = 'public, max-age=300'  # 5 minutes
        return response
    except FileNotFoundError:
        logger.error(f"Static file not found: {filename} in {static_dir}")
        return "File not found", 404
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {e}")
        logger.error(traceback.format_exc())
        return "Error serving file", 500

# ============================================================================
# PAGE ROUTES
# ============================================================================

@app.route('/')
def index() -> str:
    """
    Server-side rendered main page with connection tests and bulk rating.
    All processing done on server, no client-side JavaScript required.
    """
    try:
        # Get current tab from query parameter (default: tests)
        current_tab = request.args.get('tab', 'tests')
        if current_tab not in ['tests', 'rating']:
            current_tab = 'tests'

        # Get ingress path for proper link generation
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

        # Initialize template data
        template_data = {
            'current_tab': current_tab,
            'ingress_path': ingress_path,
            'ha_test': {'success': False, 'message': 'Not tested'},
            'yt_test': {'success': False, 'message': 'Not tested'},
            'db_test': {'success': False, 'message': 'Not tested'},
            'songs': [],
            'current_page': 1,
            'total_pages': 0,
            'total_unrated': 0
        }

        # Run connection tests if on tests tab
        if current_tab == 'tests':
            # Test Home Assistant
            ha_success, ha_message = check_home_assistant_api(ha_api)
            template_data['ha_test'] = {'success': ha_success, 'message': ha_message}

            # Test YouTube API
            yt_api = get_youtube_api()
            yt_success, yt_message = check_youtube_api(yt_api, quota_guard, db)
            template_data['yt_test'] = {'success': yt_success, 'message': yt_message}

            # Test Database
            db_success, db_message = check_database(db)
            template_data['db_test'] = {'success': db_success, 'message': db_message}

        # Get unrated songs if on rating tab
        elif current_tab == 'rating':
            page, _ = validate_page_param(request.args)
            if not page:  # If validation failed, default to 1
                page = 1

            result = db.get_unrated_videos(page=page, limit=50)

            # Format songs for template
            formatted_songs = []
            for song in result['songs']:
                title = get_video_title(song)
                artist = get_video_artist(song)

                # Format duration if available (prefer yt_duration, fallback to ha_duration)
                duration = song.get('yt_duration') or song.get('ha_duration')
                if duration:
                    duration_str = format_duration(int(duration))
                else:
                    duration_str = ''

                formatted_songs.append({
                    'id': song.get('yt_video_id'),
                    'title': title,
                    'artist': artist,
                    'duration': duration_str
                })

            template_data['songs'] = formatted_songs
            template_data['current_page'] = result['page']
            template_data['total_pages'] = result['total_pages']
            template_data['total_unrated'] = result['total_count']

        return render_template('index_server.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering index page: {e}")
        logger.error(traceback.format_exc())
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading page</h1><p>An internal error occurred. Please try again later.</p>", 500


# Database proxy routes - delegates to database_proxy module
# Allow all HTTP methods (GET, POST, etc.) for sqlite_web functionality like exports
app.add_url_rule('/database', 'database_proxy_root', create_database_proxy_handler(), defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])
app.add_url_rule('/database/<path:path>', 'database_proxy_path', create_database_proxy_handler(), methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])

# ============================================================================
# APPLICATION INITIALIZATION
# ============================================================================

# Initialize YouTube API (runs on both direct execution and WSGI import)
yt_api = None
try:
    yt_api = get_youtube_api()
except Exception as e:
    logger.error(f"Failed to initialize YouTube API: {str(e)}")
    logger.error("Please ensure credentials.json exists and run the OAuth flow")

# Run startup health checks (wrapped in try-except to prevent app crashes)
try:
    run_startup_checks(ha_api, yt_api, db, quota_guard)
except Exception as e:
    logger.error(f"Startup health checks failed: {str(e)}")
    logger.error(traceback.format_exc())
    logger.warning("App starting despite health check failures - some features may not work")

# Clear stats cache on startup to prevent stale data issues
try:
    logger.info("Clearing stats cache...")
    db.invalidate_stats_cache()
except Exception as e:
    logger.error(f"Failed to clear stats cache: {str(e)}")

logger.info("YouTube Thumbs application initialized and ready")

# Only run the development server if executed directly (not via WSGI)
if __name__ == '__main__':
    # nosec B104 - Binding to 0.0.0.0 is intentional for Docker container deployment
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '21812'))

    logger.info(f"Starting Flask development server on {host}:{port}")
    logger.warning("Using Flask development server. For production, use a WSGI server like Gunicorn.")

    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"Flask failed to start: {e}")
        logger.error(traceback.format_exc())
        raise
