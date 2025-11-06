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


def should_skip_search(db, title: str, duration: int, artist: Optional[str] = None) -> bool:
    """
    Check if search should be skipped due to recent failures or quota blocking.

    Args:
        db: Database instance
        title: Video title
        duration: Video duration in seconds
        artist: Artist name (optional, used for accurate not_found cache matching)

    Returns:
        True if search should be skipped, False otherwise
    """
    # Check if this search recently failed (negative result cache)
    if db.is_recently_not_found(title, artist, duration):
        metrics.record_not_found_cache_hit(title)
        logger.debug("Skipping search for '%s' - recently marked as not found", title)
        return True

    # No quota checks needed - if quota is exceeded, search will raise QuotaExceededError
    return False


def search_youtube_for_video(
    yt_api,
    title: str,
    duration: int
) -> Optional[List[Dict]]:
    """
    Search YouTube for matching videos with exact duration (+1 second).

    Args:
        yt_api: YouTube API instance
        title: Video title
        duration: Video duration (HA duration, YouTube will be +1)

    Returns:
        List of candidate videos or None if not found
    """
    logger.debug(f"Searching YouTube: title='{title}', expected YT duration={duration + 1}s")
    candidates = yt_api.search_video_globally(title, duration, None)

    if not candidates:
        logger.error(
            "No videos found with exact duration match | Title: '%s' | Expected YT duration: %ss",
            title,
            duration + 1
        )
        metrics.record_failed_search(title, None, reason='not_found')
        return None

    return candidates


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


def record_failed_search(
    db,
    title: str,
    duration: int,
    artist: Optional[str] = None
) -> None:
    """
    Record a failed search to prevent repeated API calls.

    Args:
        db: Database instance
        title: Video title
        duration: Video duration
        artist: Artist name (optional, used for accurate cache matching)
    """
    db.record_not_found(title, artist, duration, title)


def search_and_match_video(
    ha_media: Dict[str, Any],
    yt_api,
    db
) -> Optional[Dict]:
    """
    Simplified video search: find YouTube video by exact title and duration (+1s).
    Now with opportunistic caching of all search results!

    Args:
        ha_media: Media information from Home Assistant (must have channel='YouTube')
        yt_api: YouTube API instance
        db: Database instance

    Returns:
        video_dict or None
    """
    # Step 1: Validate requirements
    validation_result = validate_search_requirements(ha_media)
    if not validation_result:
        return None
    title, duration = validation_result

    # Step 2: Check opportunistic search cache FIRST (0 API cost!)
    cached_result = db.find_in_search_cache(title, duration + 1, tolerance=2)  # +1 for YouTube duration
    if cached_result:
        logger.info(f"Opportunistic cache HIT: '{title}' → {cached_result['yt_video_id']} (saved 101 quota units!)")
        metrics.record_cache_hit('search_results')
        # Return in same format as YouTube search results
        return {
            'yt_video_id': cached_result['yt_video_id'],
            'title': cached_result['yt_title'],
            'channel': cached_result['yt_channel'],
            'channel_id': cached_result['yt_channel_id'],
            'duration': cached_result['yt_duration']
        }

    # Step 3: Check if should skip search
    artist = ha_media.get('artist')
    if should_skip_search(db, title, duration, artist):
        return None

    # Step 4: Search YouTube (with exact duration matching)
    candidates = search_youtube_for_video(yt_api, title, duration)
    if not candidates:
        record_failed_search(db, title, duration, artist)
        return None

    # Step 5: Opportunistically cache ALL search results (not just the match!)
    # This costs 0 extra API units and might help with future searches
    try:
        cached_count = db.cache_search_results(candidates, ttl_days=30)
        logger.debug(f"Cached {cached_count} videos from search results for future lookups")
    except Exception as exc:
        logger.warning(f"Failed to cache search results: {exc}")

    # Step 6: Select best match (just take first result)
    video = select_best_match(candidates, title)
    if not video:
        record_failed_search(db, title, duration, artist)
        return None

    # Step 7: Log success
    logger.info(
        f"MATCHED: HA='{title}' ({duration}s) → YT='{video['title']}' ({video.get('duration', 0)}s) | "
        f"Channel: {video.get('channel')} | ID: {video['yt_video_id']}"
    )

    return video