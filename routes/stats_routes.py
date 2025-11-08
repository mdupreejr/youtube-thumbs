"""
Statistics and debug routes for viewing video statistics and ratings.
Extracted from app.py for better organization.
"""
import os
import traceback
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, Response
from logger import logger
from helpers.video_helpers import get_video_title, get_video_artist, format_videos_for_display
from helpers.time_helpers import format_relative_time
from helpers.validation_helpers import validate_page_param
from helpers.response_helpers import error_response
from helpers.request_helpers import get_real_ip

bp = Blueprint('stats', __name__)

# Global database reference (set by init function)
_db = None

def init_stats_routes(database):
    """Initialize stats routes with dependencies."""
    global _db
    _db = database


# ============================================================================
# STATS ROUTES
# ============================================================================

@bp.route('/stats')
def stats_page() -> str:
    """
    Server-side rendered statistics page.
    All processing done on server, no client-side JavaScript required.
    """
    try:
        # Get ingress path for proper link generation
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

        # Check cache first (5 minute TTL)
        cached = _db.get_cached_stats('stats_page')
        if cached:
            # Add ingress_path to cached data
            cached['ingress_path'] = ingress_path
            return render_template('stats_server.html', **cached)

        # Fetch fresh data
        summary = _db.get_stats_summary()
        most_played = _db.get_most_played(10)
        top_channels = _db.get_top_channels(10)
        recent = _db.get_recent_activity(15)

        # Calculate rating percentages (ensure integers to avoid type errors)
        liked = int(summary.get('liked', 0) or 0)
        disliked = int(summary.get('disliked', 0) or 0)
        unrated = int(summary.get('unrated', 0) or 0)
        total = liked + disliked + unrated

        if total > 0:
            rating_percentages = {
                'liked': (liked / total) * 100,
                'disliked': (disliked / total) * 100,
                'unrated': (unrated / total) * 100
            }
        else:
            rating_percentages = {'liked': 0, 'disliked': 0, 'unrated': 0}

        # Format recent activity
        recent_activity = []
        for item in recent:
            title = get_video_title(item)
            artist = get_video_artist(item)

            # Calculate time ago
            if item.get('date_last_played'):
                time_ago = format_relative_time(item['date_last_played'])
                if time_ago == "unknown":
                    time_ago = "Recently"
            else:
                time_ago = "Recently"

            rating_icons = {'like': '👍', 'dislike': '👎', 'none': '➖'}
            rating_icon = rating_icons.get(item.get('rating', 'none'), '➖')

            recent_activity.append({
                'title': title,
                'artist': artist,
                'time_ago': time_ago,
                'rating_icon': rating_icon,
                'yt_video_id': item.get('yt_video_id')
            })

        # Format most played
        formatted_most_played = []
        for video in most_played:
            title = get_video_title(video)
            artist = get_video_artist(video)
            formatted_most_played.append({
                'title': title,
                'artist': artist,
                'play_count': video.get('play_count', 0),
                'yt_video_id': video.get('yt_video_id')
            })

        # Prepare template data
        template_data = {
            'ingress_path': ingress_path,
            'summary': summary,
            'rating_percentages': rating_percentages,
            'most_played': formatted_most_played,
            'top_channels': top_channels,
            'recent_activity': recent_activity,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Cache for 5 minutes
        _db.set_cached_stats('stats_page', template_data, ttl_seconds=300)

        return render_template('stats_server.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering stats page: {e}")
        logger.error(traceback.format_exc())
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading statistics</h1><p>An internal error occurred. Please try again later.</p>", 500


@bp.route('/stats/liked')
def stats_liked_page() -> str:
    """Show paginated list of liked videos."""
    try:
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
        page, error = validate_page_param(request.args)
        if error:
            return error_response('Invalid page parameter', 400)
        if not page:
            page = 1

        result = _db.get_rated_videos('like', page=page, per_page=50)

        # Format videos
        formatted_videos = format_videos_for_display(result['videos'])

        return render_template('stats_rated.html',
                             ingress_path=ingress_path,
                             rating_type='liked',
                             rating_icon='👍',
                             videos=formatted_videos,
                             total_count=result['total_count'],
                             current_page=result['current_page'],
                             total_pages=result['total_pages'])
    except Exception as e:
        logger.error(f"Error rendering liked stats: {e}")
        return "<h1>Error loading liked videos</h1>", 500


@bp.route('/stats/disliked')
def stats_disliked_page() -> str:
    """Show paginated list of disliked videos."""
    try:
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
        page, error = validate_page_param(request.args)
        if error:
            return error_response('Invalid page parameter', 400)
        if not page:
            page = 1

        result = _db.get_rated_videos('dislike', page=page, per_page=50)

        # Format videos
        formatted_videos = format_videos_for_display(result['videos'])

        return render_template('stats_rated.html',
                             ingress_path=ingress_path,
                             rating_type='disliked',
                             rating_icon='👎',
                             videos=formatted_videos,
                             total_count=result['total_count'],
                             current_page=result['current_page'],
                             total_pages=result['total_pages'])
    except Exception as e:
        logger.error(f"Error rendering disliked stats: {e}")
        return "<h1>Error loading disliked videos</h1>", 500


# ============================================================================
# DEBUG ROUTES
# ============================================================================

@bp.route('/debug/not_found_analysis')
def debug_not_found_analysis() -> Response:
    """Debug endpoint to analyze not_found videos for patterns."""
    # SECURITY: Debug endpoints must be explicitly enabled in configuration
    debug_enabled = os.getenv('DEBUG_ENDPOINTS_ENABLED', 'false').lower() == 'true'
    if not debug_enabled:
        logger.warning(f"SECURITY: Unauthorized access attempt to debug endpoint from {get_real_ip()}")
        return jsonify({
            'error': 'Debug endpoints are disabled',
            'message': 'Set debug_endpoints_enabled: true in addon configuration to enable'
        }), 403

    # Log access for security audit
    logger.warning(f"SECURITY: Debug endpoint accessed from {get_real_ip()}")

    try:
        # v4.0.0: Not found videos no longer stored in video_ratings
        # Return empty analysis for backward compatibility
        logger.debug("not_found_analysis endpoint called but is DEPRECATED in v4.0.0")

        analysis = {
            'total_count': 0,
            'videos': [],
            'patterns': {
                'missing_artist': 0,
                'missing_duration': 0,
                'high_attempts': 0,
                'frequently_played': 0
            },
            'deprecated': True,
            'message': 'v4.0.0: Not found videos are now tracked in queue table, not video_ratings'
        }

        return jsonify(analysis)
    except Exception as e:
        logger.error(f"Error in not_found analysis: {e}")
        return jsonify({'error': str(e)}), 500
