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

    Note:
        location and recording_date may be None even for cached videos,
        as individual video fetches may not include recordingDetails to save quota.
        Only search_video_globally() fetches these fields.
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


def find_cached_video(db, ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
    if duration is None:
        # Can't do reliable matching without duration
        logger.debug("Cache miss for '%s' - no duration provided", title)
        metrics.record_cache_miss()
        return None

    if duration < 0:
        # Negative duration indicates data corruption or API bugs
        logger.warning("Cache miss for '%s' - negative duration (%s), possible data corruption", title, duration)
        metrics.record_cache_miss()
        return None

    artist = ha_media.get('artist')

    # Use optimized combined query (single database call instead of two)
    cached_video = db.find_cached_video_combined(title, duration, artist)
    if cached_video:
        # Determine which strategy found the match for metrics
        from .video_helpers import get_content_hash
        content_hash = get_content_hash(title, duration, artist)

        # More robust cache type detection
        if cached_video.get('ha_content_hash') == content_hash:
            cache_type = 'content_hash'
        elif cached_video.get('ha_content_hash') is not None:
            # Hash exists but doesn't match - likely title_duration match
            cache_type = 'title_duration'
        else:
            # No hash stored - either legacy data or pure title_duration match
            # Both cases should be reported as title_duration for metrics accuracy
            cache_type = 'title_duration'

        logger.info(
            "Cache hit (%s): '%s' (ID: %s)",
            cache_type,
            title,
            cached_video['yt_video_id']
        )
        metrics.record_cache_hit(cache_type)
        return build_video_result(cached_video, title)

    # No cache hit - let YouTube search handle it
    logger.debug("Cache miss for '%s' - will search YouTube", title)
    metrics.record_cache_miss()
    return None