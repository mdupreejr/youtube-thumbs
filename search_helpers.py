"""
Helper functions for video search operations.
Extracted from app.py to improve code organization and reduce function complexity.
"""
from typing import Optional, Dict, Any, List
from logger import logger
from quota_guard import quota_guard
from metrics_tracker import metrics


def validate_search_requirements(ha_media: Dict[str, Any]) -> Optional[tuple]:
    """
    Validate that required fields for searching are present.

    Args:
        ha_media: Media information from Home Assistant

    Returns:
        Tuple of (title, artist, duration) if valid, None otherwise
    """
    title = ha_media.get('title')
    artist = ha_media.get('artist')
    duration = ha_media.get('duration')

    if not title:
        logger.error("Missing title in media info")
        return None

    if not duration:
        logger.error("Missing duration in media info")
        return None

    return title, artist, duration


def should_skip_search(db, title: str, artist: Optional[str], duration: int) -> bool:
    """
    Check if search should be skipped due to recent failures or quota blocking.

    Args:
        db: Database instance
        title: Video title
        artist: Artist/channel name
        duration: Video duration in seconds

    Returns:
        True if search should be skipped, False otherwise
    """
    # Check if this search recently failed (negative result cache)
    if db.is_recently_not_found(title, artist, duration):
        metrics.record_not_found_cache_hit(title)
        logger.info("Skipping search for '%s' - recently marked as not found", title)
        return True

    # Check if quota is blocked
    if quota_guard.is_blocked():
        logger.info(
            "Skipping YouTube search for '%s' due to quota cooldown: %s",
            title,
            quota_guard.describe_block(),
        )
        return True

    return False


def search_youtube_for_video(
    yt_api,
    title: str,
    duration: int,
    artist: Optional[str]
) -> Optional[List[Dict]]:
    """
    Search YouTube for matching videos.

    Args:
        yt_api: YouTube API instance
        title: Video title
        duration: Video duration
        artist: Artist/channel name

    Returns:
        List of candidate videos or None if not found
    """
    candidates = yt_api.search_video_globally(title, duration, artist)

    if not candidates:
        logger.error(
            "No videos found matching title and duration | Title: '%s' | Duration: %ss",
            title,
            duration,
        )
        metrics.record_failed_search(title, artist, reason='not_found')
        return None

    return candidates


def filter_and_select_best_match(
    candidates: List[Dict],
    title: str,
    artist: Optional[str],
    matcher
) -> Optional[Dict]:
    """
    Filter candidates by title matching and select the best match.

    Args:
        candidates: List of candidate videos from YouTube
        title: Original title to match
        artist: Artist/channel name
        matcher: Matcher instance for title filtering

    Returns:
        Best matching video or None if no matches
    """
    # Filter candidates by title text matching
    matches = matcher.filter_candidates_by_title(title, candidates, artist)

    if not matches:
        logger.error(
            f"Title matching failed: HA='{title}' did not match any of {len(candidates)} YouTube results"
        )
        return None

    # Select best match (first one = highest search relevance)
    video = matches[0]
    match_score = video.pop('_match_score', None)

    # Log multiple matches if present
    if len(matches) > 1:
        logger.info(f"Multiple matches ({len(matches)} found):")
        for i, match in enumerate(matches[:3]):  # Show top 3
            status = "[SELECTED]" if i == 0 else "[REJECTED]"
            match_duration = match.get('duration', 0)
            duration_diff = abs(match_duration - (video.get('duration', 0))) if i > 0 else 0
            logger.info(
                f"  #{i+1} {status} HA='{title}' ↔ YT='{match['title']}' | "
                f"Duration: {match_duration}s{f' ({duration_diff}s off)' if i > 0 else ''} | "
                f"Score: {match.get('_match_score', 0):.2f}"
            )
    elif match_score is not None:
        logger.info(
            f"Single match: HA='{title}' ↔ YT='{video['title']}' | "
            f"Channel: {video.get('channel')} | Score: {match_score:.2f}"
        )

    return video


def record_failed_search(
    db,
    title: str,
    artist: Optional[str],
    duration: int
) -> None:
    """
    Record a failed search to prevent repeated API calls.

    Args:
        db: Database instance
        title: Video title
        artist: Artist/channel name
        duration: Video duration
    """
    search_query = f"{title} {artist}" if artist else title
    db.record_not_found(title, artist, duration, search_query)


def search_and_match_video_refactored(
    ha_media: Dict[str, Any],
    yt_api,
    db,
    matcher
) -> Optional[Dict]:
    """
    Refactored version of search_and_match_video with better organization.
    Find matching video using global search with duration and title matching.

    Args:
        ha_media: Media information from Home Assistant
        yt_api: YouTube API instance
        db: Database instance
        matcher: Matcher instance for title filtering

    Returns:
        video_dict or None
    """
    # Step 1: Validate requirements
    validation_result = validate_search_requirements(ha_media)
    if not validation_result:
        return None
    title, artist, duration = validation_result

    # Step 2: Check if should skip search
    if should_skip_search(db, title, artist, duration):
        return None

    # Step 3: Search YouTube
    candidates = search_youtube_for_video(yt_api, title, duration, artist)
    if not candidates:
        record_failed_search(db, title, artist, duration)
        return None

    # Step 4: Filter and select best match
    video = filter_and_select_best_match(candidates, title, artist, matcher)
    if not video:
        record_failed_search(db, title, artist, duration)
        return None

    # Step 5: Log success
    logger.info(
        f"MATCHED: HA='{title}' ({duration}s) → YT='{video['title']}' ({video.get('duration', 0)}s) | "
        f"Channel: {video.get('channel')} | ID: {video['yt_video_id']}"
    )

    return video