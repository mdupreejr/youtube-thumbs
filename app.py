import atexit
from flask import Flask, jsonify, Response, render_template, request, send_from_directory
from flask_wtf.csrf import CSRFProtect
from typing import Tuple, Optional, Dict, Any
import os
import re
import time
import traceback
import secrets
import json
from datetime import datetime, timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import safe_join
from logger import logger, user_action_logger, rating_logger
from rate_limiter import rate_limiter
from homeassistant_api import ha_api
from youtube_api import get_youtube_api, set_database as set_youtube_api_database
from database import get_database
from history_tracker import HistoryTracker
from quota_guard import quota_guard
from quota_prober import QuotaProber
from stats_refresher import StatsRefresher
from startup_checks import run_startup_checks, check_home_assistant_api, check_youtube_api, check_database
from constants import FALSE_VALUES, MAX_BATCH_SIZE, MEDIA_INACTIVITY_TIMEOUT
from video_helpers import is_youtube_content, get_video_title, get_video_artist
from metrics_tracker import metrics
from search_helpers import search_and_match_video
from cache_helpers import find_cached_video
from database_proxy import create_database_proxy_handler
from routes.data_api import bp as data_api_bp, init_data_api_routes
from routes.logs_routes import bp as logs_bp, init_logs_routes
from helpers.pagination_helpers import generate_page_numbers
from helpers.response_helpers import error_response, success_response
from helpers.validation_helpers import validate_page_param, validate_youtube_video_id
from helpers.time_helpers import parse_timestamp, format_duration, format_relative_time

# ============================================================================
# DATA VIEWER CONSTANTS
# ============================================================================

# All available columns for data viewer with friendly display names
DATA_VIEWER_COLUMNS = {
    'yt_video_id': 'Video ID',
    'ha_title': 'Title (HA)',
    'ha_artist': 'Artist (HA)',
    'ha_app_name': 'App Name',
    'yt_title': 'Title (YT)',
    'yt_channel': 'Channel',
    'yt_url': 'YouTube URL',
    'rating': 'Rating',
    'play_count': 'Play Count',
    'date_added': 'Date Added',
    'date_last_played': 'Last Played',
    'rating_score': 'Rating Score',
    'source': 'Source',
    'yt_match_pending': 'Pending',
    'yt_match_attempts': 'Match Attempts',
    'ha_duration': 'Duration (HA)',
    'yt_duration': 'Duration (YT)',
    'yt_published_at': 'Published',
    'yt_category_id': 'Category',
    'pending_reason': 'Pending Reason'
}

# Default columns to display if none selected
DEFAULT_DATA_VIEWER_COLUMNS = [
    'yt_video_id', 'ha_title', 'ha_artist',
    'rating', 'play_count', 'date_last_played'
]

# Data viewer pagination and validation constants
MAX_PAGE_NUMBER = 1_000_000  # Prevent excessive memory usage
DEFAULT_PAGE_SIZE = 50


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

def require_rate_limit(f):
    """
    SECURITY: Decorator to apply rate limiting to API endpoints.
    Returns 429 Too Many Requests if rate limit is exceeded.
    """
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        allowed, reason = rate_limiter.check_and_add_request()
        if not allowed:
            logger.warning(f"Rate limit exceeded for {request.remote_addr} on {request.path}")
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': reason}), 429
            return reason, 429
        return f(*args, **kwargs)
    return decorated_function


app = Flask(__name__)

# ============================================================================
# FLASK CONFIGURATION
# ============================================================================

# SECURITY: Generate secret key for session/CSRF protection
# In production, this should be set via environment variable
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))

# CSRF Configuration
# Disable SSL/referrer checks since we're behind Home Assistant ingress proxy
# The CSRF token check is still enforced and provides sufficient protection
app.config['WTF_CSRF_SSL_STRICT'] = False

# SECURITY: Enable CSRF protection for all POST/PUT/DELETE requests
csrf = CSRFProtect(app)

# Configure Flask to work behind Home Assistant ingress proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ============================================================================
# REQUEST/RESPONSE MIDDLEWARE
# ============================================================================
@app.before_request
def log_request_info():
    """Log all incoming requests."""
    logger.debug("="*60)
    logger.debug(f"INCOMING REQUEST: {request.method} {request.path}")
    logger.debug(f"  Remote addr: {request.remote_addr}")
    logger.debug(f"  Query string: {request.query_string.decode('utf-8')}")
    logger.debug(f"  Headers: {dict(request.headers)}")
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

    # Check if debug mode is enabled (set via environment variable)
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'

    # Check if this is an API route - return JSON
    if request.path.startswith('/api/') or request.path.startswith('/test/') or request.path.startswith('/health') or request.path.startswith('/metrics'):
        if debug_mode:
            # SECURITY: Stack trace exposure is acceptable in debug mode only
            # Debug mode should NEVER be enabled in production (check DEBUG env var)
            return jsonify({
                'success': False,
                'error': str(e),
                'type': type(e).__name__,
                'traceback': traceback.format_exc()  # nosec - debug mode only
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
init_data_api_routes(db, csrf)
app.register_blueprint(data_api_bp)

# Initialize and register logs blueprint
init_logs_routes(db)
app.register_blueprint(logs_bp)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_media_info(title: str, artist: str) -> str:
    """Format media information for logging."""
    return f'"{title}" by {artist}' if artist else f'"{title}"'

def _queue_rating_request(
    yt_video_id: str,
    rating_type: str,
    media_info: str,
    reason: str,
    record_attempt: bool = False,
) -> Tuple[Response, int]:
    db.enqueue_rating(yt_video_id, rating_type)
    if record_attempt:
        db.mark_pending_rating(yt_video_id, False, reason)
    db.record_rating_local(yt_video_id, rating_type)
    metrics.record_rating(success=False, queued=True)
    user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {yt_video_id} | QUEUED - {reason}")
    rating_logger.info(f"{rating_type.upper()} | QUEUED | {media_info} | ID: {yt_video_id} | Reason: {reason}")
    return (
        jsonify(
            {
                "success": True,
                "message": f"Queued {rating_type} request; will sync when YouTube API is available ({reason}).",
                "video_id": yt_video_id,
                "queued": True,
            }
        ),
        202,
    )

def _sync_pending_ratings(yt_api: Any, batch_size: int = 20) -> None:
    """
    Sync pending ratings using batch operations for efficiency.
    Processes up to batch_size pending ratings, using batch API calls where possible.
    """
    # Validate batch size (YouTube API supports max 50 IDs per videos.list call)
    batch_size = max(1, min(batch_size, MAX_BATCH_SIZE))

    should_skip, _ = quota_guard.check_quota_or_skip("sync pending ratings")
    if should_skip:
        return

    # Get more pending ratings to process in batch
    pending_jobs = db.list_pending_ratings(limit=batch_size)
    if not pending_jobs:
        return

    # Prepare batch ratings
    ratings_to_process = []
    for job in pending_jobs:
        should_skip, _ = quota_guard.check_quota_or_skip("batch rating processing")
        if should_skip:
            break
        ratings_to_process.append((job['yt_video_id'], job['rating']))

    if not ratings_to_process:
        return

    # Use batch operations if we have multiple ratings
    if len(ratings_to_process) > 1:
        logger.info(f"Processing batch of {len(ratings_to_process)} pending ratings")

        # Batch process the ratings
        results = yt_api.batch_set_ratings(ratings_to_process)

        # Update database based on results
        for video_id, rating in ratings_to_process:
            success = results.get(video_id, False)
            if success:
                db.record_rating(video_id, rating)
                db.mark_pending_rating(video_id, True)
                metrics.record_rating(success=True, queued=False)
                rating_logger.info(f"{rating.upper()} | SYNCED | queued video {video_id}")
            else:
                db.mark_pending_rating(video_id, False, "Batch rating failed")
                metrics.record_rating(success=False, queued=False)
                logger.warning(f"Failed to sync rating for {video_id}")
    else:
        # Single rating, use regular method
        video_id, rating = ratings_to_process[0]
        media_info = f"queued video {video_id}"
        try:
            if yt_api.set_video_rating(video_id, rating):
                db.record_rating(video_id, rating)
                db.mark_pending_rating(video_id, True)
                rating_logger.info(f"{rating.upper()} | SYNCED | {media_info}")
            else:
                db.mark_pending_rating(video_id, False, "YouTube API returned False")
        except Exception as exc:  # pragma: no cover - defensive
            db.mark_pending_rating(video_id, False, str(exc))
            logger.error("Failed to sync pending rating for %s: %s", video_id, exc)

# Wrapper functions for compatibility with HistoryTracker dependency injection
# These could be refactored to pass the actual modules instead
def _search_wrapper(ha_media: Dict[str, Any]) -> Optional[Dict]:
    """Wrapper for search_helpers.search_and_match_video."""
    yt_api = get_youtube_api()
    return search_and_match_video(ha_media, yt_api, db)


def _cache_wrapper(ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Wrapper for cache_helpers.find_cached_video."""
    return find_cached_video(db, ha_media)


def _history_tracker_enabled() -> bool:
    value = os.getenv('ENABLE_HISTORY_TRACKER', 'true')
    return value.lower() not in FALSE_VALUES if isinstance(value, str) else True


def _history_poll_interval() -> int:
    raw_interval = os.getenv('HISTORY_POLL_INTERVAL', '60')
    try:
        interval = int(raw_interval)
        return interval if interval > 0 else 60
    except ValueError:
        logger.warning(
            "Invalid HISTORY_POLL_INTERVAL '%s'; using default 60 seconds",
            raw_interval,
        )
        return 60


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


logger.info("Initializing history tracker...")
history_tracker = HistoryTracker(
    ha_api=ha_api,
    database=db,
    find_cached_video=_cache_wrapper,
    search_and_match_video=_search_wrapper,
    poll_interval=_history_poll_interval(),
    enabled=_history_tracker_enabled(),
)
logger.info("Starting history tracker...")
history_tracker.start()
atexit.register(history_tracker.stop)
logger.info("History tracker started successfully")


def _probe_youtube_api() -> bool:
    """
    Lightweight probe to test if YouTube API is accessible.
    Makes a minimal search query to check quota status.

    Returns:
        True if API is accessible, False if quota exceeded
    """
    try:
        logger.debug("Probing YouTube API with lightweight test query...")
        # Search for a well-known video with a simple query
        # This should be cheap on quota (just 1 search unit)
        result = yt_api.search_video_globally("test", expected_duration=10)

        # If we get any result (even None), it means no quota error
        # Quota errors would raise an exception
        logger.debug("YouTube API probe successful - quota appears available")
        return True
    except Exception as exc:
        # Check if it's a quota error
        error_str = str(exc).lower()
        if 'quota' in error_str or '403' in error_str:
            logger.debug("YouTube API probe failed - quota still exceeded: %s", exc)
            return False
        # Other errors might be transient, return True to clear cooldown
        logger.warning("YouTube API probe failed with unexpected error: %s", exc)
        return False


logger.info("Initializing quota prober...")
quota_prober = QuotaProber(
    quota_guard=quota_guard,
    probe_func=_probe_youtube_api,
    check_interval=300,  # Check every 5 minutes if probe is needed
    enabled=True,
    db=db,
    search_wrapper=_search_wrapper,
    retry_enabled=_pending_retry_enabled(),
    retry_batch_size=_pending_retry_batch_size(),
    metrics_tracker=metrics,
)
logger.info("Starting quota prober...")
quota_prober.start()
atexit.register(quota_prober.stop)
logger.info("Quota prober started successfully")

# Start stats refresher background task (refreshes every hour)
logger.info("Initializing stats refresher...")
stats_refresher = StatsRefresher(db=db, interval_seconds=3600)
logger.info("Starting stats refresher...")
stats_refresher.start()
atexit.register(stats_refresher.stop)
logger.info("Stats refresher started successfully")


def rate_video(rating_type: str) -> Tuple[Response, int]:
    """
    Refactored handler for rating videos with improved organization.
    Delegates to helper functions for better maintainability.
    """
    from rating_helpers import (
        check_rate_limit,
        validate_current_media,
        check_youtube_content,
        find_or_search_video,
        update_database_for_rating,
        check_already_rated,
        handle_quota_blocked_rating,
        execute_rating
    )

    logger.info(f"{rating_type} request received")

    # Step 1: Check rate limiting
    rate_limit_response = check_rate_limit(rate_limiter, rating_type)
    if rate_limit_response:
        return rate_limit_response

    try:
        # Step 2: Get and validate current media
        ha_media, error_response = validate_current_media(ha_api, rating_type)
        if error_response:
            return error_response

        # Step 3: Check if it's YouTube content
        youtube_check_response = check_youtube_content(ha_media, rating_type, is_youtube_content)
        if youtube_check_response:
            return youtube_check_response

        # Step 4: Find or search for video
        video, error_response = find_or_search_video(
            ha_media,
            _cache_wrapper,
            _search_wrapper,
            rating_type,
            format_media_info
        )
        if error_response:
            return error_response

        # Step 5: Update database
        yt_video_id = update_database_for_rating(db, video, ha_media)
        video_title = video['title']
        artist = ha_media.get('artist', '')
        media_info = format_media_info(video_title, artist)

        # Step 6: Check if already rated
        already_rated_response = check_already_rated(db, yt_video_id, rating_type, media_info, video_title)
        if already_rated_response:
            return already_rated_response

        # Step 7: Handle quota blocking
        quota_blocked_response = handle_quota_blocked_rating(
            yt_video_id,
            rating_type,
            media_info,
            _queue_rating_request
        )
        if quota_blocked_response:
            return quota_blocked_response

        # Step 8: Sync pending ratings and execute rating
        yt_api = get_youtube_api()
        _sync_pending_ratings(yt_api)

        return execute_rating(
            yt_api,
            yt_video_id,
            rating_type,
            media_info,
            video_title,
            db,
            _queue_rating_request
        )

    except Exception as e:
        logger.error(f"Unexpected error in {rating_type} endpoint: {str(e)}")
        logger.debug(f"Traceback for {rating_type} error: {traceback.format_exc()}")
        rating_logger.info(f"{rating_type.upper()} | FAILED | Unexpected error: {str(e)}")
        return error_response("An unexpected error occurred while rating the video", 500)

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

@app.route('/rate-song', methods=['POST'])
@require_rate_limit
def rate_song_form() -> Response:
    """
    Handle bulk rating form submissions from server-side rendered page.
    Processes the rating and redirects back to the rating tab.
    """
    from flask import redirect
    try:
        # Get ingress path for proper redirect
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

        song_id = request.form.get('song_id')
        rating = request.form.get('rating')
        page = request.form.get('page', '1')

        if not song_id or not rating:
            logger.error("Missing song_id or rating in form submission")
            return redirect(f"{ingress_path}/?tab=rating&page={page}")

        # SECURITY: Validate video ID format
        is_valid, _ = validate_youtube_video_id(song_id)
        if not is_valid:
            logger.warning(f"Invalid video ID format: {song_id} from {request.remote_addr}")
            return redirect(f"{ingress_path}/?tab=rating&page={page}")

        if rating not in ['like', 'dislike', 'skip']:
            logger.error(f"Invalid rating value: {rating}")
            return redirect(f"{ingress_path}/?tab=rating&page={page}")

        # Skip ratings don't actually rate, just move to next
        if rating != 'skip':
            # Use existing rate_song_direct function
            response = rate_song_direct(song_id, rating)
            # Check if rating was successful (response is tuple of (Response, status_code))
            if isinstance(response, tuple):
                response_obj, status_code = response
            else:
                response_obj = response
                status_code = 200

            if status_code != 200:
                logger.warning(f"Rating failed for {song_id}: status {status_code}")

        # Redirect back to rating tab with same page
        return redirect(f"{ingress_path}/?tab=rating&page={page}")

    except Exception as e:
        logger.error(f"Error processing rating form: {e}")
        logger.error(traceback.format_exc())
        # Redirect back even on error
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
        page = request.form.get('page', '1')
        return redirect(f"{ingress_path}/?tab=rating&page={page}")

# ============================================================================
# TEST ROUTES (System Connectivity Tests)
# ============================================================================

@app.route('/test/youtube')
def test_youtube() -> Response:
    """Test YouTube API connectivity and quota status."""
    logger.debug("=== /test/youtube endpoint called ===")
    try:
        yt_api = get_youtube_api()
        success, message = check_youtube_api(yt_api, quota_guard)
        logger.debug(f"YouTube test result: success={success}, message={message}")
        response = jsonify({"success": success, "message": message})
        logger.debug(f"Returning JSON response: {response.get_json()}")
        return response
    except Exception as e:
        logger.error(f"=== ERROR in /test/youtube endpoint ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": "Error testing YouTube API connection"})

@app.route('/test/ha')
def test_ha() -> Response:
    """Test Home Assistant API connectivity."""
    logger.debug("=== /test/ha endpoint called ===")
    try:
        success, message = check_home_assistant_api(ha_api)
        logger.debug(f"HA test result: success={success}, message={message}")
        response = jsonify({"success": success, "message": message})
        logger.debug(f"Returning JSON response: {response.get_json()}")
        return response
    except Exception as e:
        logger.error(f"=== ERROR in /test/ha endpoint ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": "Error testing Home Assistant connection"})

@app.route('/test/db')
def test_db() -> Response:
    """Test database connectivity and integrity."""
    logger.debug("=== /test/db endpoint called ===")
    try:
        success, message = check_database(db)
        logger.debug(f"DB test result: success={success}, message={message}")
        response = jsonify({"success": success, "message": message})
        logger.debug(f"Returning JSON response: {response.get_json()}")
        return response
    except Exception as e:
        logger.error(f"=== ERROR in /test/db endpoint ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": "Error testing database connection"})

# ============================================================================
# API ROUTES (Bulk Rating Interface)
# ============================================================================

@app.route('/api/unrated')
def get_unrated_songs() -> Response:
    """Get unrated songs for bulk rating interface."""
    logger.debug("=== /api/unrated endpoint called ===")
    logger.debug(f"Request args: {request.args}")

    try:
        page, error = validate_page_param(request.args)
        if error:
            return error

        logger.debug(f"Fetching page {page} of unrated songs")

        result = db.get_unrated_videos(page=page, limit=50)
        logger.debug(f"Retrieved {len(result['songs'])} songs for page {page}")

        response_data = {
            'success': True,
            **result
        }

        logger.debug(f"Returning {len(response_data['songs'])} songs, page {response_data['page']}/{response_data['total_pages']}")

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"=== ERROR in /api/unrated endpoint ===")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Exception message: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return error_response('Failed to retrieve unrated videos', 500)

@app.route('/api/rate/<video_id>/like', methods=['POST'])
@require_rate_limit
def rate_song_like(video_id: str) -> Response:
    """Rate a specific video as like (for bulk rating)."""
    return rate_song_direct(video_id, 'like')

@app.route('/api/rate/<video_id>/dislike', methods=['POST'])
@require_rate_limit
def rate_song_dislike(video_id: str) -> Response:
    """Rate a specific video as dislike (for bulk rating)."""
    return rate_song_direct(video_id, 'dislike')

def rate_song_direct(video_id: str, rating_type: str) -> Response:
    """
    Directly rate a video by ID without checking current media.
    Used for bulk rating interface.
    """
    try:
        # SECURITY: Validate all inputs before expensive operations
        # 1. Validate rating type first (cheapest check)
        if rating_type not in ['like', 'dislike']:
            logger.warning(f"Invalid rating type: {rating_type} from {request.remote_addr}")
            return error_response('Invalid rating type')

        # 2. Validate video ID format (more expensive regex check)
        is_valid, error = validate_youtube_video_id(video_id)
        if not is_valid:
            logger.warning(f"Invalid video ID format in rate_song_direct: {video_id} from {request.remote_addr}")
            return error

        # 3. Only after all validation: perform expensive database lookup
        video_data = db.get_video(video_id)
        if not video_data:
            return error_response('Video not found in database', 404)

        title = video_data.get('yt_title') or video_data.get('ha_title') or 'Unknown'

        # Check if already rated
        current_rating = video_data.get('rating', 'none')
        if current_rating == rating_type:
            return jsonify({
                'success': True,
                'message': f'Already rated as {rating_type}',
                'already_rated': True
            })

        # Update local database first
        db.record_rating_local(video_id, rating_type)

        # Try to rate on YouTube (if not in quota block)
        should_skip, _ = quota_guard.check_quota_or_skip("rate video on YouTube", video_id, rating_type)
        if should_skip:
            # Queue for later sync
            db.enqueue_rating(video_id, rating_type)
            metrics.record_rating(success=False, queued=True)
            rating_logger.info(f"{rating_type.upper()} | QUEUED | {title} | ID: {video_id} | Quota blocked")
            return jsonify({
                'success': True,
                'message': f'Queued {rating_type} (quota blocked)',
                'queued': True
            })

        # Rate on YouTube API
        yt_api = get_youtube_api()
        if yt_api.set_video_rating(video_id, rating_type):
            db.record_rating(video_id, rating_type)
            metrics.record_rating(success=True, queued=False)
            rating_logger.info(f"{rating_type.upper()} | SUCCESS | {title} | ID: {video_id}")
            return jsonify({
                'success': True,
                'message': f'Rated as {rating_type}',
                'queued': False
            })
        else:
            # Failed but queued
            db.enqueue_rating(video_id, rating_type)
            metrics.record_rating(success=False, queued=True)
            rating_logger.info(f"{rating_type.upper()} | QUEUED | {title} | ID: {video_id} | API returned false")
            return jsonify({
                'success': True,
                'message': f'Queued {rating_type} (API failed)',
                'queued': True
            })

    except Exception as e:
        logger.error(f"Error rating video {video_id}: {e}")
        logger.error(traceback.format_exc())
        return error_response('Failed to rate video', 500)

# ============================================================================
# RATING ROUTES (Main Rating Endpoints)
# ============================================================================

@app.route('/thumbs_up', methods=['POST'])
@csrf.exempt
@require_rate_limit
def thumbs_up() -> Tuple[Response, int]:
    return rate_video('like')

@app.route('/thumbs_down', methods=['POST'])
@csrf.exempt
@require_rate_limit
def thumbs_down() -> Tuple[Response, int]:
    return rate_video('dislike')

# ============================================================================
# MONITORING ROUTES (Health, Status, Metrics)
# ============================================================================

@app.route('/health', methods=['GET'])
def health() -> Response:
    """
    Fast health check endpoint optimized for frequent polling.

    This endpoint is optimized for speed (< 100ms response time) and does NOT:
    - Attempt thread restarts
    - Perform blocking operations

    It provides basic status information for UI polling without expensive operations.
    For full diagnostics with thread recovery, use /status endpoint instead.
    """
    # Quick non-blocking checks only - no thread restarts
    guard_status = quota_guard.status()
    tracker_healthy = history_tracker.is_healthy()
    prober_healthy = quota_prober.is_healthy()

    # Simple health score without expensive metric calculations
    # Base score of 100, deduct for issues
    health_score = 100
    warnings = []

    if not tracker_healthy:
        warnings.append("History tracker is not running")
        health_score -= 25

    if not prober_healthy:
        warnings.append("Quota prober is not running")
        health_score -= 15

    if guard_status.get('blocked'):
        overall_status = "cooldown"
    elif health_score >= 70:
        overall_status = "healthy"
    elif health_score >= 40:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return jsonify({
        "status": overall_status,
        "health_score": health_score,
        "warnings": warnings,
        "quota_guard": guard_status,
        "history_tracker": {
            "healthy": tracker_healthy,
            "enabled": history_tracker.enabled,
        },
        "quota_prober": {
            "healthy": prober_healthy,
            "enabled": quota_prober.enabled,
        },
        "timestamp": time.time()
    }), 200


@app.route('/status', methods=['GET'])
def status() -> Response:
    """
    Detailed system status endpoint with full diagnostics.

    This endpoint provides comprehensive health information but may be slower
    due to metric calculations. Use /health for fast uptime checks.

    Query Parameters:
        format: 'json' (default) or 'html' for formatted view
    """
    stats = rate_limiter.get_stats()
    guard_status = quota_guard.status()

    # Check history tracker health and attempt recovery if needed
    tracker_healthy = history_tracker.is_healthy()
    if not tracker_healthy:
        logger.warning("History tracker unhealthy, attempting restart")
        history_tracker.ensure_running()
        tracker_healthy = history_tracker.is_healthy()

    # Check quota prober health and attempt recovery if needed
    prober_healthy = quota_prober.is_healthy()
    if not prober_healthy:
        logger.warning("Quota prober unhealthy, attempting restart")
        quota_prober.ensure_running()
        prober_healthy = quota_prober.is_healthy()

    # Get health score from metrics
    health_score, warnings = metrics.get_health_score()

    # Add tracker warning if still unhealthy
    if not tracker_healthy:
        warnings.append("History tracker is not running")
        health_score = min(health_score, 50)  # Cap health score if tracker is down

    # Add prober warning if still unhealthy
    if not prober_healthy:
        warnings.append("Quota prober is not running")
        health_score = min(health_score, 60)  # Cap health score if prober is down

    if guard_status.get('blocked'):
        overall_status = "cooldown"
    elif health_score >= 70:
        overall_status = "healthy"
    elif health_score >= 40:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    response_data = {
        "status": overall_status,
        "health_score": health_score,
        "warnings": warnings,
        "rate_limiter": stats,
        "quota_guard": guard_status,
        "history_tracker": {
            "healthy": tracker_healthy,
            "enabled": history_tracker.enabled,
        },
        "quota_prober": {
            "healthy": prober_healthy,
            "enabled": quota_prober.enabled,
        }
    }

    # Check if HTML format is requested (default for browser access)
    format_type = request.args.get('format', 'html')

    if format_type == 'html':
        # Return formatted HTML view
        json_str = json.dumps(response_data, indent=2, sort_keys=True)
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>YouTube Thumbs - System Status</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                    margin: 0;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
                }}
                h1 {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    margin-bottom: 10px;
                }}
                .subtitle {{
                    color: #666;
                    margin-bottom: 30px;
                    font-size: 14px;
                }}
                pre {{
                    background: #f5f5f5;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    padding: 20px;
                    overflow-x: auto;
                    font-family: 'Monaco', 'Courier New', monospace;
                    font-size: 13px;
                    line-height: 1.6;
                }}
                .back-link {{
                    display: inline-block;
                    margin-top: 20px;
                    color: #667eea;
                    text-decoration: none;
                    font-weight: 600;
                    padding: 10px 20px;
                    border-radius: 8px;
                    background: #667eea15;
                    transition: all 0.2s;
                }}
                .back-link:hover {{
                    background: #667eea;
                    color: white;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>💚 System Status</h1>
                <div class="subtitle">Detailed health and diagnostics monitoring</div>
                <pre>{json_str}</pre>
                <a href="javascript:history.back()" class="back-link">← Back to Dashboard</a>
            </div>
        </body>
        </html>
        """
        return html, 200

    return jsonify(response_data)


@app.route('/metrics', methods=['GET'])
def get_metrics() -> Response:
    """
    Comprehensive metrics endpoint for monitoring and analysis.

    Returns detailed statistics about:
    - Cache performance and hit rates
    - API usage and quota status
    - Rating operations (success/failed/queued)
    - Search patterns and failures
    - System uptime and health

    Query Parameters:
        format: 'json' (default) or 'html' for formatted view
    """
    try:
        all_metrics = metrics.get_all_metrics()
        health_score, warnings = metrics.get_health_score()

        response_data = {
            'health': {
                'score': health_score,
                'status': 'healthy' if health_score >= 70 else 'degraded' if health_score >= 40 else 'unhealthy',
                'warnings': warnings
            },
            **all_metrics
        }

        # Check if HTML format is requested (default for browser access)
        format_type = request.args.get('format', 'html')

        if format_type == 'html':
            # Return formatted HTML view
            json_str = json.dumps(response_data, indent=2, sort_keys=True)
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>YouTube Thumbs - Metrics</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                        padding: 20px;
                        margin: 0;
                    }}
                    .container {{
                        max-width: 1200px;
                        margin: 0 auto;
                        background: white;
                        border-radius: 16px;
                        padding: 40px;
                        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
                    }}
                    h1 {{
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                        background-clip: text;
                        margin-bottom: 10px;
                    }}
                    .subtitle {{
                        color: #666;
                        margin-bottom: 30px;
                        font-size: 14px;
                    }}
                    pre {{
                        background: #f5f5f5;
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 20px;
                        overflow-x: auto;
                        font-family: 'Monaco', 'Courier New', monospace;
                        font-size: 13px;
                        line-height: 1.6;
                    }}
                    .back-link {{
                        display: inline-block;
                        margin-top: 20px;
                        color: #667eea;
                        text-decoration: none;
                        font-weight: 600;
                        padding: 10px 20px;
                        border-radius: 8px;
                        background: #667eea15;
                        transition: all 0.2s;
                    }}
                    .back-link:hover {{
                        background: #667eea;
                        color: white;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>📈 System Metrics</h1>
                    <div class="subtitle">Real-time monitoring and performance statistics</div>
                    <pre>{json_str}</pre>
                    <a href="javascript:history.back()" class="back-link">← Back to Dashboard</a>
                </div>
            </body>
            </html>
            """
            return html, 200

        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        return jsonify({'error': 'Failed to generate metrics'}), 500


@app.route('/stats')
def stats_page() -> str:
    """
    Server-side rendered statistics page.
    All processing done on server, no client-side JavaScript required.
    """
    try:
        # Get ingress path for proper link generation
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

        # Check cache first (5 minute TTL)
        cached = db.get_cached_stats('stats_page')
        if cached:
            # Add ingress_path to cached data
            cached['ingress_path'] = ingress_path
            return render_template('stats_server.html', **cached)

        # Fetch fresh data
        summary = db.get_stats_summary()
        most_played = db.get_most_played(10)
        top_channels = db.get_top_channels(10)
        recent = db.get_recent_activity(15)
        pending_summary = db.get_pending_summary()

        # Calculate rating percentages (ensure integers to avoid type errors)
        liked = int(summary.get('liked', 0) or 0)
        disliked = int(summary.get('disliked', 0) or 0)
        unrated = int(summary.get('unrated', 0) or 0)
        total = liked + disliked + unrated

        if total > 0:
            rating_percentages = {
                'liked': (liked / total) * 100,
                'disliked': (disliked / total) * 100,
                'unrated': (unrated / total) * 100
            }
        else:
            rating_percentages = {'liked': 0, 'disliked': 0, 'unrated': 0}

        # Format recent activity
        recent_activity = []
        for item in recent:
            title = get_video_title(item)
            artist = get_video_artist(item)

            # Calculate time ago
            if item.get('date_last_played'):
                time_ago = format_relative_time(item['date_last_played'])
                if time_ago == "unknown":
                    time_ago = "Recently"
            else:
                time_ago = "Recently"

            rating_icons = {'like': '👍', 'dislike': '👎', 'none': '➖'}
            rating_icon = rating_icons.get(item.get('rating', 'none'), '➖')

            recent_activity.append({
                'title': title,
                'artist': artist,
                'time_ago': time_ago,
                'rating_icon': rating_icon,
                'yt_video_id': item.get('yt_video_id')
            })

        # Format most played
        formatted_most_played = []
        for video in most_played:
            title = get_video_title(video)
            artist = get_video_artist(video)
            formatted_most_played.append({
                'title': title,
                'artist': artist,
                'play_count': video.get('play_count', 0),
                'yt_video_id': video.get('yt_video_id')
            })

        # Prepare template data
        template_data = {
            'ingress_path': ingress_path,
            'summary': summary,
            'rating_percentages': rating_percentages,
            'most_played': formatted_most_played,
            'top_channels': top_channels,
            'recent_activity': recent_activity,
            'pending_summary': pending_summary,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Cache for 5 minutes
        db.set_cached_stats('stats_page', template_data, ttl_seconds=300)

        return render_template('stats_server.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering stats page: {e}")
        logger.error(traceback.format_exc())
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading statistics</h1><p>An internal error occurred. Please try again later.</p>", 500


@app.route('/stats/liked')
def stats_liked_page() -> str:
    """Show paginated list of liked videos."""
    try:
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
        page = int(request.args.get('page', 1))

        result = db.get_rated_videos('like', page=page, per_page=50)

        # Format videos
        formatted_videos = []
        for video in result['videos']:
            title = get_video_title(video)
            artist = get_video_artist(video)
            formatted_videos.append({
                'title': title,
                'artist': artist,
                'yt_video_id': video.get('yt_video_id'),
                'play_count': video.get('play_count', 0),
                'date_last_played': video.get('date_last_played')
            })

        return render_template('stats_rated.html',
                             ingress_path=ingress_path,
                             rating_type='liked',
                             rating_icon='👍',
                             videos=formatted_videos,
                             total_count=result['total_count'],
                             current_page=result['current_page'],
                             total_pages=result['total_pages'])
    except Exception as e:
        logger.error(f"Error rendering liked stats: {e}")
        return "<h1>Error loading liked videos</h1>", 500


@app.route('/stats/disliked')
def stats_disliked_page() -> str:
    """Show paginated list of disliked videos."""
    try:
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
        page = int(request.args.get('page', 1))

        result = db.get_rated_videos('dislike', page=page, per_page=50)

        # Format videos
        formatted_videos = []
        for video in result['videos']:
            title = get_video_title(video)
            artist = get_video_artist(video)
            formatted_videos.append({
                'title': title,
                'artist': artist,
                'yt_video_id': video.get('yt_video_id'),
                'play_count': video.get('play_count', 0),
                'date_last_played': video.get('date_last_played')
            })

        return render_template('stats_rated.html',
                             ingress_path=ingress_path,
                             rating_type='disliked',
                             rating_icon='👎',
                             videos=formatted_videos,
                             total_count=result['total_count'],
                             current_page=result['current_page'],
                             total_pages=result['total_pages'])
    except Exception as e:
        logger.error(f"Error rendering disliked stats: {e}")
        return "<h1>Error loading disliked videos</h1>", 500


def _validate_data_viewer_params(request_args):
    """
    Validate and sanitize data viewer parameters.

    Returns:
        Tuple of (page, sort_by, sort_order, selected_columns, columns_param, all_columns)
    """
    # Get query parameters with validation
    page, _ = validate_page_param(request_args)
    if not page or page > MAX_PAGE_NUMBER:
        page = 1

    sort_by = request_args.get('sort', 'date_last_played')
    sort_order = request_args.get('order', 'DESC')

    # Try to get from checkboxes first (getlist for multiple values)
    selected_columns = request_args.getlist('column')

    # If no checkboxes, try the columns parameter (for pagination links)
    if not selected_columns:
        columns_param = request_args.get('columns', ','.join(DEFAULT_DATA_VIEWER_COLUMNS))
        selected_columns = [c.strip() for c in columns_param.split(',') if c.strip()]

    # SECURITY: Validate ALL selected columns against whitelist to prevent SQL injection
    validated_columns = []
    for col in selected_columns:
        if col in DATA_VIEWER_COLUMNS:
            validated_columns.append(col)
        else:
            logger.warning(
                f"Attempted to select invalid column: "
                f"{_sanitize_log_value(col)} from {request.remote_addr}"
            )

    # Use validated columns or fallback to defaults
    if not validated_columns:
        validated_columns = DEFAULT_DATA_VIEWER_COLUMNS

    selected_columns = validated_columns

    # Create columns param for pagination links
    columns_param = ','.join(selected_columns)

    # Ensure valid sort column (SQL injection protection)
    if sort_by not in DATA_VIEWER_COLUMNS:
        logger.warning(
            f"Invalid sort column attempted: "
            f"{_sanitize_log_value(sort_by)} from {request.remote_addr}"
        )
        sort_by = 'date_last_played'

    # Ensure valid sort order (SQL injection protection)
    sort_order = sort_order.upper()
    if sort_order not in ['ASC', 'DESC']:
        logger.warning(
            f"Invalid sort order attempted: "
            f"{_sanitize_log_value(sort_order)} from {request.remote_addr}"
        )
        sort_order = 'DESC'

    return page, sort_by, sort_order, selected_columns, columns_param, DATA_VIEWER_COLUMNS


def _build_data_query(db, selected_columns, sort_by, sort_order, page, limit=DEFAULT_PAGE_SIZE):
    """
    Build and execute data query with pagination.

    SECURITY: Uses triple-layer protection against SQL injection:
    1. Input validation against whitelist (caller responsibility)
    2. Assertions to catch programming errors
    3. Explicit SQL identifier construction (no f-strings with user data)

    Args:
        db: Database instance
        selected_columns: List of column names (must be pre-validated)
        sort_by: Sort column name (must be pre-validated)
        sort_order: 'ASC' or 'DESC' (must be pre-validated)
        page: Page number
        limit: Number of results per page

    Returns:
        Tuple of (rows, total_count, total_pages, adjusted_page)

    Note: This function may adjust the page number if it exceeds total_pages.
    Always use the returned page value, not the input page value.
    """
    # SECURITY: Defense-in-depth validation (assert to catch programming errors)
    if not all(col in DATA_VIEWER_COLUMNS for col in selected_columns):
        logger.error(f"SECURITY: Invalid columns in query: {selected_columns}")
        raise ValueError(f"Invalid columns passed to _build_data_query")

    if sort_by not in DATA_VIEWER_COLUMNS:
        logger.error(f"SECURITY: Invalid sort column: {sort_by}")
        raise ValueError(f"Invalid sort_by passed to _build_data_query")

    if sort_order not in ('ASC', 'DESC'):
        logger.error(f"SECURITY: Invalid sort order: {sort_order}")
        raise ValueError(f"Invalid sort_order passed to _build_data_query")

    # SECURITY: Build SQL with explicit string concatenation (safer than f-strings)
    # Use double quotes for SQL identifiers (standard SQL)
    quoted_columns = []
    for col in selected_columns:
        # Verify again and quote
        if col in DATA_VIEWER_COLUMNS:
            # Replace any quotes in column name (defense in depth)
            safe_col = col.replace('"', '""')
            quoted_columns.append('"' + safe_col + '"')

    select_clause = ', '.join(quoted_columns)

    # Quote sort column with same escaping
    safe_sort = sort_by.replace('"', '""')
    quoted_sort_by = '"' + safe_sort + '"'

    # Get total count of distinct video IDs
    count_query = "SELECT COUNT(DISTINCT yt_video_id) as count FROM video_ratings"
    total_count = db._conn.execute(count_query).fetchone()['count']

    # Calculate pagination
    total_pages = (total_count + limit - 1) // limit
    page = max(1, min(page, total_pages if total_pages > 0 else 1))
    offset = (page - 1) * limit

    # SECURITY: Build query with parameterized LIMIT/OFFSET
    # Use explicit string building to avoid f-string injection risks
    # nosec B608 - select_clause and sort_order are validated against whitelist above
    data_query = (
        "SELECT " + select_clause + " "
        "FROM video_ratings "
        "WHERE rowid IN ("
        "  SELECT MAX(rowid) "
        "  FROM video_ratings "
        "  GROUP BY yt_video_id"
        ") "
        "ORDER BY " + quoted_sort_by + " " + sort_order + " "
        "LIMIT ? OFFSET ?"
    )

    cursor = db._conn.execute(data_query, (limit, offset))
    rows = cursor.fetchall()

    return rows, total_count, total_pages, page


def _format_data_rows(rows, selected_columns):
    """
    Format database rows for template display.

    Returns:
        List of formatted row dictionaries
    """
    formatted_rows = []
    for row in rows:
        formatted_row = {}
        for col in selected_columns:
            value = row[col]
            # Format specific column types
            if col == 'rating':
                if value == 'like':
                    formatted_row[col] = '👍 Like'
                elif value == 'dislike':
                    formatted_row[col] = '👎 Dislike'
                else:
                    formatted_row[col] = '➖ None'
            elif col in ['date_added', 'date_last_played', 'yt_published_at']:
                if value:
                    try:
                        dt = parse_timestamp(value)
                        formatted_row[col] = dt.strftime('%Y-%m-%d %H:%M')
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse timestamp '{value}' for column {col}: {e}")
                        formatted_row[col] = value
                else:
                    formatted_row[col] = '-'
            elif col == 'yt_match_pending':
                formatted_row[col] = '✓' if value == 1 else '✗'
            elif col == 'yt_url' and value:
                # Make URL clickable
                formatted_row[col] = value
                formatted_row[col + '_link'] = True
            elif value is None:
                formatted_row[col] = '-'
            else:
                formatted_row[col] = value
        formatted_rows.append(formatted_row)

    return formatted_rows


@app.route('/data')
def data_viewer() -> str:
    """
    Server-side rendered database viewer with column selection and sorting.
    All processing done on server, no client-side JavaScript required.
    """
    try:
        # Get ingress path for proper link generation
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

        # Validate and parse request parameters
        page, sort_by, sort_order, selected_columns, columns_param, all_columns = \
            _validate_data_viewer_params(request.args)

        # Build and execute query
        rows, total_count, total_pages, page = _build_data_query(
            db, selected_columns, sort_by, sort_order, page
        )

        # Format rows for display
        formatted_rows = _format_data_rows(rows, selected_columns)

        # Generate page numbers for pagination
        page_numbers = generate_page_numbers(page, total_pages)

        # Prepare template data
        template_data = {
            'ingress_path': ingress_path,
            'rows': formatted_rows,
            'selected_columns': selected_columns,
            'all_columns': all_columns,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count,
            'columns_param': columns_param,
            'page_numbers': page_numbers
        }

        return render_template('data_viewer.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering data viewer: {e}")
        logger.error(traceback.format_exc())
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading database viewer</h1><p>An internal error occurred. Please try again later.</p>", 500


# Database proxy routes - delegates to database_proxy module
# Allow all HTTP methods (GET, POST, etc.) for sqlite_web functionality like exports
app.add_url_rule('/database', 'database_proxy_root', create_database_proxy_handler(), defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])
app.add_url_rule('/database/<path:path>', 'database_proxy_path', create_database_proxy_handler(), methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'])

# ============================================================================
# APPLICATION INITIALIZATION
# ============================================================================

if __name__ == '__main__':
    # nosec B104 - Binding to 0.0.0.0 is intentional for Docker container deployment
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '21812'))

    logger.info(f"Starting YouTube Thumbs service on {host}:{port}")
    logger.info(f"Flask will be accessible at http://{host}:{port}")

    # Initialize YouTube API
    yt_api = None
    try:
        yt_api = get_youtube_api()
    except Exception as e:
        logger.error(f"Failed to initialize YouTube API: {str(e)}")
        logger.error("Please ensure credentials.json exists and run the OAuth flow")

    # Run startup health checks
    run_startup_checks(ha_api, yt_api, db, quota_guard)

    # Clear stats cache on startup to prevent stale data issues
    logger.info("Clearing stats cache...")
    db.invalidate_stats_cache()

    logger.info("Starting Flask application...")
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"Flask failed to start: {e}")
        logger.error(traceback.format_exc())
        raise
