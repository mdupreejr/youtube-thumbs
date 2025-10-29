"""
Cache helper functions for video lookup operations.
Extracted from app.py to improve code organization and maintainability.
"""
from typing import Dict, Any, Optional, List
from logger import logger
from metrics_tracker import metrics
from fuzzy_matcher import find_best_fuzzy_match


def build_video_result(video_data: Dict[str, Any], fallback_title: str) -> Dict[str, Any]:
    """
    Build a standardized video result dictionary from cached data.

    Args:
        video_data: Raw video data from database
        fallback_title: Title to use if no title found in video_data

    Returns:
        Standardized video result dictionary
    """
    return {
        'yt_video_id': video_data['yt_video_id'],
        'title': video_data.get('yt_title') or video_data.get('ha_title') or fallback_title,
        'channel': video_data.get('yt_channel'),
        'duration': video_data.get('yt_duration') or video_data.get('ha_duration')
    }


def check_content_hash_cache(db, title: str, duration: Optional[int], artist: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Check for a video match using content hash (title+duration+artist).

    Args:
        db: Database instance
        title: Video title
        duration: Video duration in seconds
        artist: Artist/channel name

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


def check_exact_title_cache(db, title: str) -> Optional[Dict[str, Any]]:
    """
    Check for a video match using exact title matching.

    Args:
        db: Database instance
        title: Video title

    Returns:
        Video result dict if found, None otherwise
    """
    exact_match = db.find_by_exact_ha_title(title)
    if exact_match:
        logger.info(
            "Using exact cached video ID %s for title '%s'",
            exact_match['yt_video_id'],
            title,
        )
        metrics.record_cache_hit('exact_title')
        return build_video_result(exact_match, title)
    return None


def try_fuzzy_matching(
    db,
    title: str,
    duration: Optional[int],
    artist: Optional[str],
    log_context: str = "fuzzy matching"
) -> Optional[Dict[str, Any]]:
    """
    Try to find a video match using fuzzy title matching.

    Args:
        db: Database instance
        title: Video title
        duration: Video duration in seconds
        artist: Artist/channel name
        log_context: Context string for logging

    Returns:
        Video result dict if found, None otherwise
    """
    logger.debug("%s for '%s'", log_context, title)
    fuzzy_matches = db.find_fuzzy_matches(title, threshold=85.0, limit=10)

    if not fuzzy_matches:
        return None

    best_match = find_best_fuzzy_match(
        title,
        fuzzy_matches,
        duration=duration,
        artist=artist,
        threshold=85.0,
        title_key='ha_title'
    )

    if best_match:
        logger.info(
            "Using fuzzy-matched cached video ID %s for title '%s' (matched: '%s')",
            best_match['yt_video_id'],
            title,
            best_match.get('ha_title') or best_match.get('yt_title')
        )
        metrics.record_cache_hit('fuzzy')
        metrics.record_fuzzy_match(
            title,
            best_match.get('ha_title') or best_match.get('yt_title'),
            85.0  # threshold used
        )
        return build_video_result(best_match, title)

    return None


def filter_cached_rows_by_criteria(
    cached_rows: List[Dict[str, Any]],
    title: str,
    duration: Optional[int],
    artist: Optional[str]
) -> Optional[Dict[str, Any]]:
    """
    Filter cached rows by duration and artist criteria.

    Args:
        cached_rows: List of cached video entries
        title: Video title for logging
        duration: Expected duration in seconds
        artist: Expected artist/channel name

    Returns:
        First matching video result dict, None if no matches
    """
    for row in cached_rows:
        # Check duration match (within 2 seconds tolerance)
        stored_duration = row.get('ha_duration') or row.get('yt_duration')
        if duration and stored_duration and abs(stored_duration - duration) > 2:
            continue

        # Check artist/channel match
        yt_channel = row.get('yt_channel')
        if artist and yt_channel and yt_channel.lower() != artist:
            continue

        # Found a match
        logger.info(
            "Using cached video ID %s for title '%s' (channel: %s)",
            row['yt_video_id'],
            title,
            yt_channel or 'unknown',
        )
        metrics.record_cache_hit('title_with_filters')
        return build_video_result(row, title)

    return None


def find_cached_video_refactored(db, ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Refactored version of find_cached_video with better organization.
    Attempts to find a cached video using various matching strategies.

    Args:
        db: Database instance
        ha_media: Home Assistant media information

    Returns:
        Video result dict if found, None otherwise
    """
    title = ha_media.get('title')
    if not title:
        return None

    duration = ha_media.get('duration')
    artist = (ha_media.get('artist') or '').lower() if ha_media.get('artist') else None

    # Strategy 1: Check content hash (most specific)
    result = check_content_hash_cache(db, title, duration, artist)
    if result:
        return result

    # Strategy 2: Check exact title match
    result = check_exact_title_cache(db, title)
    if result:
        return result

    # Strategy 3: Check title matches with filtering
    cached_rows = db.find_by_title(title)
    if cached_rows:
        result = filter_cached_rows_by_criteria(cached_rows, title, duration, artist)
        if result:
            return result

        # Strategy 4: Try fuzzy matching since exact matches were filtered out
        result = try_fuzzy_matching(
            db, title, duration, artist,
            log_context="Exact title matches filtered out, trying fuzzy matching"
        )
        if result:
            return result
    else:
        # Strategy 5: No exact matches, try fuzzy matching
        result = try_fuzzy_matching(
            db, title, duration, artist,
            log_context="No exact title match found, trying fuzzy matching"
        )
        if result:
            return result

        # No matches found
        metrics.record_cache_miss()

    return None