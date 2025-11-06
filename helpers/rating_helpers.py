"""
Helper functions for video rating operations.
Extracted from app.py to improve code organization and reduce function complexity.
"""
from typing import Tuple, Optional, Dict, Any
from flask import jsonify, Response
from logger import logger, user_action_logger, rating_logger
from metrics_tracker import metrics
from .video_helpers import prepare_video_upsert
from .response_helpers import error_response, success_response


def _get_quota_guard():
    """Lazy import of quota_guard to avoid circular dependency."""
    from quota_manager import get_quota_manager
    return get_quota_manager()


def check_rate_limit(rate_limiter, rating_type: str) -> Optional[Tuple[Response, int]]:
    """
    Check rate limiting and return error response if limit exceeded.

    Args:
        rate_limiter: Rate limiter instance
        rating_type: Type of rating (like/dislike)

    Returns:
        Error response tuple if rate limited, None otherwise
    """
    allowed, reason = rate_limiter.check_and_add_request()
    if not allowed:
        logger.warning(f"Request blocked: {reason}")
        rating_logger.info(f"{rating_type.upper()} | BLOCKED | Reason: {reason}")
        return error_response(reason, 429)
    return None


def validate_current_media(ha_api, rating_type: str) -> Tuple[Optional[Dict], Optional[Tuple[Response, int]]]:
    """
    Get and validate current media from Home Assistant.

    Args:
        ha_api: Home Assistant API instance
        rating_type: Type of rating for logging

    Returns:
        Tuple of (media_dict, error_response)
        - media_dict is None if error
        - error_response is None if success
    """
    ha_media = ha_api.get_current_media()
    if not ha_media:
        logger.error(f"No media currently playing | Context: rate_video ({rating_type})")
        rating_logger.info(f"{rating_type.upper()} | FAILED | No media currently playing")
        err_response = error_response("No media currently playing")
        return None, err_response
    return ha_media, None


def check_youtube_content(ha_media: Dict, rating_type: str, is_youtube_content_func) -> Optional[Tuple[Response, int]]:
    """
    Check if media is YouTube content and return error if not.

    Args:
        ha_media: Media information from Home Assistant
        rating_type: Type of rating for logging
        is_youtube_content_func: Function to check if content is from YouTube

    Returns:
        Error response tuple if not YouTube content, None otherwise
    """
    if not is_youtube_content_func(ha_media):
        title = ha_media.get('title', 'unknown')
        app_name = ha_media.get('app_name', 'unknown')
        logger.info(f"Skipping non-YouTube content: '{title}' from app '{app_name}'")
        rating_logger.info(f"{rating_type.upper()} | SKIPPED | Non-YouTube content from '{app_name}'")
        return error_response(f"Not YouTube content (app: {app_name})")
    return None


def find_or_search_video(
    ha_media: Dict,
    find_cached_func,
    search_and_match_func,
    rating_type: str,
    format_media_info_func
) -> Tuple[Optional[Dict], Optional[Tuple[Response, int]]]:
    """
    Find video in cache or search for it.

    Args:
        ha_media: Media information from Home Assistant
        find_cached_func: Function to find cached video
        search_and_match_func: Function to search and match video
        rating_type: Type of rating for logging
        format_media_info_func: Function to format media info for logging

    Returns:
        Tuple of (video_dict, error_response)
    """
    # Try to find in cache first
    video = find_cached_func(ha_media)

    if not video:
        # Check if quota is blocked
        should_skip, _ = _get_quota_guard().check_quota_or_skip("locate video for rating", rating_type)
        if should_skip:
            # Can't search now due to quota, but we can queue this media for later matching
            # This allows the user to rate songs even when quota is exhausted
            from database import get_database
            db = get_database()

            # Add to pending videos so it can be matched when quota is restored
            db.upsert_pending_media(ha_media, reason='quota_exceeded')

            title = ha_media.get('title', 'Unknown')
            artist = ha_media.get('artist', 'Unknown')
            media_info = format_media_info_func(title, artist)

            logger.info(
                "Quota blocked - cannot search for video now. Added to pending: %s",
                media_info
            )
            rating_logger.info(f"{rating_type.upper()} | PENDING | {media_info} | Quota blocked, queued for later matching")

            error_response = (
                jsonify({
                    "success": False,
                    "error": "Quota exceeded - video will be matched and rated when quota is restored",
                    "queued_for_matching": True,
                    "pending_reason": "quota_exceeded"
                }),
                503,
            )
            return None, error_response

        # Search for video
        video = search_and_match_func(ha_media)

    # Still not found
    if not video:
        title = ha_media.get('title', 'unknown')
        artist = ha_media.get('artist', '')
        media_info = format_media_info_func(title, artist)
        user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: N/A | FAILED - Video not found")
        rating_logger.info(f"{rating_type.upper()} | FAILED | {media_info} | ID: N/A | Reason: Video not found")
        logger.error(f"Video not found | Context: rate_video ({rating_type}) | Media: {media_info}")
        err_response = error_response("Video not found", 404)
        return None, err_response

    return video, None


def update_database_for_rating(db, video: Dict, ha_media: Dict) -> str:
    """
    Update database with video information for rating.

    Note: Does NOT increment play count - that's handled by the history tracker.
    Rating a video is separate from playing it.

    Args:
        db: Database instance
        video: Video information
        ha_media: Media information from Home Assistant

    Returns:
        YouTube video ID
    """
    yt_video_id = video['yt_video_id']

    # Prepare and upsert video data
    video_data = prepare_video_upsert(video, ha_media, source='ha_live')
    db.upsert_video(video_data)
    # DO NOT call record_play() here - history tracker handles play counting

    return yt_video_id


def check_already_rated(db, yt_video_id: str, rating_type: str, media_info: str, video_title: str) -> Optional[Tuple[Response, int]]:
    """
    Check if video is already rated with the same rating.

    Args:
        db: Database instance
        yt_video_id: YouTube video ID
        rating_type: Type of rating (like/dislike)
        media_info: Formatted media info for logging
        video_title: Video title for response

    Returns:
        Success response if already rated, None otherwise
    """
    cached_video_row = db.get_video(yt_video_id)
    cached_rating = (cached_video_row or {}).get('rating')

    if cached_rating == rating_type:
        logger.info(f"Video {yt_video_id} already rated '{rating_type}' (cache)")
        user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {yt_video_id} | ALREADY_RATED_CACHE")
        rating_logger.info(f"{rating_type.upper()} | ALREADY_RATED | {media_info} | ID: {yt_video_id} | Source: cache")
        db.record_rating(yt_video_id, rating_type)
        return jsonify({
            "success": True,
            "message": f"Already rated {rating_type}",
            "video_id": yt_video_id,
            "title": video_title
        }), 200

    return None


def handle_quota_blocked_rating(
    yt_video_id: str,
    rating_type: str,
    media_info: str,
    queue_rating_func
) -> Optional[Tuple[Response, int]]:
    """
    Handle rating when quota is blocked.

    Args:
        yt_video_id: YouTube video ID
        rating_type: Type of rating
        media_info: Formatted media info for logging
        queue_rating_func: Function to queue the rating

    Returns:
        Response tuple if quota blocked, None otherwise
    """
    should_skip, _ = _get_quota_guard().check_quota_or_skip("rate video", yt_video_id, rating_type)
    if should_skip:
        guard_status = _get_quota_guard().status()
        logger.warning(
            "Queuing %s request for %s due to quota cooldown",
            rating_type,
            yt_video_id,
        )
        return queue_rating_func(
            yt_video_id,
            rating_type,
            media_info,
            guard_status.get('message', 'quota cooldown'),
        )
    return None


def execute_rating(
    yt_api,
    yt_video_id: str,
    rating_type: str,
    media_info: str,
    video_title: str,
    db,
    queue_rating_func
) -> Tuple[Response, int]:
    """
    Execute the actual rating via YouTube API.

    Args:
        yt_api: YouTube API instance
        yt_video_id: YouTube video ID
        rating_type: Type of rating
        media_info: Formatted media info for logging
        video_title: Video title for response
        db: Database instance
        queue_rating_func: Function to queue rating on failure

    Returns:
        Response tuple
    """
    # Enqueue the rating first to populate yt_rating_* columns
    db.enqueue_rating(yt_video_id, rating_type)

    # Check quota one more time before attempting rating
    # (quota might have been exhausted during _sync_pending_ratings)
    should_skip, _ = _get_quota_guard().check_quota_or_skip("execute rating", yt_video_id, rating_type)
    if should_skip:
        logger.info(f"Quota blocked during execute_rating for {yt_video_id}, already queued")
        db.mark_pending_rating(yt_video_id, False, "Quota blocked")
        return queue_rating_func(
            yt_video_id,
            rating_type,
            media_info,
            "Quota blocked",
            record_attempt=False  # Already marked as failed above
        )

    if yt_api.set_video_rating(yt_video_id, rating_type):
        logger.info(f"Successfully rated video {yt_video_id} {rating_type}")
        user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {yt_video_id} | SUCCESS")
        rating_logger.info(f"{rating_type.upper()} | SUCCESS | {media_info} | ID: {yt_video_id}")
        db.record_rating(yt_video_id, rating_type)
        db.mark_pending_rating(yt_video_id, True)
        metrics.record_rating(success=True, queued=False)
        return jsonify({
            "success": True,
            "message": f"Successfully rated {rating_type}",
            "video_id": yt_video_id,
            "title": video_title
        }), 200

    # Rating failed
    # nosec B605 - yt_video_id is a public YouTube video ID, not sensitive data
    logger.error(
        "YouTube API returned failure for %s request (video %s). Queuing for retry.",
        rating_type,
        yt_video_id,
    )
    # Mark as failed (increment attempts)
    db.mark_pending_rating(yt_video_id, False, "YouTube API error")
    return queue_rating_func(
        yt_video_id,
        rating_type,
        media_info,
        "YouTube API error",
        record_attempt=False  # Already marked as failed above
    )