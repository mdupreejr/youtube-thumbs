from flask import Flask, jsonify, Response
from typing import Tuple, Optional, Dict, Any
import os
import traceback
from dotenv import load_dotenv
from logger import logger, user_action_logger, error_logger
from rate_limiter import rate_limiter
from homeassistant_api import ha_api
from youtube_api import get_youtube_api
from matcher import matcher

load_dotenv()

app = Flask(__name__)

PORT = int(os.getenv('PORT', '21812'))
HOST = os.getenv('HOST', '0.0.0.0')


def find_video_with_retry(ha_media: Dict[str, Any]) -> Tuple[Optional[Dict], bool]:
    """
    Find matching video using global search with duration and title matching.
    No retries - either finds it or fails fast.
    
    Returns:
        tuple: (video_dict or None, success: bool)
    """
    yt_api = get_youtube_api()
    
    title = ha_media.get('title')
    artist = ha_media.get('artist')
    duration = ha_media.get('duration')
    
    # Validate required fields
    if not title:
        error_msg = "Missing title in media info"
        logger.error(error_msg)
        error_logger.error(f"{error_msg} | Context: find_video_with_retry")
        return None, False
    
    if not duration:
        error_msg = "Missing duration in media info"
        logger.error(error_msg)
        error_logger.error(f"{error_msg} | Context: find_video_with_retry")
        return None, False
    
    # Build search query (include artist if available for better results)
    if artist:
        search_query = f"{artist} {title}"
    else:
        search_query = title
    
    # Step 1: Search globally, filtered by duration
    candidates = yt_api.search_video_globally(search_query, duration)
    if not candidates:
        error_msg = f"No videos found globally matching title and duration"
        logger.error(error_msg)
        error_logger.error(f"{error_msg} | Context: find_video_with_retry | Query: '{search_query}' | Duration: {duration}s")
        return None, False
    
    # Step 2: Filter candidates by title text matching
    matches = matcher.filter_candidates_by_title(title, candidates)
    if not matches:
        error_msg = f"No videos matched title text: '{title}'"
        logger.error(error_msg)
        error_logger.error(f"{error_msg} | Context: find_video_with_retry | Candidates checked: {len(candidates)}")
        return None, False
    
    # Step 3: Select best match (first one = highest search relevance)
    video = matches[0]
    
    if len(matches) > 1:
        logger.warning(f"Multiple matches found ({len(matches)}), using first result: '{video['title']}' on '{video['channel']}'")
    
    logger.info(f"Successfully found video: '{video['title']}' on '{video['channel']}' (ID: {video['video_id']})")
    return video, True


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
            error_msg = "No media currently playing"
            error_logger.error(f"{error_msg} | Context: rate_video ({rating_type})")
            return jsonify({"success": False, "error": error_msg}), 400
        
        video, _ = find_video_with_retry(ha_media)
        if not video:
            error_msg = "Video not found"
            title = ha_media.get('title', 'unknown')
            artist = ha_media.get('artist', '')
            media_info = f"\"{title}\" by {artist}" if artist else f"\"{title}\""
            user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: N/A | FAILED - {error_msg}")
            error_logger.error(f"{error_msg} | Context: rate_video ({rating_type}) | Media: {media_info}")
            return jsonify({"success": False, "error": error_msg}), 404
        
        video_id = video['video_id']
        video_title = video['title']
        video_channel = video.get('channel', 'unknown')
        artist = ha_media.get('artist', '')
        
        # Format media info for logging
        media_info = f"\"{video_title}\" by {artist}" if artist else f"\"{video_title}\""
        
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
        
        error_msg = "Failed to set rating"
        user_action_logger.info(f"{rating_type.upper()} | {media_info} | ID: {video_id} | FAILED - API error")
        error_logger.error(f"{error_msg} | Context: rate_video ({rating_type}) | Video ID: {video_id} | Title: {video_title}")
        return jsonify({"success": False, "error": error_msg}), 500
    except Exception as e:
        logger.error(f"Error in {rating_type} endpoint: {str(e)}")
        error_logger.error(f"Unexpected error in rate_video ({rating_type}) | Error: {str(e)} | Traceback: {traceback.format_exc()}")
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
    logger.info(f"Starting YouTube Thumbs service on {HOST}:{PORT}")
    
    try:
        get_youtube_api()
    except Exception as e:
        logger.error(f"Failed to initialize YouTube API: {str(e)}")
        logger.error("Please ensure credentials.json exists and run the OAuth flow")
    
    app.run(host=HOST, port=PORT, debug=False)
