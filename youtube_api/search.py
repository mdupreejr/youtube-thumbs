"""
YouTube video search operations.

This module handles video search functionality including query building,
result scoring, and batch video fetching.
"""

from typing import Optional, List, Dict, Any, Tuple
from googleapiclient.errors import HttpError
from logging_helper import LoggingHelper, LogType
from error_handler import log_and_suppress, validate_environment_variable
from quota_error import QuotaExceededError
from constants import YOUTUBE_DURATION_OFFSET

from .quota_manager import quota_error_detail
from .title_cleaner import build_smart_search_query
from .video_parser import process_search_result

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

# Global database instance for API usage tracking (injected from app.py)
_db = None

# Search configuration
MAX_SEARCH_RESULTS = validate_environment_variable(
    'YTT_SEARCH_MAX_RESULTS',
    default=25,
    converter=int,
    validator=lambda x: 1 <= x <= 50
)
MAX_CANDIDATES = validate_environment_variable(
    'YTT_SEARCH_MAX_CANDIDATES',
    default=10,
    converter=int,
    validator=lambda x: 1 <= x <= 50
)

# API field specifications
SEARCH_FIELDS = 'items(id/videoId,snippet/title)'
VIDEO_FIELDS = 'items(id,snippet(title,channelTitle,channelId,description,publishedAt,categoryId,liveBroadcastContent),contentDetails(duration),recordingDetails(location,recordingDate))'


def set_database(db):
    """Set the database instance for API usage tracking."""
    global _db
    _db = db


def calculate_title_similarity(result_title: str, query_title: str) -> float:
    """
    Calculate similarity score between titles (0-1, higher is better).

    Uses multiple strategies:
    1. Exact match = 1.0
    2. Contains exact query = 0.9
    3. Word overlap (Jaccard similarity) = 0.0-0.8

    Args:
        result_title: Title from YouTube search result
        query_title: Original query title

    Returns:
        float: Similarity score between 0.0 and 1.0
    """
    result_lower = result_title.lower()
    query_lower = query_title.lower()

    # Exact match = perfect score
    if result_lower == query_lower:
        return 1.0

    # Contains exact query = high score
    if query_lower in result_lower:
        return 0.9

    # Word overlap scoring (Jaccard similarity)
    result_words = set(result_lower.split())
    query_words = set(query_lower.split())

    if not query_words:
        return 0.0

    # Jaccard similarity (intersection / union)
    intersection = len(result_words & query_words)
    union = len(result_words | query_words)

    return intersection / union if union > 0 else 0.0


def score_and_sort_results(items: list, title: str) -> list:
    """
    Score search results by title similarity and sort by relevance.

    Args:
        items: List of search result items from YouTube API
        title: Original query title for comparison

    Returns:
        List of video IDs sorted by relevance (best matches first)
    """
    # Score each result by title similarity
    scored_items = []
    for item in items:
        result_title = item['snippet'].get('title', '')
        score = calculate_title_similarity(result_title, title)
        scored_items.append((score, item))

    # Sort by score descending (best matches first)
    scored_items.sort(key=lambda x: x[0], reverse=True)

    # Log top matches for debugging
    logger.debug(f"Top 3 matches by title similarity: " +
                ", ".join([f"{item['snippet'].get('title', '')[:40]}... ({score:.2f})"
                          for score, item in scored_items[:3]]))

    # Extract video IDs in score order
    video_ids = [item['id']['videoId'] for score, item in scored_items]
    return video_ids


def log_search_api_call(search_query: str, title: str, success: bool, results_count: int = 0, error_message: str = None):
    """
    Log YouTube search API call to database.

    Args:
        search_query: The search query used
        title: Original title being searched
        success: Whether the API call succeeded
        results_count: Number of results returned
        error_message: Error message if failed
    """
    if not _db:
        return

    quota_cost = 100 if success else 0  # Search costs 100 quota units
    title_truncated = f"title='{title[:50]}...'" if len(title) > 50 else f"title='{title}'"

    _db.record_api_call('search', success=success, quota_cost=quota_cost, error_message=error_message)
    _db.log_api_call_detailed(
        api_method='search',
        operation_type='search_video',
        query_params=f"q='{search_query}', maxResults={MAX_SEARCH_RESULTS}",
        quota_cost=quota_cost,
        success=success,
        results_count=results_count,
        error_message=error_message,
        context=title_truncated
    )


def log_batch_api_call(phase: str, batch_num: int, video_count: int, title: str, success: bool, error_message: str = None):
    """
    Log YouTube batch video fetch API call to database.

    Args:
        phase: Phase identifier (e.g., "Phase 1", "Phase 2")
        batch_num: Batch number within phase
        video_count: Number of videos in this batch
        title: Original title being searched
        success: Whether the API call succeeded
        error_message: Error message if failed
    """
    if not _db:
        return

    quota_cost = video_count if success else 0  # videos.list costs 1 quota unit per video
    title_truncated = f"{title[:30]}..." if len(title) > 30 else title
    context = f"[{phase}] batch {batch_num} of search for '{title_truncated}'"

    _db.record_api_call('videos.list', success=success, quota_cost=quota_cost, error_message=error_message)
    _db.log_api_call_detailed(
        api_method='videos.list',
        operation_type='batch_get_video_details',
        query_params=f"ids={video_count} videos",
        quota_cost=quota_cost,
        success=success,
        results_count=video_count if success else 0,
        error_message=error_message,
        context=context
    )


def fetch_video_batch(
    youtube_client,
    video_id_batch: list,
    expected_duration: Optional[int],
    title: str,
    phase: str,
    batch_num: int,
    api_debug_data: dict
) -> tuple:
    """
    Fetch and process a batch of videos from YouTube API.

    OPTIMIZED: Fetches multiple videos in a single API call (reduces network latency 10x).
    Processes videos and separates duration-matched candidates from all fetched videos.

    Args:
        youtube_client: Authenticated YouTube API client
        video_id_batch: List of video IDs to fetch
        expected_duration: Expected duration for filtering (or None for no filter)
        title: Original title being searched (for logging)
        phase: Phase identifier (e.g., "Phase 1", "Phase 2")
        batch_num: Batch number within phase
        api_debug_data: Debug data dict to append batch response

    Returns:
        Tuple of (candidates, all_videos, videos_checked_count):
        - candidates: List of videos matching duration filter
        - all_videos: List of all videos fetched (for caching)
        - videos_checked_count: Number of videos fetched

    Raises:
        QuotaExceededError: If YouTube quota is exceeded
    """
    if not video_id_batch:
        return ([], [], 0)

    batch_ids = ','.join(video_id_batch)
    logger.debug(f"[{phase}] Batch {batch_num}: Fetching {len(video_id_batch)} videos in single API call")

    try:
        # OPTIMIZED: Single batch API call instead of N sequential calls
        details = youtube_client.videos().list(
            part='contentDetails,snippet,recordingDetails',
            id=batch_ids,  # Batch request - up to 50 IDs
            fields=VIDEO_FIELDS,
        ).execute()

        # Capture batch response for debugging
        api_debug_data['batch_responses'].append({
            'phase': phase,
            'batch_num': batch_num,
            'video_ids_requested': len(video_id_batch),
            'response': details
        })

        videos_fetched = len(details.get('items', []))

        # Track successful batch API call (quota = 1 per video)
        log_batch_api_call(phase, batch_num, videos_fetched, title, success=True)

        # Process ALL fetched videos in score order (best title matches first)
        candidates = []
        all_videos = []

        for video in details.get('items', []):
            # First, cache video WITHOUT duration filtering
            video_info_all = process_search_result(video, expected_duration=None)
            if video_info_all:
                all_videos.append(video_info_all)

            # Then check for duration match
            video_info = process_search_result(video, expected_duration)
            if video_info:
                candidates.append(video_info)

        # Log results
        if candidates:
            logger.debug(f"[{phase}] Found {len(candidates)} match(es) in batch {batch_num}")

        return (candidates, all_videos, videos_fetched)

    except HttpError as e:
        # Check for quota errors
        detail = quota_error_detail(e)
        is_quota_error = detail is not None

        # Log failed API call
        error_msg = "Quota exceeded" if is_quota_error else str(e)
        quota_cost = 0 if is_quota_error else len(video_id_batch)
        log_batch_api_call(phase, batch_num, quota_cost, title, success=False, error_message=error_msg)

        # Raise quota errors to stop processing
        if is_quota_error:
            raise QuotaExceededError("YouTube quota exceeded")

        # Log and continue on other errors
        logger.warning(f"[{phase}] Error fetching batch {batch_num}: {e}")
        return ([], [], 0)

    except Exception as e:
        # Unexpected error - log and continue
        logger.error(f"[{phase}] Unexpected error fetching batch {batch_num}: {e}", exc_info=True)
        log_batch_api_call(
            phase, batch_num, len(video_id_batch), title,
            success=False, error_message=f"Unexpected error: {str(e)}"
        )
        return ([], [], 0)


def search_video_globally(
    youtube_client,
    title: str,
    expected_duration: Optional[int] = None,
    artist: Optional[str] = None,
    return_api_response: bool = False
):
    """
    Search for a video globally. Filters by duration (exact or +1s) if provided.

    Args:
        youtube_client: Authenticated YouTube API client
        title: Video title to search for
        expected_duration: Expected HA duration in seconds (YouTube must be exact or +1s)
        artist: Artist/channel name (optional, improves accuracy for generic titles like "Flowers", "Electric")
        return_api_response: If True, return tuple of (candidates, api_debug_data)

    Note: v4.0.68+ now uses artist parameter to improve search accuracy for generic titles.

    Returns:
        If return_api_response=False: List of candidate videos or None
        If return_api_response=True: Tuple of (candidates or None, api_debug_data dict)
    """
    api_debug_data = {
        'search_query': None,
        'search_response': None,
        'batch_responses': [],
        'videos_checked': 0,
        'candidates_found': 0
    }

    try:
        # Build search query (cleaned and simplified)
        # v4.0.68: Now includes artist when provided (improves accuracy for generic titles)
        search_query = build_smart_search_query(title, artist)
        logger.debug(f"YouTube Search: Original='{title}' | Artist='{artist}' | Query='{search_query}'")

        api_debug_data['search_query'] = search_query

        response = youtube_client.search().list(
            part='snippet',
            q=search_query,
            type='video',
            maxResults=MAX_SEARCH_RESULTS,
            fields=SEARCH_FIELDS,
        ).execute()

        api_debug_data['search_response'] = response

        # Track API usage
        log_search_api_call(search_query, title, success=True, results_count=len(response.get('items', [])))

        items = response.get('items', [])
        if not items:
            logger.error(f"No videos found globally for: '{title}'")
            api_debug_data['videos_checked'] = 0
            api_debug_data['candidates_found'] = 0
            return (None, api_debug_data) if return_api_response else None

        logger.debug(f"Found {len(items)} videos globally")

        # OPTIMIZATION: Score results by title similarity before checking durations
        # This ensures we check the most relevant matches first
        video_ids = score_and_sort_results(items, title)

        # v4.0.60: OPTIMIZED with batched API calls to reduce network latency
        # Phase 1: Batch fetch first 10 videos (high confidence - best title matches)
        # Phase 2: If no match, batch fetch up to 15 more (up to 25 total)
        # IMPORTANT: Cache ALL videos checked, not just the ones that match
        PHASE_1_LIMIT = 10  # High-confidence check
        PHASE_2_LIMIT = 25  # Extended search if needed
        candidates = []
        all_fetched_videos = []  # Track ALL videos fetched for caching
        videos_checked = 0

        # Phase 1: Batch fetch first 10 videos (single API call = 10x faster than sequential)
        logger.debug(f"Starting Phase 1: Batch fetching first {PHASE_1_LIMIT} videos (high confidence)")
        phase1_ids = video_ids[:PHASE_1_LIMIT]
        if phase1_ids:
            batch_candidates, batch_all_videos, batch_count = fetch_video_batch(
                youtube_client, phase1_ids, expected_duration, title, "Phase 1", 1, api_debug_data
            )
            candidates.extend(batch_candidates)
            all_fetched_videos.extend(batch_all_videos)
            videos_checked += batch_count

        # Phase 2: If no match found, batch fetch next 15 videos (up to 25 total)
        if not candidates and len(video_ids) > PHASE_1_LIMIT:
            remaining = min(PHASE_2_LIMIT - PHASE_1_LIMIT, len(video_ids) - PHASE_1_LIMIT)
            logger.debug(f"No match in Phase 1, starting Phase 2: Batch fetching {remaining} more videos")
            phase2_ids = video_ids[PHASE_1_LIMIT:PHASE_1_LIMIT + remaining]
            if phase2_ids:
                batch_candidates, batch_all_videos, batch_count = fetch_video_batch(
                    youtube_client, phase2_ids, expected_duration, title, "Phase 2", 2, api_debug_data
                )
                candidates.extend(batch_candidates)
                all_fetched_videos.extend(batch_all_videos)
                videos_checked += batch_count

        if candidates:
            logger.info(f"Found match after checking {videos_checked} videos (saved checking {min(PHASE_2_LIMIT, len(video_ids)) - videos_checked} videos)")
        else:
            logger.debug(f"No match found after checking {videos_checked} videos")

        if not candidates and expected_duration:
            logger.error(
                f"No exact duration matches found: HA='{title}' ({expected_duration}s) | "
                f"Expected YouTube duration: {expected_duration + YOUTUBE_DURATION_OFFSET}s | "
                f"Checked {videos_checked}/{len(video_ids)} videos"
            )
            # Don't return None yet - still cache all checked videos

        if len(candidates) > MAX_CANDIDATES:
            candidates = candidates[:MAX_CANDIDATES]
            logger.debug(
                "Trimmed candidates to %s to minimize API comparisons",
                MAX_CANDIDATES,
            )

        # v4.0.58: Cache ALL videos we checked (even if no duration match found)
        # This ensures we don't waste the API quota we already spent
        if _db and all_fetched_videos:
            try:
                cached_count = _db.cache_search_results(all_fetched_videos, ttl_days=30)
                logger.info(f"Opportunistically cached {cached_count}/{len(all_fetched_videos)} videos checked during search ({len(candidates)} duration matches)")
            except Exception as exc:
                logger.warning(f"Failed to cache fetched videos: {exc}")

        # Update final stats in debug data
        api_debug_data['videos_checked'] = videos_checked
        api_debug_data['candidates_found'] = len(candidates) if candidates else 0

        if not candidates:
            logger.info(f"No duration matches, but cached {len(all_fetched_videos)} checked videos for future searches")
            return (None, api_debug_data) if return_api_response else None

        logger.debug(f"Found {len(candidates)} duration-matched candidates")
        return (candidates, api_debug_data) if return_api_response else candidates

    except HttpError as e:
        detail = quota_error_detail(e)
        is_quota_error = detail is not None

        # Capture error in debug data
        api_debug_data['error'] = {
            'type': 'quota_exceeded' if is_quota_error else 'http_error',
            'message': "Quota exceeded" if is_quota_error else str(e),
            'detail': detail
        }

        # v4.0.29: ALWAYS log failed API calls (including quota errors) BEFORE raising
        # This ensures check_quota_recently_exceeded() can find recent quota errors
        if _db:
            _db.record_api_call('search', success=False, quota_cost=100 if not is_quota_error else 0,
                               error_message="Quota exceeded" if is_quota_error else str(e))
            _db.log_api_call_detailed(
                api_method='search',
                operation_type='search_video',
                query_params=f"q='{api_debug_data.get('search_query', title)}', maxResults={MAX_SEARCH_RESULTS}",
                quota_cost=100 if not is_quota_error else 0,  # No quota consumed if quota already exceeded
                success=False,
                error_message="Quota exceeded" if is_quota_error else str(e),
                context=f"title='{title[:50]}...'" if len(title) > 50 else f"title='{title}'"
            )

        if is_quota_error:
            # Raise exception - worker will catch and sleep until midnight
            raise QuotaExceededError("YouTube quota exceeded")

        if return_api_response:
            return (None, api_debug_data)

        return log_and_suppress(
            e,
            f"YouTube API error in search_video_globally | Query: '{title}'",
            level="error",
            return_value=None,
            log_traceback=not is_quota_error  # Skip traceback for quota errors
        )
    except Exception as e:
        # Capture unexpected error in debug data
        api_debug_data['error'] = {
            'type': 'unexpected_error',
            'message': str(e)
        }

        if return_api_response:
            return (None, api_debug_data)

        return log_and_suppress(
            e,
            f"Unexpected error searching video | Query: '{title}'",
            level="error",
            return_value=None
        )
