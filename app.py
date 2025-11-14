import atexit
from flask import Flask, jsonify, render_template, request, send_from_directory, url_for, g
from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf
from typing import Tuple, Optional, Dict, Any
from pathlib import Path
import os
import traceback
import secrets
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.security import safe_join
from logging_helper import LoggingHelper, LogType

# Get logger instances
logger = LoggingHelper.get_logger(LogType.MAIN)
from homeassistant_api import ha_api
from youtube_api import get_youtube_api, set_database as set_youtube_api_database
from database import get_database
from stats_refresher import StatsRefresher
from song_tracker import SongTracker
from startup_checks import run_startup_checks, check_home_assistant_api, check_youtube_api, check_database
from constants import FALSE_VALUES
from helpers.video_helpers import is_youtube_content, get_video_title, get_video_artist
from metrics_tracker import metrics
from helpers.search_helpers import search_and_match_video
from helpers.cache_helpers import find_cached_video
from database_proxy import create_sqlite_web_middleware
from routes.data_api import bp as data_api_bp, init_data_api_routes
from routes.logs_routes import bp as logs_bp, init_logs_routes
from routes.data_viewer_routes import bp as data_viewer_bp, init_data_viewer_routes
from routes.stats_routes import bp as stats_bp, init_stats_routes
from routes.rating_routes import bp as rating_bp, init_rating_routes
from routes.system_routes import bp as system_bp, init_system_routes
from helpers.validation_helpers import validate_page_param, validate_youtube_video_id
from helpers.time_helpers import format_duration
from helpers.constants.empty_states import EMPTY_STATE_ALL_RATED

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

# Note: ProxyFix middleware is applied after sqlite_web mounting (see DATABASE INITIALIZATION section)

# ============================================================================
# TEMPLATE CONTEXT PROCESSORS
# ============================================================================

@app.context_processor
def inject_static_url():
    """
    Inject static_url function and ingress_path into all templates.
    This ensures static files and all links work correctly through Home Assistant ingress.
    """
    def static_url(filename):
        """Generate static URL with ingress path support and cache-busting."""
        ingress_path = g.ingress_path
        base_url = url_for('static', filename=filename)

        # Add version parameter for cache-busting to prevent browser caching issues
        # This ensures CSS/JS updates are immediately visible without hard refresh
        import json
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                version = config.get('version', '1.0.0')
        except:
            version = '1.0.0'

        # Append version as query parameter
        cache_buster = f"?v={version}"

        if ingress_path:
            return f"{ingress_path}{base_url}{cache_buster}"
        return f"{base_url}{cache_buster}"

    # Inject both static_url function and ingress_path variable
    return dict(static_url=static_url, ingress_path=g.ingress_path)

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

@app.before_request
def inject_ingress_path():
    """
    Inject ingress_path into Flask's g object for all requests.
    This centralizes the ingress path retrieval and eliminates duplication across routes.
    """
    g.ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

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

    # Cache control - prevent CDN/browser caching issues
    # Static files with ?v= parameter can be cached long-term (version in URL)
    # Everything else should not be cached to ensure fresh content
    if request.path.startswith('/static/'):
        if 'v' in request.args:
            # Versioned static files - cache for 1 year (URL changes with version)
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            # Non-versioned static files - no cache
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
    else:
        # HTML pages and API responses - no cache
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    return response

# Add error handler to show actual errors
@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all error handler - returns JSON for API routes, HTML for pages."""
    from flask import request

    LoggingHelper.log_error_with_trace(f"Unhandled exception on {request.path}", e)

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
    LoggingHelper.log_error_with_trace("CRITICAL: Failed to initialize database", e)
    logger.critical("Application cannot start without database. Exiting.")
    raise SystemExit(1)

# Inject database into youtube_api module for API usage tracking
set_youtube_api_database(db)

# ============================================================================
# SQLITE_WEB INTEGRATION
# ============================================================================

# Track if sqlite_web was successfully mounted
sqlite_web_available = False

# Mount sqlite_web directly into Flask using DispatcherMiddleware
# This replaces the HTTP proxy approach for better performance
try:
    db_path = os.environ.get('YTT_DB_PATH', '/config/youtube_thumbs/ratings.db')
    sqlite_web_wsgi = create_sqlite_web_middleware(db_path)

    # Mount sqlite_web at /database using DispatcherMiddleware
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
        '/database': sqlite_web_wsgi
    })
    sqlite_web_available = True
    logger.info("sqlite_web mounted at /database (direct WSGI integration)")
except Exception as e:
    logger.warning(f"Failed to mount sqlite_web: {e}")
    logger.warning("Database admin interface will not be available")
    sqlite_web_available = False

# Configure Flask to work behind Home Assistant ingress proxy
# IMPORTANT: ProxyFix must be applied AFTER DispatcherMiddleware
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ============================================================================
# BLUEPRINT REGISTRATION
# ============================================================================

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


# Start stats refresher background task (refreshes every hour)
stats_refresher = StatsRefresher(db=db, interval_seconds=3600)
stats_refresher.start()
atexit.register(stats_refresher.stop)
LoggingHelper.log_operation("stats refresher", "started")

# Start song tracker background task (polls HA every 30 seconds)
song_tracking_enabled = os.environ.get('SONG_TRACKING_ENABLED', 'true').lower() not in FALSE_VALUES
song_tracking_interval = int(os.environ.get('SONG_TRACKING_POLL_INTERVAL', '30'))

if song_tracking_enabled:
    song_tracker = SongTracker(ha_api=ha_api, db=db, poll_interval=song_tracking_interval)
    song_tracker.start()
    atexit.register(song_tracker.stop)
    LoggingHelper.log_operation(f"song tracker (poll interval: {song_tracking_interval}s)", "started")
else:
    logger.info("Song tracker disabled (song_tracking_enabled=false)")

# NOTE: Queue worker runs as a separate process (queue_worker.py), not a thread
# This eliminates threading complexity and ensures only ONE worker processes the queue
logger.debug("Queue worker runs as separate background process (started by run.sh)")

# ============================================================================
# BLUEPRINT REGISTRATION
# ============================================================================

# Initialize and register data viewer blueprint
init_data_viewer_routes(db, sqlite_web_available)
app.register_blueprint(data_viewer_bp)

# Initialize and register stats blueprint
init_stats_routes(db)
app.register_blueprint(stats_bp)

# Initialize and register rating blueprint
init_rating_routes(
    database=db,
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
    except Exception as e:
        LoggingHelper.log_error_with_trace(f"Error serving static file {filename}", e)
        return "Error serving file", 500

# ============================================================================
# PAGE ROUTES
# ============================================================================

@app.route('/')
def index() -> str:
    """
    Server-side rendered main page with connection tests and bulk rating.
    All processing done on server, no client-side JavaScript required.
    Now uses unified table_viewer.html for bulk rating tab.
    """
    try:
        # Get current tab from query parameter (default: tests)
        current_tab = request.args.get('tab', 'tests')
        if current_tab not in ['tests', 'rating']:
            current_tab = 'tests'

        # Get ingress path for proper link generation
        ingress_path = g.ingress_path

        # Handle tests tab with old template
        if current_tab == 'tests':
            # Refresh all checks on every Tests tab load (all are cheap operations)
            # HA API is local so we can hit it as much as needed
            ha_success, ha_data = check_home_assistant_api(ha_api)
            fresh_ha_test = {'success': ha_success, **ha_data}

            # check_youtube_api() doesn't make API calls (just reads DB stats for quota)
            yt_success, yt_data = check_youtube_api(yt_api, db)
            fresh_yt_test = {'success': yt_success, **yt_data}

            # DB check is also cheap (just counts)
            db_success, db_data = check_database(db)
            fresh_db_test = {'success': db_success, **db_data}

            template_data = {
                'current_tab': current_tab,
                'ingress_path': ingress_path,
                'ha_test': fresh_ha_test,  # Fresh HA status (local, can refresh often)
                'yt_test': fresh_yt_test,  # Fresh YouTube stats with live quota usage
                'db_test': fresh_db_test,  # Fresh DB stats
                'songs': [],
                'current_page': 1,
                'total_pages': 0,
                'total_unrated': 0
            }

            try:
                template_data['metrics'] = {
                    'cache_stats': metrics.get_cache_stats(),
                    'api_stats': metrics.get_api_stats(),
                    'rating_stats': metrics.get_rating_stats(),
                    'search_stats': metrics.get_search_stats(),
                    'retry_stats': metrics.get_retry_stats(),
                    'system_stats': metrics.get_system_stats()
                }
            except Exception as e:
                logger.warning(f"Failed to gather metrics for tests page: {e}")
                template_data['metrics'] = None

            return render_template('index_server.html', **template_data)

        # Handle rating tab with table_viewer.html
        else:  # current_tab == 'rating'
            page, _ = validate_page_param(request.args)
            if not page:
                page = 1

            result = db.get_unrated_videos(page=page, limit=50)

            # Create page configuration
            from helpers.template import PageConfig, TableData, TableColumn, TableRow, TableCell
            from helpers.pagination_helpers import generate_page_numbers

            page_config = PageConfig(
                title='Bulk Rating',
                nav_active='rating',
                storage_key='bulk-rating',
                show_title=False  # Don't show title, already in navbar
            )

            # No need for main_tabs - they're already in the main navbar

            # Set empty state
            page_config.set_empty_state(**EMPTY_STATE_ALL_RATED)

            # Create table columns
            columns = [
                TableColumn('title', 'Song Title', width='30%'),
                TableColumn('artist', 'Artist', width='25%'),
                TableColumn('duration', 'Duration', width='10%'),
                TableColumn('actions', 'Actions', width='35%')
            ]

            # Create table rows with action buttons
            rows = []
            for song in result['songs']:
                title = get_video_title(song)
                artist = get_video_artist(song)

                # Format duration
                duration = song.get('yt_duration') or song.get('ha_duration')
                duration_str = format_duration(int(duration)) if duration else '—'

                # Create action buttons HTML with form
                csrf_token_value = generate_csrf()
                actions_html = f'''
                    <form method="POST" action="{ingress_path}/rate-song" style="display: inline-flex; gap: 5px;">
                        <input type="hidden" name="csrf_token" value="{csrf_token_value}">
                        <input type="hidden" name="song_id" value="{song.get('yt_video_id')}">
                        <input type="hidden" name="page" value="{page}">
                        <button type="submit" name="rating" value="like" class="btn-like" style="padding: 5px 12px; cursor: pointer; border: 1px solid #10b981; background: #10b981; color: white; border-radius: 4px; font-size: 14px;">👍 Like</button>
                        <button type="submit" name="rating" value="dislike" class="btn-dislike" style="padding: 5px 12px; cursor: pointer; border: 1px solid #ef4444; background: #ef4444; color: white; border-radius: 4px; font-size: 14px;">👎 Dislike</button>
                        <button type="submit" name="rating" value="skip" class="btn-skip" style="padding: 5px 12px; cursor: pointer; border: 1px solid #6b7280; background: #6b7280; color: white; border-radius: 4px; font-size: 14px;">⏭️ Skip</button>
                    </form>
                '''

                cells = [
                    TableCell(title),
                    TableCell(artist or '—'),
                    TableCell(duration_str),
                    TableCell('actions', actions_html)
                ]
                rows.append(TableRow(cells))

            table_data = TableData(columns, rows)

            # Build pagination
            total_pages = result['total_pages']
            page_numbers = generate_page_numbers(page, total_pages)
            pagination = {
                'current_page': page,
                'total_pages': total_pages,
                'page_numbers': page_numbers,
                'prev_url': f'/?tab=rating&page={page-1}' if page > 1 else None,
                'next_url': f'/?tab=rating&page={page+1}' if page < total_pages else None,
                'page_url_template': '/?tab=rating&page=PAGE_NUM'
            }

            status_message = f"{result['total_count']} unrated songs • Page {page} of {total_pages}"

            return render_template(
                'table_viewer.html',
                ingress_path=ingress_path,
                page_config=page_config.to_dict(),
                table_data=table_data.to_dict() if table_data and table_data.rows else None,
                pagination=pagination,
                status_message=status_message
            )

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering index page", e)
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading page</h1><p>An internal error occurred. Please try again later.</p>", 500


# Note: Database viewer routes (/database) are now handled by DispatcherMiddleware
# See SQLITE_WEB INTEGRATION section for direct WSGI mounting

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

# Run startup health checks and cache results (wrapped in try-except to prevent app crashes)
# v4.0.23: Cache results to avoid re-running checks on every page load
_cached_health_checks = {
    'ha_test': {'success': False, 'message': 'Not tested', 'details': {}},
    'yt_test': {'success': False, 'message': 'Not tested', 'details': {}},
    'db_test': {'success': False, 'message': 'Not tested'}
}

try:
    # v4.0.35: run_startup_checks now returns check results to avoid duplicate API calls
    all_ok, check_results = run_startup_checks(ha_api, yt_api, db)

    # Cache the results for display in webui (avoid re-running on every page load)
    ha_success, ha_data = check_results['ha']
    _cached_health_checks['ha_test'] = {'success': ha_success, **ha_data}

    yt_success, yt_data = check_results['yt']
    _cached_health_checks['yt_test'] = {'success': yt_success, **yt_data}

    db_success, db_message = check_results['db']
    _cached_health_checks['db_test'] = {'success': db_success, 'message': db_message}

except Exception as e:
    LoggingHelper.log_error_with_trace("Startup health checks failed", e)
    logger.warning("App starting despite health check failures - some features may not work")

# v4.0.22: Removed redundant cache clear - stats refresher already does initial refresh
# The stats refresher populates the cache immediately on startup (line 385)
# Clearing it here would just empty what we just populated

logger.info("YouTube Thumbs application initialized and ready")

# Only run the development server if executed directly (not via WSGI)
if __name__ == '__main__':
    # Bind to localhost by default for security (only accessible via localhost or ingress proxy)
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '21812'))

    # Security warning if binding to all interfaces
    if host == '0.0.0.0':
        logger.warning("Binding to 0.0.0.0 exposes API to network. Use 127.0.0.1 for production security.")

    logger.info(f"Starting Flask development server on {host}:{port}")
    logger.warning("Using Flask development server. For production, use a WSGI server like Gunicorn.")

    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except Exception as e:
        LoggingHelper.log_error_with_trace("Flask failed to start", e)
        raise
