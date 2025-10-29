import atexit
from flask import Flask, jsonify, Response, render_template
from typing import Tuple, Optional, Dict, Any
import os
import traceback
from werkzeug.middleware.proxy_fix import ProxyFix
from logger import logger, user_action_logger, rating_logger
from rate_limiter import rate_limiter
from homeassistant_api import ha_api
from youtube_api import get_youtube_api
from database import get_database
from history_tracker import HistoryTracker
from quota_guard import quota_guard
from startup_checks import run_startup_checks, check_home_assistant_api, check_youtube_api, check_database
from constants import FALSE_VALUES
from video_helpers import is_youtube_content
from metrics_tracker import metrics
from search_helpers import search_and_match_video_refactored
from cache_helpers import find_cached_video_refactored

app = Flask(__name__)

# Configure Flask to work behind Home Assistant ingress proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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

def search_and_match_video(ha_media: Dict[str, Any]) -> Optional[Dict]:
    """
    Find matching video using simplified search: exact title + duration.
    Uses the refactored implementation from search_helpers module.
    """
    yt_api = get_youtube_api()
    return search_and_match_video_refactored(ha_media, yt_api, db)


def find_cached_video(ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Attempt to reuse an existing DB record before querying YouTube.
    Uses the refactored implementation from cache_helpers module.
    """
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
    find_cached_video=find_cached_video,
    search_and_match_video=search_and_match_video,
    poll_interval=_history_poll_interval(),
    enabled=_history_tracker_enabled(),
)
history_tracker.start()
atexit.register(history_tracker.stop)


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
            find_cached_video,
            search_and_match_video,
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
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/')
def index() -> str:
    """Render the test interface page."""
    return render_template('index.html')

@app.route('/test/youtube')
def test_youtube() -> Response:
    """Test YouTube API connectivity and quota status."""
    try:
        yt_api = get_youtube_api()
        success, message = check_youtube_api(yt_api)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error testing YouTube API: {str(e)}"})

@app.route('/test/ha')
def test_ha() -> Response:
    """Test Home Assistant API connectivity."""
    success, message = check_home_assistant_api(ha_api)
    return jsonify({"success": success, "message": message})

@app.route('/test/db')
def test_db() -> Response:
    """Test database connectivity and integrity."""
    success, message = check_database(db)
    return jsonify({"success": success, "message": message})

@app.route('/api/unrated')
def get_unrated_songs() -> Response:
    """Get unrated songs for bulk rating interface."""
    try:
        from flask import request
        page = int(request.args.get('page', 1))
        limit = 50
        offset = (page - 1) * limit

        with db.lock:
            # Get total count of unrated songs
            cursor = db._conn.execute(
                "SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'none' AND pending_match = 0"
            )
            total_count = cursor.fetchone()['count']

            # Get unrated songs, sorted by play count (most played first)
            cursor = db._conn.execute(
                """
                SELECT yt_video_id, ha_title, yt_title, ha_artist, yt_channel, play_count
                FROM video_ratings
                WHERE rating = 'none' AND pending_match = 0
                ORDER BY play_count DESC, date_last_played DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            songs = cursor.fetchall()

        # Format results
        songs_list = []
        for song in songs:
            songs_list.append({
                'id': song['yt_video_id'],
                'title': song['yt_title'] or song['ha_title'] or 'Unknown',
                'artist': song['ha_artist'] or song['yt_channel'] or 'Unknown',
                'play_count': song['play_count'] or 0
            })

        total_pages = (total_count + limit - 1) // limit  # Ceiling division

        return jsonify({
            'success': True,
            'songs': songs_list,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count
        })
    except Exception as e:
        logger.error(f"Error fetching unrated songs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/thumbs_up', methods=['POST'])
def thumbs_up() -> Tuple[Response, int]:
    return rate_video('like')

@app.route('/thumbs_down', methods=['POST'])
def thumbs_down() -> Tuple[Response, int]:
    return rate_video('dislike')


@app.route('/health', methods=['GET'])
def health() -> Response:
    """Health check endpoint."""
    stats = rate_limiter.get_stats()
    guard_status = quota_guard.status()

    # Get health score from metrics
    health_score, warnings = metrics.get_health_score()
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
        "rate_limiter": stats,
        "quota_guard": guard_status,
    })


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

        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        return jsonify({'error': 'Failed to generate metrics', 'message': str(e)}), 500


if __name__ == '__main__':
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
