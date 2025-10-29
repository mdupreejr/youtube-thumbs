import atexit
from flask import Flask, jsonify, Response
from typing import Tuple, Optional, Dict, Any
import os
import traceback
from logger import logger, user_action_logger, rating_logger
from rate_limiter import rate_limiter
from homeassistant_api import ha_api
from youtube_api import get_youtube_api
from matcher import matcher
from database import get_database
from history_tracker import HistoryTracker
from quota_guard import quota_guard
from startup_checks import run_startup_checks
from constants import FALSE_VALUES
from video_helpers import prepare_video_upsert, is_youtube_content
from metrics_tracker import metrics

app = Flask(__name__)
db = get_database()


def format_media_info(title: str, artist: str) -> str:
    """Format media information for logging."""
    return f'"{title}" by {artist}' if artist else f'"{title}"'

def _queue_rating_request(
    yt_video_id: str,
    rating_type: str,
    media_info: str,
    reason: str,
    record_attempt: bool = False,
) -> Tuple[Response, int]:
    db.enqueue_rating(yt_video_id, rating_type)
    if record_attempt:
        db.mark_pending_rating(yt_video_id, False, reason)
    db.record_rating_local(yt_video_id, rating_type)
    metrics.record_rating(success=False, queued=True)
    user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {yt_video_id} | QUEUED - {reason}")
    rating_logger.info(f"{rating_type.upper()} | QUEUED | {media_info} | ID: {yt_video_id} | Reason: {reason}")
    return (
        jsonify(
            {
                "success": True,
                "message": f"Queued {rating_type} request; will sync when YouTube API is available ({reason}).",
                "video_id": yt_video_id,
                "queued": True,
            }
        ),
        202,
    )

def _sync_pending_ratings(yt_api: Any, batch_size: int = 20) -> None:
    """
    Sync pending ratings using batch operations for efficiency.
    Processes up to batch_size pending ratings, using batch API calls where possible.
    """
    # Validate batch size (YouTube API supports max 50 IDs per videos.list call)
    batch_size = max(1, min(batch_size, 50))

    if quota_guard.is_blocked():
        return

    # Get more pending ratings to process in batch
    pending_jobs = db.list_pending_ratings(limit=batch_size)
    if not pending_jobs:
        return

    # Prepare batch ratings
    ratings_to_process = []
    for job in pending_jobs:
        if quota_guard.is_blocked():
            break
        ratings_to_process.append((job['yt_video_id'], job['rating']))

    if not ratings_to_process:
        return

    # Use batch operations if we have multiple ratings
    if len(ratings_to_process) > 1:
        logger.info(f"Processing batch of {len(ratings_to_process)} pending ratings")

        # Batch process the ratings
        results = yt_api.batch_set_ratings(ratings_to_process)

        # Update database based on results
        for video_id, rating in ratings_to_process:
            success = results.get(video_id, False)
            if success:
                db.record_rating(video_id, rating)
                db.mark_pending_rating(video_id, True)
                metrics.record_rating(success=True, queued=False)
                rating_logger.info(f"{rating.upper()} | SYNCED | queued video {video_id}")
            else:
                db.mark_pending_rating(video_id, False, "Batch rating failed")
                metrics.record_rating(success=False, queued=False)
                logger.warning(f"Failed to sync rating for {video_id}")
    else:
        # Single rating, use regular method
        video_id, rating = ratings_to_process[0]
        media_info = f"queued video {video_id}"
        try:
            if yt_api.set_video_rating(video_id, rating):
                db.record_rating(video_id, rating)
                db.mark_pending_rating(video_id, True)
                rating_logger.info(f"{rating.upper()} | SYNCED | {media_info}")
            else:
                db.mark_pending_rating(video_id, False, "YouTube API returned False")
        except Exception as exc:  # pragma: no cover - defensive
            db.mark_pending_rating(video_id, False, str(exc))
            logger.error("Failed to sync pending rating for %s: %s", video_id, exc)

def search_and_match_video(ha_media: Dict[str, Any]) -> Optional[Dict]:
    """
    Find matching video using global search with duration and title matching.
    Either finds it or fails fast.

    Returns:
        video_dict or None
    """
    yt_api = get_youtube_api()
    
    title = ha_media.get('title')
    artist = ha_media.get('artist')
    duration = ha_media.get('duration')
    
    # Validate required fields
    if not title:
        logger.error("Missing title in media info")
        return None

    if not duration:
        logger.error("Missing duration in media info")
        return None
    
    # Check if this search recently failed (Phase 3: Cache Negative Results)
    if db.is_recently_not_found(title, artist, duration):
        metrics.record_not_found_cache_hit(title)
        return None  # Skip search, already logged by is_recently_not_found

    if quota_guard.is_blocked():
        logger.info(
            "Skipping YouTube search for '%s' due to quota cooldown: %s",
            title,
            quota_guard.describe_block(),
        )
        return None

    # Use the improved search with smart query building
    candidates = yt_api.search_video_globally(title, duration, artist)
    provider = 'YouTube'

    if not candidates:
        logger.error(
            "No videos found matching title and duration | Title: '%s' | Artist: '%s' | Duration: %ss | Providers attempted: %s",
            title,
            artist or 'N/A',
            duration,
            provider or 'none',
        )
        # Record this failed search to prevent repeated API calls
        metrics.record_failed_search(title, artist, reason='not_found')
        db.record_not_found(title, artist, duration, f"{title} {artist}" if artist else title)
        return None
    
    # Step 2: Filter candidates by title text matching
    matches = matcher.filter_candidates_by_title(title, candidates, artist)
    if not matches:
        logger.error(f"No videos matched title text: '{title}' | Candidates checked: {len(candidates)}")
        # Record this failed search to prevent repeated API calls
        db.record_not_found(title, artist, duration, f"{title} {artist}" if artist else title)
        return None
    
    # Step 3: Select best match (first one = highest search relevance)
    video = matches[0]
    match_score = video.pop('_match_score', None)

    if len(matches) > 1:
        runner_up = matches[1]
        logger.warning(
            "Multiple matches found (%s). Using '%s' (score %.2f) over '%s' (score %.2f)",
            len(matches),
            video['title'],
            match_score or 0,
            runner_up.get('title'),
            runner_up.get('_match_score', 0),
        )
    elif match_score is not None:
        logger.info(
            "Matched '%s' on '%s' (score %.2f)",
            video['title'],
            video.get('channel'),
            match_score,
        )

    logger.info(
        "Successfully found video via %s: '%s' on '%s' (ID: %s)",
        provider or 'unknown',
        video['title'],
        video.get('channel'),
        video['yt_video_id'],
    )
    return video


def find_cached_video(ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attempt to reuse an existing DB record before querying YouTube."""
    title = ha_media.get('title')
    duration = ha_media.get('duration')
    artist = (ha_media.get('artist') or '').lower() if ha_media.get('artist') else None

    if not title:
        return None

    # First check by content hash (title+duration+artist) for exact duplicate detection
    hash_match = db.find_by_content_hash(title, duration, artist)
    if hash_match:
        logger.info(
            "Using hash-cached video ID %s for title '%s' (duration %s)",
            hash_match['yt_video_id'],
            title,
            duration,
        )
        metrics.record_cache_hit('content_hash')
        return {
            'yt_video_id': hash_match['yt_video_id'],
            'title': hash_match.get('yt_title') or hash_match.get('ha_title') or title,
            'channel': hash_match.get('yt_channel'),
            'duration': hash_match.get('yt_duration') or hash_match.get('ha_duration')
        }

    exact_match = db.find_by_exact_ha_title(title)
    if exact_match:
        logger.info(
            "Using exact cached video ID %s for title '%s'",
            exact_match['yt_video_id'],
            title,
        )
        metrics.record_cache_hit('exact_title')
        yt_channel = exact_match.get('yt_channel')
        return {
            'yt_video_id': exact_match['yt_video_id'],
            'title': exact_match.get('yt_title') or exact_match.get('ha_title') or title,
            'channel': yt_channel,
            'duration': exact_match.get('yt_duration') or exact_match.get('ha_duration')
        }

    cached_rows = db.find_by_title(title)
    if not cached_rows:
        # Try fuzzy matching as a fallback
        logger.debug("No exact title match found, trying fuzzy matching for '%s'", title)
        fuzzy_matches = db.find_fuzzy_matches(title, threshold=85.0, limit=10)

        if fuzzy_matches:
            from fuzzy_matcher import find_best_fuzzy_match
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
                return {
                    'yt_video_id': best_match['yt_video_id'],
                    'title': best_match.get('yt_title') or best_match.get('ha_title') or title,
                    'channel': best_match.get('yt_channel'),
                    'duration': best_match.get('yt_duration') or best_match.get('ha_duration')
                }

        metrics.record_cache_miss()
        return None

    for row in cached_rows:
        stored_duration = row.get('ha_duration') or row.get('yt_duration')
        if duration and stored_duration and abs(stored_duration - duration) > 2:
            continue

        yt_channel = row.get('yt_channel')
        if artist and yt_channel and yt_channel.lower() != artist:
            continue

        logger.info(
            "Using cached video ID %s for title '%s' (channel: %s)",
            row['yt_video_id'],
            title,
            yt_channel or 'unknown',
        )
        metrics.record_cache_hit('title_with_filters')
        return {
            'yt_video_id': row['yt_video_id'],
            'title': row.get('yt_title') or row.get('ha_title') or title,
            'channel': yt_channel,
            'duration': row.get('yt_duration') or row.get('ha_duration')
        }

    # If we have exact title matches but none passed duration/artist filters,
    # try fuzzy matching as a last resort
    logger.debug("Exact title matches filtered out, trying fuzzy matching for '%s'", title)
    fuzzy_matches = db.find_fuzzy_matches(title, threshold=85.0, limit=10)

    if fuzzy_matches:
        from fuzzy_matcher import find_best_fuzzy_match
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
            return {
                'yt_video_id': best_match['yt_video_id'],
                'title': best_match.get('yt_title') or best_match.get('ha_title') or title,
                'channel': best_match.get('yt_channel'),
                'duration': best_match.get('yt_duration') or best_match.get('ha_duration')
            }

    return None


def _history_tracker_enabled() -> bool:
    value = os.getenv('ENABLE_HISTORY_TRACKER', 'true')
    return value.lower() not in FALSE_VALUES if isinstance(value, str) else True


def _history_poll_interval() -> int:
    raw_interval = os.getenv('HISTORY_POLL_INTERVAL', '60')
    try:
        interval = int(raw_interval)
        return interval if interval > 0 else 60
    except ValueError:
        logger.warning(
            "Invalid HISTORY_POLL_INTERVAL '%s'; using default 60 seconds",
            raw_interval,
        )
        return 60


history_tracker = HistoryTracker(
    ha_api=ha_api,
    database=db,
    find_cached_video=find_cached_video,
    search_and_match_video=search_and_match_video,
    poll_interval=_history_poll_interval(),
    enabled=_history_tracker_enabled(),
)
history_tracker.start()
atexit.register(history_tracker.stop)


def rate_video(rating_type: str) -> Tuple[Response, int]:
    """Common handler for rating videos."""
    logger.info(f"{rating_type} request received")
    
    allowed, reason = rate_limiter.check_and_add_request()
    if not allowed:
        logger.warning(f"Request blocked: {reason}")
        rating_logger.info(f"{rating_type.upper()} | BLOCKED | Reason: {reason}")
        return jsonify({"success": False, "error": reason}), 429
    
    try:
        ha_media = ha_api.get_current_media()
        if not ha_media:
            logger.error(f"No media currently playing | Context: rate_video ({rating_type})")
            rating_logger.info(f"{rating_type.upper()} | FAILED | No media currently playing")
            return jsonify({"success": False, "error": "No media currently playing"}), 400

        # Skip non-YouTube content to save API calls
        if not is_youtube_content(ha_media):
            title = ha_media.get('title', 'unknown')
            channel = ha_media.get('channel', 'unknown')
            logger.info(f"Skipping non-YouTube content: '{title}' from channel '{channel}'")
            rating_logger.info(f"{rating_type.upper()} | SKIPPED | Non-YouTube content from '{channel}'")
            return jsonify({"success": False, "error": f"Not YouTube content (channel: {channel})"}), 400

        video = find_cached_video(ha_media)
        if not video:
            if quota_guard.is_blocked():
                guard_status = quota_guard.status()
                cooldown_msg = guard_status.get('message')
                logger.error(
                    "Cannot locate cached video while quota is blocked; rejecting %s request",
                    rating_type,
                )
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": cooldown_msg,
                            "cooldown_until": guard_status.get('blocked_until'),
                            "cooldown_seconds_remaining": guard_status.get('remaining_seconds', 0),
                        }
                    ),
                    503,
                )
            video = search_and_match_video(ha_media)
        if not video:
            title = ha_media.get('title', 'unknown')
            artist = ha_media.get('artist', '')
            media_info = format_media_info(title, artist)
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: N/A | FAILED - Video not found")
            rating_logger.info(f"{rating_type.upper()} | FAILED | {media_info} | ID: N/A | Reason: Video not found")
            logger.error(f"Video not found | Context: rate_video ({rating_type}) | Media: {media_info}")
            return jsonify({"success": False, "error": "Video not found"}), 404
        
        yt_video_id = video['yt_video_id']
        video_title = video['title']
        artist = ha_media.get('artist', '')
        media_info = format_media_info(video_title, artist)

        # Use helper function to prepare video data
        video_data = prepare_video_upsert(video, ha_media, source='ha_live')
        db.upsert_video(video_data)
        db.record_play(yt_video_id)

        cached_video_row = db.get_video(yt_video_id)
        cached_rating = (cached_video_row or {}).get('rating')
        if cached_rating == rating_type:
            logger.info(f"Video {yt_video_id} already rated '{rating_type}' (cache)")
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {yt_video_id} | ALREADY_RATED_CACHE")
            rating_logger.info(f"{rating_type.upper()} | ALREADY_RATED | {media_info} | ID: {yt_video_id} | Source: cache")
            db.record_rating(yt_video_id, rating_type)
            return jsonify({"success": True, "message": f"Already rated {rating_type}", "video_id": yt_video_id, "title": video_title}), 200

        if quota_guard.is_blocked():
            guard_status = quota_guard.status()
            logger.warning(
                "Queuing %s request for %s due to quota cooldown",
                rating_type,
                yt_video_id,
            )
            return _queue_rating_request(
                yt_video_id,
                rating_type,
                media_info,
                guard_status.get('message', 'quota cooldown'),
            )

        yt_api = get_youtube_api()
        _sync_pending_ratings(yt_api)

        if yt_api.set_video_rating(yt_video_id, rating_type):
            logger.info(f"Successfully rated video {yt_video_id} {rating_type}")
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {yt_video_id} | SUCCESS")
            rating_logger.info(f"{rating_type.upper()} | SUCCESS | {media_info} | ID: {yt_video_id}")
            db.record_rating(yt_video_id, rating_type)
            db.mark_pending_rating(yt_video_id, True)
            return jsonify({"success": True, "message": f"Successfully rated {rating_type}", "video_id": yt_video_id, "title": video_title}), 200

        logger.error(
            "YouTube API returned failure for %s request (video %s). Queuing for retry.",
            rating_type,
            yt_video_id,
        )
        return _queue_rating_request(yt_video_id, rating_type, media_info, "YouTube API error", record_attempt=True)
    except Exception as e:
        logger.error(f"Unexpected error in {rating_type} endpoint: {str(e)}")
        logger.debug(f"Traceback for {rating_type} error: {traceback.format_exc()}")
        rating_logger.info(f"{rating_type.upper()} | FAILED | Unexpected error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/thumbs_up', methods=['POST'])
def thumbs_up() -> Tuple[Response, int]:
    return rate_video('like')

@app.route('/thumbs_down', methods=['POST'])
def thumbs_down() -> Tuple[Response, int]:
    return rate_video('dislike')


@app.route('/health', methods=['GET'])
def health() -> Response:
    """Health check endpoint."""
    stats = rate_limiter.get_stats()
    guard_status = quota_guard.status()

    # Get health score from metrics
    health_score, warnings = metrics.get_health_score()
    if guard_status.get('blocked'):
        overall_status = "cooldown"
    elif health_score >= 70:
        overall_status = "healthy"
    elif health_score >= 40:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return jsonify({
        "status": overall_status,
        "health_score": health_score,
        "warnings": warnings,
        "rate_limiter": stats,
        "quota_guard": guard_status,
    })


@app.route('/metrics', methods=['GET'])
def get_metrics() -> Response:
    """
    Comprehensive metrics endpoint for monitoring and analysis.

    Returns detailed statistics about:
    - Cache performance and hit rates
    - API usage and quota status
    - Rating operations (success/failed/queued)
    - Search patterns and failures
    - System uptime and health
    """
    try:
        all_metrics = metrics.get_all_metrics()
        health_score, warnings = metrics.get_health_score()

        response_data = {
            'health': {
                'score': health_score,
                'status': 'healthy' if health_score >= 70 else 'degraded' if health_score >= 40 else 'unhealthy',
                'warnings': warnings
            },
            **all_metrics
        }

        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        return jsonify({'error': 'Failed to generate metrics', 'message': str(e)}), 500


if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '21812'))

    logger.info(f"Starting YouTube Thumbs service on {host}:{port}")

    # Initialize YouTube API
    yt_api = None
    try:
        yt_api = get_youtube_api()
    except Exception as e:
        logger.error(f"Failed to initialize YouTube API: {str(e)}")
        logger.error("Please ensure credentials.json exists and run the OAuth flow")

    # Run startup health checks
    run_startup_checks(ha_api, yt_api, db)

    app.run(host=host, port=port, debug=False)
