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

app = Flask(__name__)
db = get_database()

FALSE_VALUES = {'false', '0', 'no', 'off'}


def format_media_info(title: str, artist: str) -> str:
    """Format media information for logging."""
    return f'"{title}" by {artist}' if artist else f'"{title}"'

def _queue_rating_request(
    video_id: str,
    rating_type: str,
    media_info: str,
    reason: str,
    record_attempt: bool = False,
) -> Tuple[Response, int]:
    db.enqueue_rating(video_id, rating_type)
    if record_attempt:
        db.mark_pending_rating(video_id, False, reason)
    db.record_rating_local(video_id, rating_type)
    user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | QUEUED - {reason}")
    rating_logger.info(f"{rating_type.upper()} | QUEUED | {media_info} | ID: {video_id} | Reason: {reason}")
    return (
        jsonify(
            {
                "success": True,
                "message": f"Queued {rating_type} request; will sync when YouTube API is available ({reason}).",
                "video_id": video_id,
                "queued": True,
            }
        ),
        202,
    )

def _sync_pending_ratings(yt_api: Any, batch_size: int = 5) -> None:
    if quota_guard.is_blocked():
        return
    pending_jobs = db.list_pending_ratings(limit=batch_size)
    if not pending_jobs:
        return

    for job in pending_jobs:
        if quota_guard.is_blocked():
            break
        video_id = job['video_id']
        desired_rating = job['rating']
        media_info = f"queued video {video_id}"
        try:
            if yt_api.set_video_rating(video_id, desired_rating):
                db.record_rating(video_id, desired_rating)
                db.mark_pending_rating(video_id, True)
                rating_logger.info(f"{desired_rating.upper()} | SYNCED | {media_info}")
            else:
                db.mark_pending_rating(video_id, False, "YouTube API returned False")
                break
        except Exception as exc:  # pragma: no cover - defensive
            db.mark_pending_rating(video_id, False, str(exc))
            logger.error("Failed to sync pending rating for %s: %s", video_id, exc)
            break

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
    
    # Build search query (include artist if available for better results)
    if artist:
        search_query = f"{artist} {title}"
    else:
        search_query = title
    
    if quota_guard.is_blocked():
        logger.info(
            "Skipping YouTube search for '%s' due to quota cooldown: %s",
            title,
            quota_guard.describe_block(),
        )
        return None

    candidates = yt_api.search_video_globally(search_query, duration)
    provider = 'YouTube'

    if not candidates:
        logger.error(
            "No videos found matching title and duration | Query: '%s' | Duration: %ss | Providers attempted: %s",
            search_query,
            duration,
            provider or 'none',
        )
        return None
    
    # Step 2: Filter candidates by title text matching
    matches = matcher.filter_candidates_by_title(title, candidates, artist)
    if not matches:
        logger.error(f"No videos matched title text: '{title}' | Candidates checked: {len(candidates)}")
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
        video['video_id'],
    )
    return video


def find_cached_video(ha_media: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Attempt to reuse an existing DB record before querying YouTube."""
    title = ha_media.get('title')
    duration = ha_media.get('duration')
    artist = (ha_media.get('artist') or '').lower() if ha_media.get('artist') else None

    if not title:
        return None

    exact_match = db.find_by_exact_ha_title(title)
    if exact_match:
        logger.info(
            "Using exact cached video ID %s for title '%s'",
            exact_match['video_id'],
            title,
        )
        yt_channel = exact_match.get('yt_channel')
        return {
            'video_id': exact_match['video_id'],
            'title': exact_match.get('yt_title') or exact_match.get('ha_title') or title,
            'channel': yt_channel,
            'duration': exact_match.get('yt_duration') or exact_match.get('ha_duration')
        }

    cached_rows = db.find_by_title(title)
    if not cached_rows:
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
            row['video_id'],
            title,
            yt_channel or 'unknown',
        )
        return {
            'video_id': row['video_id'],
            'title': row.get('yt_title') or row.get('ha_title') or title,
            'channel': yt_channel,
            'duration': row.get('yt_duration') or row.get('ha_duration')
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
        
        video_id = video['video_id']
        video_title = video['title']
        artist = ha_media.get('artist', '')
        media_info = format_media_info(video_title, artist)

        db.upsert_video({
            'video_id': video_id,
            'ha_title': ha_media.get('title', video_title),
            'ha_artist': ha_media.get('artist'),
            'yt_title': video_title,
            'yt_channel': video.get('channel'),
            'yt_channel_id': video.get('channel_id'),
            'yt_description': video.get('description'),
            'yt_published_at': video.get('published_at'),
            'yt_category_id': video.get('category_id'),
            'yt_live_broadcast': video.get('live_broadcast'),
            'yt_location': video.get('location'),
            'yt_recording_date': video.get('recording_date'),
            'ha_duration': ha_media.get('duration'),
            'yt_duration': video.get('duration'),
            'youtube_url': f"https://www.youtube.com/watch?v={video_id}",
            'source': 'ha_live',
        })
        db.record_play(video_id)

        cached_video_row = db.get_video(video_id)
        cached_rating = (cached_video_row or {}).get('rating')
        if cached_rating == rating_type:
            logger.info(f"Video {video_id} already rated '{rating_type}' (cache)")
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | ALREADY_RATED_CACHE")
            rating_logger.info(f"{rating_type.upper()} | ALREADY_RATED | {media_info} | ID: {video_id} | Source: cache")
            db.record_rating(video_id, rating_type)
            return jsonify({"success": True, "message": f"Already rated {rating_type}", "video_id": video_id, "title": video_title}), 200

        if quota_guard.is_blocked():
            guard_status = quota_guard.status()
            logger.warning(
                "Queuing %s request for %s due to quota cooldown",
                rating_type,
                video_id,
            )
            return _queue_rating_request(
                video_id,
                rating_type,
                media_info,
                guard_status.get('message', 'quota cooldown'),
            )

        yt_api = get_youtube_api()
        _sync_pending_ratings(yt_api)

        if yt_api.set_video_rating(video_id, rating_type):
            logger.info(f"Successfully rated video {video_id} {rating_type}")
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | SUCCESS")
            rating_logger.info(f"{rating_type.upper()} | SUCCESS | {media_info} | ID: {video_id}")
            db.record_rating(video_id, rating_type)
            db.mark_pending_rating(video_id, True)
            return jsonify({"success": True, "message": f"Successfully rated {rating_type}", "video_id": video_id, "title": video_title}), 200

        logger.error(
            "YouTube API returned failure for %s request (video %s). Queuing for retry.",
            rating_type,
            video_id,
        )
        return _queue_rating_request(video_id, rating_type, media_info, "YouTube API error", record_attempt=True)
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
    overall_status = "cooldown" if guard_status.get('blocked') else "healthy"
    return jsonify({
        "status": overall_status,
        "rate_limiter": stats,
        "quota_guard": guard_status,
    })


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
