from flask import Flask, jsonify, Response
from typing import Tuple, Optional, Dict, Any
import os
import traceback
from logger import logger, user_action_logger
from rate_limiter import rate_limiter
from homeassistant_api import ha_api
from youtube_api import get_youtube_api
from matcher import matcher

app = Flask(__name__)


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
    matches = matcher.filter_candidates_by_title(title, candidates)
    if not matches:
        logger.error(f"No videos matched title text: '{title}' | Candidates checked: {len(candidates)}")
        return None
    
    # Step 3: Select best match (first one = highest search relevance)
    video = matches[0]

    if len(matches) > 1:
        logger.warning(f"Multiple matches found ({len(matches)}), using first result: '{video['title']}' on '{video['channel']}'")

    logger.info(f"Successfully found video: '{video['title']}' on '{video['channel']}' (ID: {video['video_id']})")
    return video


def rate_video(rating_type: str) -> Tuple[Response, int]:
    """Common handler for rating videos."""
    logger.info(f"{rating_type} request received")
    
    allowed, reason = rate_limiter.check_and_add_request()
    if not allowed:
        logger.warning(f"Request blocked: {reason}")
        return jsonify({"success": False, "error": reason}), 429
    
    try:
        ha_media = ha_api.get_current_media()
        if not ha_media:
            logger.error(f"No media currently playing | Context: rate_video ({rating_type})")
            return jsonify({"success": False, "error": "No media currently playing"}), 400
        
        video = search_and_match_video(ha_media)
        if not video:
            title = ha_media.get('title', 'unknown')
            artist = ha_media.get('artist', '')
            media_info = format_media_info(title, artist)
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: N/A | FAILED - Video not found")
            logger.error(f"Video not found | Context: rate_video ({rating_type}) | Media: {media_info}")
            return jsonify({"success": False, "error": "Video not found"}), 404
        
        video_id = video['video_id']
        video_title = video['title']
        artist = ha_media.get('artist', '')
        media_info = format_media_info(video_title, artist)

        yt_api = get_youtube_api()
        current_rating = yt_api.get_video_rating(video_id)
        
        if current_rating == rating_type:
            logger.info(f"Video {video_id} already rated '{rating_type}'")
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | ALREADY_RATED")
            return jsonify({"success": True, "message": f"Already rated {rating_type}", "video_id": video_id, "title": video_title}), 200
        
        if yt_api.set_video_rating(video_id, rating_type):
            logger.info(f"Successfully rated video {video_id} {rating_type}")
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | SUCCESS")
            return jsonify({"success": True, "message": f"Successfully rated {rating_type}", "video_id": video_id, "title": video_title}), 200

        user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | FAILED - API error")
        logger.error(f"Failed to set rating | Context: rate_video ({rating_type}) | Video ID: {video_id} | Title: {video_title}")
        return jsonify({"success": False, "error": "Failed to set rating"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in {rating_type} endpoint: {str(e)}")
        logger.debug(f"Traceback for {rating_type} error: {traceback.format_exc()}")
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
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '21812'))

    logger.info(f"Starting YouTube Thumbs service on {host}:{port}")

    try:
        get_youtube_api()
    except Exception as e:
        logger.error(f"Failed to initialize YouTube API: {str(e)}")
        logger.error("Please ensure credentials.json exists and run the OAuth flow")

    app.run(host=host, port=port, debug=False)
