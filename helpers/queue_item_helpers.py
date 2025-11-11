"""
Queue item detail extraction helpers.

Extracted from routes/logs_routes.py to eliminate code duplication.
"""

from typing import Dict, Any, Optional
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)


def extract_queue_item_details(queue_item: Dict[str, Any], db) -> Optional[Dict[str, Any]]:
    """
    Extract full details from a queue item for display.

    Args:
        queue_item: Queue item dictionary from database
        db: Database instance for lookups

    Returns:
        Dictionary with formatted details, or None if item type is invalid
    """
    if not queue_item:
        return None

    payload = queue_item.get('payload', {})
    item_type = queue_item['type']

    if item_type == 'rating':
        return _extract_rating_details(queue_item, payload, db)
    elif item_type == 'search':
        return _extract_search_details(queue_item, payload, db)
    else:
        logger.error(f"Invalid queue item type: {item_type}")
        return None


def _extract_rating_details(queue_item: Dict[str, Any], payload: Dict[str, Any], db) -> Dict[str, Any]:
    """Extract details for a rating queue item."""
    # Extract rating info from payload
    yt_video_id = payload.get('yt_video_id')
    rating = payload.get('rating')

    # Get video details if available
    video = db.get_video(yt_video_id) if yt_video_id else None

    # Format the response with all available details
    details = {
        'type': 'rating',
        'queue_id': queue_item.get('id'),
        'yt_video_id': yt_video_id,
        'ha_title': video.get('ha_title', 'Unknown') if video else 'Unknown',
        'ha_artist': video.get('ha_artist', 'Unknown') if video else 'Unknown',
        'yt_title': video.get('yt_title') if video else None,
        'yt_channel': video.get('yt_channel') if video else None,
        'yt_duration': video.get('yt_duration') if video else None,
        'ha_duration': video.get('ha_duration') if video else None,
        'operation': f"Rate as {rating}",
        'rating': rating,
        'requested_at': queue_item.get('requested_at'),
        'attempts': queue_item.get('attempts', 0),
        'last_attempt': queue_item.get('last_attempt'),
        'last_error': queue_item.get('last_error'),
        'status': queue_item.get('status'),
        'completed_at': queue_item.get('completed_at'),
        'current_rating': video.get('rating') if video else None,
        'play_count': video.get('play_count', 0) if video else 0,
        'date_added': video.get('date_added') if video else None,
        'date_last_played': video.get('date_last_played') if video else None,
        'api_response_data': queue_item.get('api_response_data'),  # v4.0.64: YouTube API debug data
        'payload': payload
    }

    return details


def _extract_search_details(queue_item: Dict[str, Any], payload: Dict[str, Any], db) -> Dict[str, Any]:
    """Extract details for a search queue item."""
    # Extract search info from payload
    ha_media = payload
    callback_rating = ha_media.get('callback_rating')

    # Try to find if search found a video to get YouTube metadata
    found_video = None
    if queue_item.get('status') == 'completed':
        # Search was completed, try to find the video by title+artist
        try:
            found_video = db.find_by_title_and_duration(
                ha_media.get('ha_title'),
                ha_media.get('ha_duration')
            )
            if not found_video and ha_media.get('ha_artist'):
                # Try content hash lookup as fallback
                found_video = db.find_by_content_hash(
                    ha_media.get('ha_title'),
                    ha_media.get('ha_duration'),
                    ha_media.get('ha_artist')
                )
        except Exception as e:
            logger.debug(f"Could not find completed search result for queue {queue_item.get('id')}: {e}")

    details = {
        'type': 'search',
        'queue_id': queue_item.get('id'),
        'ha_title': ha_media.get('ha_title', 'Unknown'),
        'ha_artist': ha_media.get('ha_artist', 'Unknown'),
        'ha_album': ha_media.get('ha_album'),
        'ha_duration': ha_media.get('ha_duration'),
        'ha_app_name': ha_media.get('ha_app_name'),
        'operation': 'Search for YouTube match',
        'callback_rating': callback_rating,
        'status': queue_item.get('status'),
        'requested_at': queue_item.get('requested_at'),
        'attempts': queue_item.get('attempts', 0),
        'last_attempt': queue_item.get('last_attempt'),
        'last_error': queue_item.get('last_error'),
        'completed_at': queue_item.get('completed_at'),
        'api_response_data': queue_item.get('api_response_data'),  # v4.0.64: YouTube API debug data
        'payload': payload,
        # Add YouTube metadata if found
        'yt_video_id': found_video.get('yt_video_id') if found_video else None,
        'yt_title': found_video.get('yt_title') if found_video else None,
        'yt_channel': found_video.get('yt_channel') if found_video else None,
        'yt_duration': found_video.get('yt_duration') if found_video else None,
        'yt_url': found_video.get('yt_url') if found_video else None
    }

    return details
