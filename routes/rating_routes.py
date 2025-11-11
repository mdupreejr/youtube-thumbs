"""
Rating routes for video rating functionality.
Extracted from app.py for better organization.
"""
import re
import traceback
from typing import Tuple, Optional, Dict, Any
from flask import Blueprint, request, jsonify, Response, redirect, g
from flask_wtf.csrf import CSRFProtect
from logging_helper import LoggingHelper, LogType

# Get logger instances
logger = LoggingHelper.get_logger(LogType.MAIN)
user_action_logger = LoggingHelper.get_logger(LogType.USER_ACTION)
rating_logger = LoggingHelper.get_logger(LogType.RATING)
from helpers.response_helpers import error_response
from helpers.validation_helpers import validate_page_param, validate_youtube_video_id
from helpers.video_helpers import get_video_title, get_video_artist
from helpers.request_helpers import get_real_ip

bp = Blueprint('rating', __name__)


def safe_redirect(tab='rating', page='1'):
    """
    SECURITY: Create a safe redirect URL with validated parameters.

    This prevents open redirect vulnerabilities by:
    1. Validating ingress_path format
    2. Ensuring page is numeric
    3. Restricting tab to known values
    4. Always using relative URLs

    Args:
        tab: Tab to redirect to (default: 'rating')
        page: Page number (default: '1')

    Returns:
        Flask redirect response
    """
    # SECURITY: Validate and sanitize ingress path
    raw_ingress_path = g.ingress_path
    ingress_path = ''
    if raw_ingress_path:
        # Only allow alphanumeric, hyphens, underscores, and forward slashes
        if re.match(r'^/[a-zA-Z0-9/_-]*$', raw_ingress_path):
            ingress_path = raw_ingress_path
        else:
            logger.warning(f"Invalid ingress path in redirect rejected: {raw_ingress_path}")

    # SECURITY: Validate tab is one of allowed values
    allowed_tabs = {'rating', 'stats', 'logs', 'database', 'system'}
    if tab not in allowed_tabs:
        logger.warning(f"Invalid tab in redirect rejected: {tab}")
        tab = 'rating'

    # SECURITY: Validate page is numeric
    try:
        page_num = int(page)
        if page_num < 1:
            page = '1'
        else:
            page = str(page_num)
    except (ValueError, TypeError):
        logger.warning(f"Invalid page in redirect rejected: {page}")
        page = '1'

    # Build safe relative URL
    safe_url = f"{ingress_path}/?tab={tab}&page={page}"
    return redirect(safe_url)

# Global references (set by init function)
_db = None
_csrf = None
_ha_api = None
_get_youtube_api = None
_metrics = None
_is_youtube_content = None

def init_rating_routes(
    database,
    csrf: CSRFProtect,
    ha_api,
    get_youtube_api_func,
    metrics_tracker,
    is_youtube_content_func,
    search_wrapper_func,
    cache_wrapper_func
):
    """Initialize rating routes with dependencies."""
    global _db, _csrf, _ha_api, _get_youtube_api, _metrics
    global _is_youtube_content

    _db = database
    _csrf = csrf
    _ha_api = ha_api
    _get_youtube_api = get_youtube_api_func
    _metrics = metrics_tracker
    _is_youtube_content = is_youtube_content_func
    # Note: search_wrapper_func and cache_wrapper_func no longer needed
    # Cache checking moved to queue worker (v5.0.0)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_media_info(title: str, artist: str) -> str:
    """Format media information for logging."""
    return f'"{title}" by {artist}' if artist else f'"{title}"'


# ============================================================================
# RATING HANDLERS
# ============================================================================

def rate_video(rating_type: str) -> Tuple[Response, int]:
    """
    Simplified queue-based handler for rating videos.
    All logic (cache checking, searching, rating) happens in the queue worker.
    This endpoint just validates input and queues the request.

    Args:
        rating_type: Type of rating ('like' or 'dislike')
    """
    from helpers.rating_helpers import (
        validate_current_media,
        check_youtube_content
    )

    logger.info(f"{rating_type} request received")

    try:
        # Step 1: Get and validate current media
        ha_media, err_resp = validate_current_media(_ha_api, rating_type, error_response)
        if err_resp:
            return err_resp

        # Step 2: Check if it's YouTube content
        youtube_check_response = check_youtube_content(ha_media, rating_type, _is_youtube_content, error_response)
        if youtube_check_response:
            return youtube_check_response

        # Step 3: Queue search with rating callback
        # The queue worker will:
        # - Check cache first (skip search if found)
        # - Search if needed
        # - Check if already rated
        # - Apply the rating
        try:
            search_id = _db.enqueue_search(ha_media, callback_rating=rating_type)
            title = ha_media.get('title', 'Unknown')
            artist = ha_media.get('artist', '')
            media_info = format_media_info(title, artist)

            # v4.2.5: Check if search was skipped due to recent failure
            if search_id is None:
                user_action_logger.info(f"{rating_type.upper()} | {media_info} | SKIPPED (recent failed search)")
                logger.info(f"Skipping rating for '{title}' - recent failed search found")

                return jsonify({
                    'success': False,
                    'message': f'Video not found in recent search. Try again in 24 hours or add manually.',
                    'queued': False,
                    'search_queued': False,
                    'rating': rating_type,
                    'reason': 'recent_search_failure'
                }), 404

            user_action_logger.info(f"{rating_type.upper()} | {media_info} | QUEUED")
            logger.info(f"Queued rating for '{title}' (search_id: {search_id})")

            return jsonify({
                'success': True,
                'message': f'Rating queued. Will process shortly when quota available.',
                'queued': True,
                'rating': rating_type
            }), 202

        except Exception as e:
            # Queue full or other error
            logger.error(f"Failed to queue rating: {e}")
            return jsonify({
                'success': False,
                'message': f'Failed to queue rating: {str(e)}',
                'queued': False
            }), 503  # Service Unavailable

    except Exception as e:
        LoggingHelper.log_error_with_trace(f"Unexpected error in {rating_type} endpoint", e)
        rating_logger.info(f"{rating_type.upper()} | FAILED | Unexpected error: {str(e)}")
        return error_response("An unexpected error occurred while rating the video", 500)


def rate_song_direct(video_id: str, rating_type: str) -> Response:
    """
    Simplified queue-based direct rating by video ID.
    Used for bulk rating interface. All ratings are queued for background worker.
    Queue worker will check if already rated and handle the rating.
    """
    try:
        # SECURITY: Validate all inputs before expensive operations
        # 1. Validate rating type first (cheapest check)
        if rating_type not in ['like', 'dislike']:
            logger.warning(f"Invalid rating type: {rating_type} from {get_real_ip()}")
            return error_response('Invalid rating type')

        # 2. Validate video ID format (more expensive regex check)
        is_valid, error = validate_youtube_video_id(video_id)
        if not is_valid:
            logger.warning(f"Invalid video ID format in rate_song_direct: {video_id} from {get_real_ip()}")
            return error

        # 3. Only after all validation: perform expensive database lookup to verify video exists
        video_data = _db.get_video(video_id)
        if not video_data:
            return error_response('Video not found in database', 404)

        title = video_data.get('yt_title') or video_data.get('ha_title') or 'Unknown'

        # Queue rating for background worker
        # Worker will check if already rated and handle appropriately
        _db.enqueue_rating(video_id, rating_type)

        user_action_logger.info(f"{rating_type.upper()} | {title} | QUEUED")
        logger.info(f"Queued {rating_type} for {video_id} ({title})")

        return jsonify({
            'success': True,
            'message': f'Rating queued. Will sync to YouTube shortly when quota available.',
            'queued': True,
            'rating': rating_type
        })

    except Exception as e:
        LoggingHelper.log_error_with_trace(f"Error rating video {video_id}", e)
        return error_response('Failed to rate video', 500)


# ============================================================================
# RATING ROUTES
# ============================================================================

@bp.route('/rate-song', methods=['POST'])
def rate_song_form() -> Response:
    """
    Handle bulk rating form submissions from server-side rendered page.
    Processes the rating and redirects back to the rating tab.
    """
    try:
        # Get ingress path for proper redirect
        ingress_path = g.ingress_path

        song_id = request.form.get('song_id')
        rating = request.form.get('rating')
        page = request.form.get('page', '1')

        if not song_id or not rating:
            logger.error("Missing song_id or rating in form submission")
            return safe_redirect('rating', page)

        # SECURITY: Validate video ID format
        is_valid, _ = validate_youtube_video_id(song_id)
        if not is_valid:
            logger.warning(f"Invalid video ID format: {song_id} from {get_real_ip()}")
            return safe_redirect('rating', page)

        if rating not in ['like', 'dislike', 'skip']:
            logger.error(f"Invalid rating value: {rating}")
            return safe_redirect('rating', page)

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
        return safe_redirect('rating', page)

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error processing rating form", e)
        # Redirect back even on error
        try:
            page = request.form.get('page', '1')
        except:
            page = '1'
        return safe_redirect('rating', page)


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
        LoggingHelper.log_error_with_trace("ERROR in /api/unrated endpoint", e)
        return error_response('Failed to retrieve unrated videos', 500)


@bp.route('/api/rate/<video_id>/like', methods=['POST'])
def rate_song_like(video_id: str) -> Response:
    """Rate a specific video as like (for bulk rating). No rate limiting - just queueing."""
    return rate_song_direct(video_id, 'like')


@bp.route('/api/rate/<video_id>/dislike', methods=['POST'])
def rate_song_dislike(video_id: str) -> Response:
    """Rate a specific video as dislike (for bulk rating). No rate limiting - just queueing."""
    return rate_song_direct(video_id, 'dislike')


@bp.route('/thumbs_up', methods=['POST'])
def thumbs_up() -> Tuple[Response, int]:
    """
    Manual rating endpoint for currently playing media.
    Just queues the rating - no rate limiting needed.
    CSRF protection exempt to allow external calls (e.g., Home Assistant automations).
    """
    # Note: CSRF exemption handled by app.py when registering blueprint
    return rate_video('like')


@bp.route('/thumbs_down', methods=['POST'])
def thumbs_down() -> Tuple[Response, int]:
    """
    Manual rating endpoint for currently playing media.
    Just queues the rating - no rate limiting needed.
    CSRF protection exempt to allow external calls (e.g., Home Assistant automations).
    """
    # Note: CSRF exemption handled by app.py when registering blueprint
    return rate_video('dislike')
