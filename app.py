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

app = Flask(__name__)
db = get_database()

FALSE_VALUES = {'false', '0', 'no', 'off'}


def format_media_info(title: str, artist: str) -> str:
    """Format media information for logging."""
    return f'"{title}" by {artist}' if artist else f'"{title}"'


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
    
    # Step 1: Search globally, filtered by duration
    candidates = yt_api.search_video_globally(search_query, duration)
    if not candidates:
        logger.error(f"No videos found globally matching title and duration | Query: '{search_query}' | Duration: {duration}s")
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

    logger.info(f"Successfully found video: '{video['title']}' on '{video['channel']}' (ID: {video['video_id']})")
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
        return {
            'video_id': exact_match['video_id'],
            'title': exact_match.get('yt_title') or exact_match.get('ha_title') or title,
            'channel': exact_match.get('channel'),
            'duration': exact_match.get('yt_duration') or exact_match.get('ha_duration')
        }

    cached_rows = db.find_by_title(title)
    if not cached_rows:
        return None

    for row in cached_rows:
        stored_duration = row.get('ha_duration') or row.get('yt_duration')
        if duration and stored_duration and abs(stored_duration - duration) > 2:
            continue

        channel = row.get('channel')
        if artist and channel and channel.lower() != artist:
            continue

        logger.info(
            "Using cached video ID %s for title '%s' (channel: %s)",
            row['video_id'],
            title,
            channel or 'unknown',
        )
        return {
            'video_id': row['video_id'],
            'title': row.get('yt_title') or row.get('ha_title') or title,
            'channel': channel,
            'duration': row.get('yt_duration') or row.get('ha_duration')
        }

    return None


def _history_tracker_enabled() -> bool:
    value = os.getenv('ENABLE_HISTORY_TRACKER', 'true')
    return value.lower() not in FALSE_VALUES if isinstance(value, str) else True


def _history_poll_interval() -> int:
    raw_interval = os.getenv('HISTORY_POLL_INTERVAL', '30')
    try:
        interval = int(raw_interval)
        return interval if interval > 0 else 30
    except ValueError:
        logger.warning(
            "Invalid HISTORY_POLL_INTERVAL '%s'; using default 30 seconds",
            raw_interval,
        )
        return 30


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
            'yt_title': video_title,
            'channel': video.get('channel'),
            'ha_duration': ha_media.get('duration'),
            'yt_duration': video.get('duration'),
            'youtube_url': f"https://www.youtube.com/watch?v={video_id}"
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

        yt_api = get_youtube_api()

        if yt_api.set_video_rating(video_id, rating_type):
            logger.info(f"Successfully rated video {video_id} {rating_type}")
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | SUCCESS")
            rating_logger.info(f"{rating_type.upper()} | SUCCESS | {media_info} | ID: {video_id}")
            db.record_rating(video_id, rating_type)
            return jsonify({"success": True, "message": f"Successfully rated {rating_type}", "video_id": video_id, "title": video_title}), 200

        user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | FAILED - API error")
        rating_logger.info(f"{rating_type.upper()} | FAILED | {media_info} | ID: {video_id} | Reason: API error")
        logger.error(f"Failed to set rating | Context: rate_video ({rating_type}) | Video ID: {video_id} | Title: {video_title}")
        return jsonify({"success": False, "error": "Failed to set rating"}), 500
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
    return jsonify({
        "status": "healthy",
        "rate_limiter": stats
    })


if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '21812'))

    logger.info(f"Starting YouTube Thumbs service on {host}:{port}")

    try:
        get_youtube_api()
    except Exception as e:
        logger.error(f"Failed to initialize YouTube API: {str(e)}")
        logger.error("Please ensure credentials.json exists and run the OAuth flow")

    app.run(host=host, port=port, debug=False)
