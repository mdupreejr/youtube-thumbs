"""
Simplified cache helper functions for video lookup operations.
"""
from typing import Dict, Any, Optional
from logger import logger
from metrics_tracker import metrics


def build_video_result(video_data: Dict[str, Any], fallback_title: str) -> Dict[str, Any]:
    """
    Build a standardized video result dictionary from cached data.

    Args:
        video_data: Raw video data from database
        fallback_title: Title to use if no title found in video_data

    Returns:
        Standardized video result dictionary with all YouTube metadata
    """
    return {
        'yt_video_id': video_data['yt_video_id'],
        'title': video_data.get('yt_title') or video_data.get('ha_title') or fallback_title,
        'channel': video_data.get('yt_channel'),
        'channel_id': video_data.get('yt_channel_id'),
        'description': video_data.get('yt_description'),
        'published_at': video_data.get('yt_published_at'),
        'category_id': video_data.get('yt_category_id'),
        'live_broadcast': video_data.get('yt_live_broadcast'),
        'location': video_data.get('yt_location'),
        'recording_date': video_data.get('yt_recording_date'),
        'duration': video_data.get('yt_duration') or video_data.get('ha_duration')
    }


def check_content_hash_cache(db, title: str, duration: Optional[int], artist: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Check for a video match using content hash (title+duration+artist).

    Args:
        db: Database instance
        title: Video title
        duration: Video duration in seconds
        artist: Artist name from Home Assistant

    Returns:
        Video result dict if found, None otherwise
    """
    hash_match = db.find_by_content_hash(title, duration, artist)
    if hash_match:
        logger.info(
            "Using hash-cached video ID %s for title '%s' (duration %s)",
            hash_match['yt_video_id'],
            title,
            duration,
        )
        metrics.record_cache_hit('content_hash')
        return build_video_result(hash_match, title)
    return None


def find_cached_video_refactored(db, ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Simplified cache lookup: check exact matches only.
    If not found, return None and let YouTube search handle it.

    Args:
        db: Database instance
        ha_media: Home Assistant media information (title, duration, channel)

    Returns:
        Video result dict if found in cache, None otherwise
    """
    title = ha_media.get('title')
    if not title:
        return None

    duration = ha_media.get('duration')
    artist = ha_media.get('artist')

    # Strategy 1: Check content hash (title + duration + artist)
    result = check_content_hash_cache(db, title, duration, artist)
    if result:
        return result

    # Strategy 2: Check exact title + duration match
    if duration:
        # Find by title and check duration matches exactly (YouTube = HA + 1)
        exact_match = db.find_by_title_and_duration(title, duration)
        if exact_match:
            logger.info(
                "Cache hit: exact title+duration match for '%s' (ID: %s)",
                title,
                exact_match['yt_video_id']
            )
            metrics.record_cache_hit('title_duration')
            return build_video_result(exact_match, title)

    # No cache hit - let YouTube search handle it
    logger.debug("Cache miss for '%s' - will search YouTube", title)
    metrics.record_cache_miss()
    return None