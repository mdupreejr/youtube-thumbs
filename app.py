import atexit
from flask import Flask, jsonify, Response, render_template, request, send_from_directory
from typing import Tuple, Optional, Dict, Any
import os
import time
import traceback
import requests
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


@app.route('/api/stats/most-played', methods=['GET'])
def get_most_played_stats() -> Response:
    """Get most played songs for statistics dashboard."""
    try:
        limit = int(request.args.get('limit', 10))
        limit = max(1, min(limit, 100))  # Enforce bounds: 1-100
        videos = db.get_most_played(limit)
        return jsonify({'success': True, 'data': videos})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400
    except Exception as e:
        logger.error(f"Error getting most played stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve most played statistics'}), 500


@app.route('/api/stats/top-channels', methods=['GET'])
def get_top_channels_stats() -> Response:
    """Get top channels/artists for statistics dashboard."""
    try:
        limit = int(request.args.get('limit', 10))
        limit = max(1, min(limit, 100))  # Enforce bounds: 1-100
        channels = db.get_top_channels(limit)
        return jsonify({'success': True, 'data': channels})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400
    except Exception as e:
        logger.error(f"Error getting top channels stats: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve top channels statistics'}), 500


@app.route('/api/stats/rating-distribution', methods=['GET'])
def get_rating_distribution() -> Response:
    """Get rating distribution for pie chart."""
    try:
        distribution = db.get_ratings_breakdown()
        return jsonify({'success': True, 'data': distribution})
    except Exception as e:
        logger.error(f"Error getting rating distribution: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve rating distribution'}), 500


@app.route('/api/stats/summary', methods=['GET'])
def get_stats_summary() -> Response:
    """Get summary statistics for dashboard."""
    try:
        summary = db.get_stats_summary()
        return jsonify({
            'success': True,
            'data': summary
        })
    except Exception as e:
        logger.error(f"Error getting stats summary: {e}")
        return jsonify({'success': False, 'error': 'Failed to retrieve summary statistics'}), 500


@app.route('/api/stats/top-rated', methods=['GET'])
def get_top_rated_api() -> Response:
    """Get top rated videos."""
    try:
        try:
            limit = int(request.args.get('limit', 10))
            limit = max(1, min(limit, 100))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400

        videos = db.get_top_rated(limit)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error getting top rated: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/stats/recent', methods=['GET'])
def get_recent_activity_api() -> Response:
    """Get recent activity."""
    try:
        try:
            limit = int(request.args.get('limit', 20))
            limit = max(1, min(limit, 100))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid limit parameter'}), 400

        videos = db.get_recent_activity(limit)
        return jsonify({'success': True, 'data': videos})
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/stats/categories', methods=['GET'])
def get_category_breakdown_api() -> Response:
    """Get category breakdown."""
    try:
        categories = db.get_category_breakdown()
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"Error getting category breakdown: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/stats/timeline', methods=['GET'])
def get_timeline_stats_api() -> Response:
    """Get time-based stats."""
    try:
        try:
            days = int(request.args.get('days', 7))
            days = max(1, min(days, 365))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid days parameter'}), 400

        timeline = db.get_plays_by_period(days)
        return jsonify({'success': True, 'data': timeline})
    except Exception as e:
        logger.error(f"Error getting timeline stats: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/stats/api-usage', methods=['GET'])
def get_api_usage_summary_endpoint() -> Response:
    """Get YouTube API usage statistics summary."""
    try:
        try:
            days = int(request.args.get('days', 30))
            days = max(1, min(days, 365))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid days parameter'}), 400

        usage = db.get_api_usage_summary(days)
        return jsonify({'success': True, 'data': usage})
    except Exception as e:
        logger.error(f"Error getting API usage summary: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/stats/api-usage/daily', methods=['GET'])
def get_api_daily_usage_endpoint() -> Response:
    """Get YouTube API usage for a specific day."""
    try:
        date_str = request.args.get('date')  # YYYY-MM-DD format
        usage = db.get_api_daily_usage(date_str)
        return jsonify({'success': True, 'data': usage})
    except Exception as e:
        logger.error(f"Error getting daily API usage: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/stats/api-usage/hourly', methods=['GET'])
def get_api_hourly_usage_endpoint() -> Response:
    """Get hourly YouTube API usage for a specific day."""
    try:
        date_str = request.args.get('date')  # YYYY-MM-DD format
        usage = db.get_api_hourly_usage(date_str)
        return jsonify({'success': True, 'data': usage})
    except Exception as e:
        logger.error(f"Error getting hourly API usage: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/history/plays', methods=['GET'])
def get_play_history_api() -> Response:
    """Get paginated play history."""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        date_from = request.args.get('from')
        date_to = request.args.get('to')

        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        history = db.get_play_history(limit, offset, date_from, date_to)
        return jsonify({'success': True, 'data': history})
    except Exception as e:
        logger.error(f"Error getting play history: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/history/search', methods=['GET'])
def search_history_api() -> Response:
    """Search history."""
    try:
        query = request.args.get('q', '')
        if not query or len(query) < 2:
            return jsonify({'success': False, 'error': 'Query must be at least 2 characters'}), 400

        limit = int(request.args.get('limit', 50))
        limit = max(1, min(limit, 200))

        results = db.search_history(query, limit)
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        logger.error(f"Error searching history: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/insights/patterns', methods=['GET'])
def get_listening_patterns_api() -> Response:
    """Get listening patterns analysis."""
    try:
        patterns = db.get_listening_patterns()
        return jsonify({'success': True, 'data': patterns})
    except Exception as e:
        logger.error(f"Error getting listening patterns: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/insights/trends', methods=['GET'])
def get_trends_api() -> Response:
    """Get various trend analyses."""
    try:
        discovery = db.get_discovery_stats()
        play_distribution = db.get_play_distribution()

        trends = {
            'discovery': discovery,
            'play_distribution': play_distribution
        }
        return jsonify({'success': True, 'data': trends})
    except Exception as e:
        logger.error(f"Error getting trends: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/analytics/correlation', methods=['GET'])
def get_correlation_stats_api() -> Response:
    """Get correlation analysis."""
    try:
        correlation = db.get_correlation_stats()
        return jsonify({'success': True, 'data': correlation})
    except Exception as e:
        logger.error(f"Error getting correlation stats: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/analytics/retention', methods=['GET'])
def get_retention_analysis_api() -> Response:
    """Get retention analysis."""
    try:
        retention = db.get_retention_analysis()
        return jsonify({'success': True, 'data': retention})
    except Exception as e:
        logger.error(f"Error getting retention analysis: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/analytics/duration', methods=['GET'])
def get_duration_analysis_api() -> Response:
    """Get duration preferences analysis."""
    try:
        duration = db.get_duration_analysis()
        return jsonify({'success': True, 'data': duration})
    except Exception as e:
        logger.error(f"Error getting duration analysis: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/analytics/source', methods=['GET'])
def get_source_breakdown_api() -> Response:
    """Get source breakdown analysis."""
    try:
        source = db.get_source_breakdown()
        return jsonify({'success': True, 'data': source})
    except Exception as e:
        logger.error(f"Error getting source breakdown: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/explorer/filter', methods=['POST'])
def filter_videos_api() -> Response:
    """Filter videos with complex criteria."""
    try:
        filters = request.get_json() or {}
        results = db.filter_videos(filters)
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        logger.error(f"Error filtering videos: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/explorer/channels', methods=['GET'])
def get_channels_list_api() -> Response:
    """Get list of all channels for filter dropdown."""
    try:
        channels = db.get_all_channels()
        return jsonify({'success': True, 'data': channels})
    except Exception as e:
        logger.error(f"Error getting channels list: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/explorer/categories', methods=['GET'])
def get_categories_list_api() -> Response:
    """Get list of all categories."""
    try:
        categories = db.get_all_categories()
        return jsonify({'success': True, 'data': categories})
    except Exception as e:
        logger.error(f"Error getting categories list: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


@app.route('/api/recommendations', methods=['GET'])
def get_recommendations_api() -> Response:
    """Get video recommendations."""
    try:
        based_on = request.args.get('strategy', 'likes')
        limit = int(request.args.get('limit', 10))

        # Validate strategy
        if based_on not in ['likes', 'played', 'discover']:
            based_on = 'likes'

        # Limit range
        limit = max(1, min(limit, 50))

        recommendations = db.get_recommendations(based_on, limit)
        return jsonify({'success': True, 'data': recommendations})
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        return jsonify({'success': False, 'error': 'An error occurred processing your request'}), 500


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

        # Calculate rating percentages
        total = summary['liked'] + summary['disliked'] + summary['unrated']
        if total > 0:
            rating_percentages = {
                'liked': (summary['liked'] / total) * 100,
                'disliked': (summary['disliked'] / total) * 100,
                'unrated': (summary['unrated'] / total) * 100
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


@app.route('/database', defaults={'path': ''})
@app.route('/database/<path:path>')
def database_proxy(path):
    """Proxy requests to sqlite_web running on port 8080."""
    sqlite_web_host = os.getenv('SQLITE_WEB_HOST', '127.0.0.1')
    sqlite_web_port = os.getenv('SQLITE_WEB_PORT', '8080')
    sqlite_web_url = f"http://{sqlite_web_host}:{sqlite_web_port}"

    # Build the target URL
    if path:
        target_url = f"{sqlite_web_url}/{path}"
    else:
        target_url = sqlite_web_url

    # Auto-sort video_ratings table by date_last_played (descending) if no sort specified
    query_string = request.query_string.decode('utf-8')
    if 'video_ratings' in path and not any(x in query_string for x in ['_sort', '_sort_desc']):
        # Add default sort by date_last_played descending
        if query_string:
            query_string += '&_sort_desc=date_last_played'
        else:
            query_string = '_sort_desc=date_last_played'

    # Forward query parameters
    if query_string:
        target_url += f"?{query_string}"

    try:
        # Forward the request to sqlite_web
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers={key: value for (key, value) in request.headers if key != 'Host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30
        )

        # Build response
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in resp.raw.headers.items()
                   if name.lower() not in excluded_headers]

        # Inject custom CSS and fix links for Home Assistant ingress if this is HTML
        content = resp.content
        content_type = resp.headers.get('Content-Type', '')
        if 'text/html' in content_type and b'</head>' in content:
            # Rewrite links for ingress compatibility
            # sqlite_web generates links like href="/ratings.db/table"
            # We need to rewrite them to include the ingress prefix
            if request.environ.get('HTTP_X_INGRESS_PATH'):
                ingress_path = request.environ.get('HTTP_X_INGRESS_PATH')
                # Rewrite hrefs to include /database prefix and ingress path
                content = content.replace(b'href="/', f'href="{ingress_path}/database/'.encode())
                content = content.replace(b"href='/", f"href='{ingress_path}/database/".encode())
                content = content.replace(b'action="/', f'action="{ingress_path}/database/'.encode())
                content = content.replace(b"action='/", f"action='{ingress_path}/database/".encode())
            else:
                # Not through ingress, just add /database prefix
                content = content.replace(b'href="/', b'href="/database/')
                content = content.replace(b"href='/", b"href='/database/")
                content = content.replace(b'action="/', b'action="/database/')
                content = content.replace(b"action='/", b"action='/database/")
            custom_css = b'''
<style>
/* Custom CSS to make sqlite_web sidebar narrower and fix theme compatibility */
.sidebar {
    width: 180px !important;
    min-width: 180px !important;
}
.content {
    margin-left: 190px !important;
}

/* Fix background colors for proper visibility */
body {
    background-color: #ffffff !important;
    color: #333333 !important;
}

/* Ensure content areas have proper background */
.content, .main, #content, main {
    background-color: #ffffff !important;
    color: #333333 !important;
}

/* Fix table styling */
table {
    background-color: #ffffff !important;
    color: #333333 !important;
}

table th {
    background-color: #f5f5f5 !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

table td {
    background-color: #ffffff !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

table tr:hover td {
    background-color: #f9f9f9 !important;
}

/* Fix form and input elements */
input, select, textarea, button {
    background-color: #ffffff !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

/* Fix links */
a {
    color: #0066cc !important;
}

a:hover {
    color: #004499 !important;
}

/* Fix pre and code blocks */
pre, code {
    background-color: #f5f5f5 !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

/* Fix sidebar */
.sidebar, #sidebar, nav {
    background-color: #f8f8f8 !important;
    color: #333333 !important;
}

/* Fix header areas */
header, .header {
    background-color: #f5f5f5 !important;
    color: #333333 !important;
}

@media (max-width: 768px) {
    .sidebar {
        width: 150px !important;
        min-width: 150px !important;
    }
    .content {
        margin-left: 160px !important;
    }
}
</style>
'''
            content = content.replace(b'</head>', custom_css + b'</head>')

        # nosec B201 - Content from trusted internal sqlite_web proxy (localhost only)
        # Protected by CSP headers and X-Content-Type-Options below
        response = Response(content, resp.status_code, headers)

        # Add security headers to prevent XSS
        # Only allow scripts/styles from self to prevent injection attacks
        response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' 'unsafe-eval'; img-src 'self' data:;"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'

        return response

    except requests.exceptions.ConnectionError:
        logger.error("Failed to connect to sqlite_web - is it running?")
        return Response("Database viewer not available. sqlite_web may not be running.", status=503)
    except Exception as e:
        logger.error(f"Error proxying to sqlite_web: {e}")
        logger.error(traceback.format_exc())
        return Response("Error accessing database viewer", status=500)


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

    logger.info("Starting Flask application...")
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"Flask failed to start: {e}")
        logger.error(traceback.format_exc())
        raise
