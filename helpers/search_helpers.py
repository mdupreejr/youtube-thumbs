"""
Helper functions for video search operations.
Extracted from app.py to improve code organization and reduce function complexity.
"""
from typing import Optional, Dict, Any, List
from logger import logger
from metrics_tracker import metrics


def validate_search_requirements(ha_media: Dict[str, Any]) -> Optional[tuple]:
    """
    Validate that required fields for searching are present.

    Args:
        ha_media: Media information from Home Assistant

    Returns:
        Tuple of (title, duration) if valid, None otherwise
    """
    title = ha_media.get('title')
    duration = ha_media.get('duration')

    if not title:
        logger.error("Missing title in media info")
        return None

    if not duration:
        logger.error("Missing duration in media info")
        return None

    return title, duration


def search_youtube_for_video(
    yt_api,
    title: str,
    duration: int,
    artist: str = None,
    return_api_response: bool = False
):
    """
    Search YouTube for matching videos with exact duration (+1 second).

    Args:
        yt_api: YouTube API instance
        title: Video title
        duration: Video duration (HA duration, YouTube will be +1)
        artist: Artist/channel name (improves search accuracy for generic titles)
        return_api_response: If True, return tuple of (candidates, api_debug_data)

    Returns:
        If return_api_response=False: List of candidate videos or None if not found
        If return_api_response=True: Tuple of (candidates or None, api_debug_data dict)
    """
    logger.debug(f"Searching YouTube: title='{title}', artist='{artist}', expected YT duration={duration + 1}s")

    if return_api_response:
        result = yt_api.search_video_globally(title, duration, artist, return_api_response=True)
        candidates, api_debug_data = result if result else (None, {})
    else:
        candidates = yt_api.search_video_globally(title, duration, artist)
        api_debug_data = None

    if not candidates:
        logger.error(
            "No videos found with exact duration match | Title: '%s' | Expected YT duration: %ss",
            title,
            duration + 1
        )
        metrics.record_failed_search(title, None, reason='not_found')
        return (None, api_debug_data) if return_api_response else None

    return (candidates, api_debug_data) if return_api_response else candidates


def select_best_match(
    candidates: List[Dict],
    title: str
) -> Optional[Dict]:
    """
    Select the best match from candidates (just take the first one).
    Since we already filtered by exact duration and searched with the exact title,
    the first result from YouTube is usually the best match.

    Args:
        candidates: List of candidate videos from YouTube (already duration-filtered)
        title: Original title from HA

    Returns:
        First matching video or None if no candidates
    """
    if not candidates:
        return None

    # Just take the first match (YouTube's top result with correct duration)
    video = candidates[0]

    # Log if we have multiple candidates
    if len(candidates) > 1:
        logger.info(
            f"Multiple candidates found ({len(candidates)}), using first: "
            f"YT='{video['title']}' by {video.get('channel')}"
        )

    return video


def search_and_match_video(
    ha_media: Dict[str, Any],
    yt_api,
    db,
    return_api_response: bool = False
):
    """
    Simplified video search: find YouTube video by exact title and duration (+1s).
    Now with opportunistic caching of all search results!

    Args:
        ha_media: Media information from Home Assistant (must have channel='YouTube')
        yt_api: YouTube API instance
        db: Database instance
        return_api_response: If True, return tuple of (video, api_debug_data)

    Returns:
        If return_api_response=False: video_dict or None
        If return_api_response=True: Tuple of (video_dict or None, api_debug_data dict or None)
    """
    # Step 1: Validate requirements
    validation_result = validate_search_requirements(ha_media)
    if not validation_result:
        return (None, None) if return_api_response else None
    title, duration = validation_result

    # Step 2: Check opportunistic search cache FIRST (0 API cost!)
    cached_result = db.find_in_search_cache(title, duration + 1, tolerance=2)  # +1 for YouTube duration
    if cached_result:
        logger.info(f"Opportunistic cache HIT: '{title}' → {cached_result['yt_video_id']} (saved 101 quota units!)")
        metrics.record_cache_hit('search_results')
        # v4.0.46: Return ALL cached video fields, not just 5
        cached_video = {
            'yt_video_id': cached_result['yt_video_id'],
            'title': cached_result['yt_title'],
            'channel': cached_result['yt_channel'],
            'channel_id': cached_result['yt_channel_id'],
            'duration': cached_result['yt_duration'],
            'description': cached_result.get('yt_description'),
            'published_at': cached_result.get('yt_published_at'),
            'category_id': cached_result.get('yt_category_id'),
            'live_broadcast': cached_result.get('yt_live_broadcast'),
            'location': cached_result.get('yt_location'),
            'recording_date': cached_result.get('yt_recording_date')
        }
        # No API call made, so no debug data
        return (cached_video, {'cache_hit': True}) if return_api_response else cached_video

    # v4.0.11: Removed should_skip_search() - not-found cache disabled, always search
    # Step 3: Search YouTube (with exact duration matching)
    # v4.0.46: Caching now happens inside search_youtube_for_video (youtube_api.py)
    #          to cache ALL fetched videos, not just duration-matched candidates
    # v4.0.68: Pass artist to improve search accuracy for generic titles
    # v4.0.71: Use album (channel name) as fallback when artist is generic/missing
    # v4.2.3: Use BOTH artist and album when both are available and useful
    artist = ha_media.get('artist')
    album = ha_media.get('album')

    # Build comprehensive search context from all available HA metadata
    search_artist = None
    if artist and artist not in ['Unknown', 'YouTube', None, '']:
        search_artist = artist
        # Also append album if it's different and useful
        if album and album not in ['Unknown', 'YouTube', None, ''] and album.lower() != artist.lower():
            search_artist = f"{artist} {album}"
            logger.debug(f"Using both artist '{artist}' and album '{album}' for enhanced search")
    elif album and album not in ['Unknown', 'YouTube', None, '']:
        # Fallback to album if artist is generic/missing
        search_artist = album
        logger.debug(f"Using album '{album}' as artist for search (original artist was generic/missing)")

    if return_api_response:
        result = search_youtube_for_video(yt_api, title, duration, search_artist, return_api_response=True)
        candidates, api_debug_data = result if result else (None, {})
    else:
        candidates = search_youtube_for_video(yt_api, title, duration, search_artist)
        api_debug_data = None

    if not candidates:
        # v4.0.11: No longer recording not-found - queue table tracks failed searches
        return (None, api_debug_data) if return_api_response else None

    # Step 4: Select best match (just take first result)
    video = select_best_match(candidates, title)
    if not video:
        # v4.0.11: No longer recording not-found - queue table tracks failed searches
        return (None, api_debug_data) if return_api_response else None

    # Step 7: Log success
    logger.info(
        f"MATCHED: HA='{title}' ({duration}s) → YT='{video['title']}' ({video.get('duration', 0)}s) | "
        f"Channel: {video.get('channel')} | ID: {video['yt_video_id']}"
    )

    return (video, api_debug_data) if return_api_response else video