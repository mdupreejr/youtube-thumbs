"""
Rating routes for video rating functionality.
Extracted from app.py for better organization.
"""
import traceback
from typing import Tuple, Optional, Dict, Any
from flask import Blueprint, request, jsonify, Response, redirect
from flask_wtf.csrf import CSRFProtect
from logger import logger, user_action_logger, rating_logger
from helpers.response_helpers import error_response
from helpers.validation_helpers import validate_page_param, validate_youtube_video_id
from helpers.video_helpers import get_video_title, get_video_artist
from constants import MAX_BATCH_SIZE

bp = Blueprint('rating', __name__)

# Global references (set by init function)
_db = None
_rate_limiter = None
_quota_guard = None
_csrf = None
_ha_api = None
_get_youtube_api = None
_metrics = None
_is_youtube_content = None
_search_wrapper = None
_cache_wrapper = None

def init_rating_routes(
    database,
    rate_limiter,
    quota_guard,
    csrf: CSRFProtect,
    ha_api,
    get_youtube_api_func,
    metrics_tracker,
    is_youtube_content_func,
    search_wrapper_func,
    cache_wrapper_func
):
    """Initialize rating routes with dependencies."""
    global _db, _rate_limiter, _quota_guard, _csrf, _ha_api, _get_youtube_api, _metrics
    global _is_youtube_content, _search_wrapper, _cache_wrapper

    _db = database
    _rate_limiter = rate_limiter
    _quota_guard = quota_guard
    _csrf = csrf
    _ha_api = ha_api
    _get_youtube_api = get_youtube_api_func
    _metrics = metrics_tracker
    _is_youtube_content = is_youtube_content_func
    _search_wrapper = search_wrapper_func
    _cache_wrapper = cache_wrapper_func


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
    """Queue a rating request for later processing."""
    _db.enqueue_rating(yt_video_id, rating_type)
    if record_attempt:
        _db.mark_pending_rating(yt_video_id, False, reason)
    _db.record_rating_local(yt_video_id, rating_type)
    _metrics.record_rating(success=False, queued=True)
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

    should_skip, _ = _quota_guard.check_quota_or_skip("sync pending ratings")
    if should_skip:
        return

    # Get more pending ratings to process in batch
    pending_jobs = _db.list_pending_ratings(limit=batch_size)
    if not pending_jobs:
        return

    # Prepare batch ratings
    ratings_to_process = []
    for job in pending_jobs:
        should_skip, _ = _quota_guard.check_quota_or_skip("batch rating processing")
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
                _db.record_rating(video_id, rating)
                _db.mark_pending_rating(video_id, True)
                _metrics.record_rating(success=True, queued=False)
                rating_logger.info(f"{rating.upper()} | SYNCED | queued video {video_id}")
            else:
                _db.mark_pending_rating(video_id, False, "Batch rating failed")
                _metrics.record_rating(success=False, queued=False)
                logger.warning(f"Failed to sync rating for {video_id}")
    else:
        # Single rating, use regular method
        video_id, rating = ratings_to_process[0]
        media_info = f"queued video {video_id}"
        try:
            if yt_api.set_video_rating(video_id, rating):
                _db.record_rating(video_id, rating)
                _db.mark_pending_rating(video_id, True)
                rating_logger.info(f"{rating.upper()} | SYNCED | {media_info}")
            else:
                _db.mark_pending_rating(video_id, False, "YouTube API returned False")
        except Exception as exc:  # pragma: no cover - defensive
            _db.mark_pending_rating(video_id, False, str(exc))
            logger.error("Failed to sync pending rating for %s: %s", video_id, exc)


def rate_video(rating_type: str) -> Tuple[Response, int]:
    """
    Refactored handler for rating videos with improved organization.
    Delegates to helper functions for better maintainability.
    """
    from helpers.rating_helpers import (
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
    rate_limit_response = check_rate_limit(_rate_limiter, rating_type)
    if rate_limit_response:
        return rate_limit_response

    try:
        # Step 2: Get and validate current media
        ha_media, error_response = validate_current_media(_ha_api, rating_type)
        if error_response:
            return error_response

        # Step 3: Check if it's YouTube content
        youtube_check_response = check_youtube_content(ha_media, rating_type, _is_youtube_content)
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
        yt_video_id = update_database_for_rating(_db, video, ha_media)
        video_title = video['title']
        artist = ha_media.get('artist', '')
        media_info = format_media_info(video_title, artist)

        # Step 6: Check if already rated
        already_rated_response = check_already_rated(_db, yt_video_id, rating_type, media_info, video_title)
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
        yt_api = _get_youtube_api()
        _sync_pending_ratings(yt_api)

        return execute_rating(
            yt_api,
            yt_video_id,
            rating_type,
            media_info,
            video_title,
            _db,
            _queue_rating_request
        )

    except Exception as e:
        logger.error(f"Unexpected error in {rating_type} endpoint: {str(e)}")
        logger.debug(f"Traceback for {rating_type} error: {traceback.format_exc()}")
        rating_logger.info(f"{rating_type.upper()} | FAILED | Unexpected error: {str(e)}")
        return error_response("An unexpected error occurred while rating the video", 500)


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
        video_data = _db.get_video(video_id)
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
        _db.record_rating_local(video_id, rating_type)

        # Try to rate on YouTube (if not in quota block)
        should_skip, _ = _quota_guard.check_quota_or_skip("rate video on YouTube", video_id, rating_type)
        if should_skip:
            # Queue for later sync
            _db.enqueue_rating(video_id, rating_type)
            _metrics.record_rating(success=False, queued=True)
            rating_logger.info(f"{rating_type.upper()} | QUEUED | {title} | ID: {video_id} | Quota blocked")
            return jsonify({
                'success': True,
                'message': f'Queued {rating_type} (quota blocked)',
                'queued': True
            })

        # Rate on YouTube API
        yt_api = _get_youtube_api()
        if yt_api.set_video_rating(video_id, rating_type):
            _db.record_rating(video_id, rating_type)
            _metrics.record_rating(success=True, queued=False)
            rating_logger.info(f"{rating_type.upper()} | SUCCESS | {title} | ID: {video_id}")
            return jsonify({
                'success': True,
                'message': f'Rated as {rating_type}',
                'queued': False
            })
        else:
            # Failed but queued
            _db.enqueue_rating(video_id, rating_type)
            _metrics.record_rating(success=False, queued=True)
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
# DECORATORS
# ============================================================================

def require_rate_limit(f):
    """
    SECURITY: Decorator to apply rate limiting to API endpoints.
    Returns 429 Too Many Requests if rate limit is exceeded.
    """
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        allowed, reason = _rate_limiter.check_and_add_request()
        if not allowed:
            logger.warning(f"Rate limit exceeded for {request.remote_addr} on {request.path}")
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': reason}), 429
            return reason, 429
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# RATING ROUTES
# ============================================================================

@bp.route('/rate-song', methods=['POST'])
@require_rate_limit
def rate_song_form() -> Response:
    """
    Handle bulk rating form submissions from server-side rendered page.
    Processes the rating and redirects back to the rating tab.
    """
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


@bp.route('/api/unrated')
def get_unrated_songs() -> Response:
    """Get unrated songs for bulk rating interface."""
    logger.debug("=== /api/unrated endpoint called ===")
    logger.debug(f"Request args: {request.args}")

    try:
        page, error = validate_page_param(request.args)
        if error:
            return error

        logger.debug(f"Fetching page {page} of unrated songs")

        result = _db.get_unrated_videos(page=page, limit=50)
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


@bp.route('/api/rate/<video_id>/like', methods=['POST'])
@require_rate_limit
def rate_song_like(video_id: str) -> Response:
    """Rate a specific video as like (for bulk rating)."""
    return rate_song_direct(video_id, 'like')


@bp.route('/api/rate/<video_id>/dislike', methods=['POST'])
@require_rate_limit
def rate_song_dislike(video_id: str) -> Response:
    """Rate a specific video as dislike (for bulk rating)."""
    return rate_song_direct(video_id, 'dislike')


@bp.route('/thumbs_up', methods=['POST'])
@require_rate_limit
def thumbs_up() -> Tuple[Response, int]:
    """
    DEPRECATED: Legacy endpoint. Use /rate-song instead.
    CSRF protection exempt to allow external calls (e.g., Home Assistant automations).
    """
    # Note: CSRF exemption handled by app.py when registering blueprint
    return rate_video('like')


@bp.route('/thumbs_down', methods=['POST'])
@require_rate_limit
def thumbs_down() -> Tuple[Response, int]:
    """
    DEPRECATED: Legacy endpoint. Use /rate-song instead.
    CSRF protection exempt to allow external calls (e.g., Home Assistant automations).
    """
    # Note: CSRF exemption handled by app.py when registering blueprint
    return rate_video('dislike')
