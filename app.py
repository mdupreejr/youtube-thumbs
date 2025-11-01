import atexit
from flask import Flask, jsonify, Response, render_template, request, send_from_directory
from typing import Tuple, Optional, Dict, Any
import os
import time
import traceback
from datetime import datetime, timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
from logger import logger, user_action_logger, rating_logger
from rate_limiter import rate_limiter
from homeassistant_api import ha_api
from youtube_api import get_youtube_api
from database import get_database
from history_tracker import HistoryTracker
from quota_guard import quota_guard
from quota_prober import QuotaProber
from startup_checks import run_startup_checks, check_home_assistant_api, check_youtube_api, check_database
from constants import FALSE_VALUES
from video_helpers import is_youtube_content
from metrics_tracker import metrics
from search_helpers import search_and_match_video_refactored
from cache_helpers import find_cached_video_refactored
from database_proxy import create_database_proxy_handler
from routes.data_api import bp as data_api_bp, init_data_api_routes

app = Flask(__name__)

# Configure Flask to work behind Home Assistant ingress proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Request/Response logging middleware
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
    """Log all outgoing responses."""
    logger.debug("-"*60)
    logger.debug(f"OUTGOING RESPONSE: {request.method} {request.path}")
    logger.debug(f"  Status: {response.status_code}")
    logger.debug(f"  Content-Type: {response.content_type}")
    if response.content_type and 'json' in response.content_type:
        logger.debug(f"  JSON Body: {response.get_data(as_text=True)[:500]}")  # First 500 chars
    elif response.content_type and 'html' in response.content_type:
        logger.debug(f"  HTML Body (first 200 chars): {response.get_data(as_text=True)[:200]}")
    logger.debug("-"*60)
    return response

# Add error handler to show actual errors
@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all error handler - returns JSON for API routes, HTML for pages."""
    from flask import request

    logger.error(f"Unhandled exception on {request.path}: {e}")
    logger.error(traceback.format_exc())

    # Check if this is an API route - return JSON
    if request.path.startswith('/api/') or request.path.startswith('/test/') or request.path.startswith('/health') or request.path.startswith('/metrics'):
        return jsonify({
            'success': False,
            'error': str(e),
            'type': type(e).__name__
        }), 500

    # For regular pages, return HTML with error details
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

db = get_database()

# Initialize and register data API blueprint
init_data_api_routes(db)
app.register_blueprint(data_api_bp)


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
    batch_size = max(1, min(batch_size, 50))

    if quota_guard.is_blocked():
        return

    # Get more pending ratings to process in batch
    pending_jobs = db.list_pending_ratings(limit=batch_size)
    if not pending_jobs:
        return

    # Prepare batch ratings
    ratings_to_process = []
    for job in pending_jobs:
        if quota_guard.is_blocked():
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
    """Wrapper for search_helpers.search_and_match_video_refactored."""
    yt_api = get_youtube_api()
    return search_and_match_video_refactored(ha_media, yt_api, db)


def _cache_wrapper(ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Wrapper for cache_helpers.find_cached_video_refactored."""
    return find_cached_video_refactored(db, ha_media)


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


history_tracker = HistoryTracker(
    ha_api=ha_api,
    database=db,
    find_cached_video=_cache_wrapper,
    search_and_match_video=_search_wrapper,
    poll_interval=_history_poll_interval(),
    enabled=_history_tracker_enabled(),
)
history_tracker.start()
atexit.register(history_tracker.stop)


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
quota_prober.start()
atexit.register(quota_prober.stop)


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
        return jsonify({"success": False, "error": "An unexpected error occurred while rating the video"}), 500

@app.route('/static/<path:filename>')
def serve_static(filename):
    """
    Explicitly serve static files to work through Home Assistant ingress.
    Flask's default static serving doesn't respect ingress paths properly.
    """
    try:
        static_dir = os.path.join(app.root_path, 'static')
        logger.debug(f"Serving static file: {filename} from {static_dir}")
        response = send_from_directory(static_dir, filename)
        # Add cache headers for static files
        response.headers['Cache-Control'] = 'public, max-age=300'  # 5 minutes
        return response
    except FileNotFoundError:
        logger.error(f"Static file not found: {filename} in {static_dir}")
        return f"File not found: {filename}", 404
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {e}")
        logger.error(traceback.format_exc())
        return f"Error serving file: {str(e)}", 500

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
            yt_success, yt_message = check_youtube_api(yt_api)
            template_data['yt_test'] = {'success': yt_success, 'message': yt_message}

            # Test Database
            db_success, db_message = check_database(db)
            template_data['db_test'] = {'success': db_success, 'message': db_message}

        # Get unrated songs if on rating tab
        elif current_tab == 'rating':
            try:
                page = int(request.args.get('page', 1))
                if page < 1:
                    page = 1
            except (ValueError, TypeError):
                page = 1

            result = db.get_unrated_videos(page=page, limit=50)

            # Format songs for template
            formatted_songs = []
            for song in result['songs']:
                title = (song.get('ha_title') or song.get('yt_title') or 'Unknown').strip() or 'Unknown'
                artist = (song.get('ha_artist') or song.get('yt_channel') or 'Unknown').strip() or 'Unknown'

                # Format duration if available
                duration_str = ''
                if song.get('duration'):
                    duration = int(song['duration'])
                    minutes = duration // 60
                    seconds = duration % 60
                    duration_str = f"{minutes}:{seconds:02d}"

                formatted_songs.append({
                    'id': song['yt_video_id'],
                    'title': title,
                    'artist': artist,
                    'duration': duration_str
                })

            template_data['songs'] = formatted_songs
            template_data['current_page'] = result['page']
            template_data['total_pages'] = result['total_pages']
            template_data['total_unrated'] = result['total_unrated']

        return render_template('index_server.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering index page: {e}")
        logger.error(traceback.format_exc())
        return f"<h1>Error loading page</h1><p>{str(e)}</p>", 500

@app.route('/rate-song', methods=['POST'])
def rate_song_form() -> Response:
    """
    Handle bulk rating form submissions from server-side rendered page.
    Processes the rating and redirects back to the rating tab.
    """
    from flask import redirect, url_for
    try:
        song_id = request.form.get('song_id')
        rating = request.form.get('rating')
        page = request.form.get('page', '1')

        if not song_id or not rating:
            logger.error("Missing song_id or rating in form submission")
            return redirect(url_for('index', tab='rating', page=page))

        if rating not in ['like', 'dislike', 'skip']:
            logger.error(f"Invalid rating value: {rating}")
            return redirect(url_for('index', tab='rating', page=page))

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
        return redirect(url_for('index', tab='rating', page=page))

    except Exception as e:
        logger.error(f"Error processing rating form: {e}")
        logger.error(traceback.format_exc())
        # Redirect back even on error
        page = request.form.get('page', '1')
        return redirect(url_for('index', tab='rating', page=page))

@app.route('/test/youtube')
def test_youtube() -> Response:
    """Test YouTube API connectivity and quota status."""
    logger.debug("=== /test/youtube endpoint called ===")
    try:
        yt_api = get_youtube_api()
        success, message = check_youtube_api(yt_api)
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
        return jsonify({"success": False, "message": "Error testing Home Assistant connection"})

@app.route('/api/unrated')
def get_unrated_songs() -> Response:
    """Get unrated songs for bulk rating interface."""
    logger.debug("=== /api/unrated endpoint called ===")
    logger.debug(f"Request args: {request.args}")

    try:
        try:
            page = int(request.args.get('page', 1))
            if page < 1:
                return jsonify({'success': False, 'error': 'Page must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid page parameter: must be a positive integer'}), 400

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
        return jsonify({'success': False, 'error': 'Failed to retrieve unrated videos'}), 500

@app.route('/api/rate/<video_id>/like', methods=['POST'])
def rate_song_like(video_id: str) -> Response:
    """Rate a specific video as like (for bulk rating)."""
    return rate_song_direct(video_id, 'like')

@app.route('/api/rate/<video_id>/dislike', methods=['POST'])
def rate_song_dislike(video_id: str) -> Response:
    """Rate a specific video as dislike (for bulk rating)."""
    return rate_song_direct(video_id, 'dislike')

def rate_song_direct(video_id: str, rating_type: str) -> Response:
    """
    Directly rate a video by ID without checking current media.
    Used for bulk rating interface.
    """
    try:
        # Get video info from database
        video_data = db.get_video(video_id)
        if not video_data:
            return jsonify({'success': False, 'error': 'Video not found in database'}), 404

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
        if quota_guard.is_blocked():
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
        return jsonify({'success': False, 'error': 'Failed to rate video'}), 500

@app.route('/thumbs_up', methods=['POST'])
def thumbs_up() -> Tuple[Response, int]:
    return rate_video('like')

@app.route('/thumbs_down', methods=['POST'])
def thumbs_down() -> Tuple[Response, int]:
    return rate_video('dislike')


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
        import json
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
            import json
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
            title = (item.get('ha_title') or item.get('yt_title') or 'Unknown').strip() or 'Unknown'
            artist = (item.get('ha_artist') or item.get('yt_channel') or 'Unknown').strip() or 'Unknown'

            # Calculate time ago
            if item.get('date_last_played'):
                try:
                    played_dt = datetime.fromisoformat(item['date_last_played'].replace(' ', 'T'))
                    delta = datetime.now() - played_dt
                    if delta.days > 0:
                        time_ago = f"{delta.days}d ago"
                    elif delta.seconds >= 3600:
                        time_ago = f"{delta.seconds // 3600}h ago"
                    elif delta.seconds >= 60:
                        time_ago = f"{delta.seconds // 60}m ago"
                    else:
                        time_ago = "Just now"
                except:
                    time_ago = "Recently"
            else:
                time_ago = "Recently"

            rating_icons = {'like': '👍', 'dislike': '👎', 'none': '➖'}
            rating_icon = rating_icons.get(item.get('rating', 'none'), '➖')

            recent_activity.append({
                'title': title,
                'artist': artist,
                'time_ago': time_ago,
                'rating_icon': rating_icon
            })

        # Format most played
        formatted_most_played = []
        for video in most_played:
            title = (video.get('ha_title') or video.get('yt_title') or 'Unknown').strip() or 'Unknown'
            artist = (video.get('ha_artist') or video.get('yt_channel') or 'Unknown').strip() or 'Unknown'
            formatted_most_played.append({
                'title': title,
                'artist': artist,
                'play_count': video.get('play_count', 0)
            })

        # Prepare template data
        template_data = {
            'ingress_path': ingress_path,
            'summary': summary,
            'rating_percentages': rating_percentages,
            'most_played': formatted_most_played,
            'top_channels': top_channels,
            'recent_activity': recent_activity,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Cache for 5 minutes
        db.set_cached_stats('stats_page', template_data, ttl_seconds=300)

        return render_template('stats_server.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering stats page: {e}")
        logger.error(traceback.format_exc())
        return f"<h1>Error loading statistics</h1><p>{str(e)}</p>", 500


# Database proxy routes - delegates to database_proxy module
app.add_url_rule('/database', 'database_proxy_root', create_database_proxy_handler(), defaults={'path': ''})
app.add_url_rule('/database/<path:path>', 'database_proxy_path', create_database_proxy_handler())


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
    run_startup_checks(ha_api, yt_api, db)

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
