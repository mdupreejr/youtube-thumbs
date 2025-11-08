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
from helpers.template_helpers import (
    PageConfig, TableData, TableColumn, TableRow, TableCell,
    create_stats_page_config, format_youtube_link, format_badge
)

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

        # v4.0.55: Removed pending_summary - retry functionality removed from UI

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
        
        # Create page configuration
        page_config = create_stats_page_config('liked', ingress_path)
        page_config.title = '👍 Liked Videos'
        page_config.title_suffix = f"{result['total_count']} total"
        
        # Create table data
        columns = [
            TableColumn('song', 'Song', width='50%'),
            TableColumn('artist', 'Artist'),
            TableColumn('plays', 'Plays'),
            TableColumn('last_played', 'Last Played')
        ]
        
        rows = []
        for video in result['videos']:
            formatted_video = format_videos_for_display([video])[0]
            
            # Format song title with YouTube link
            song_html = format_youtube_link(
                formatted_video.get('yt_video_id'), 
                formatted_video.get('title', 'Unknown'),
                icon=False
            )
            
            # Format last played date
            last_played = '-'
            if formatted_video.get('date_last_played'):
                last_played = str(formatted_video['date_last_played'])[:10]
            
            cells = [
                TableCell(formatted_video.get('title', 'Unknown'), song_html),
                TableCell(formatted_video.get('artist', '-'), style='color: #64748b;'),
                TableCell(formatted_video.get('play_count', 0), style='color: #64748b;'),
                TableCell(last_played, style='color: #64748b; white-space: nowrap;')
            ]
            rows.append(TableRow(cells))
        
        table_data = TableData(columns, rows)
        
        # Create pagination
        pagination = {
            'current_page': result['current_page'],
            'total_pages': result['total_pages'],
            'page_numbers': list(range(max(1, page-2), min(result['total_pages']+1, page+3))),
            'prev_url': f"/stats/liked?page={page-1}" if page > 1 else None,
            'next_url': f"/stats/liked?page={page+1}" if page < result['total_pages'] else None,
            'page_url_template': "/stats/liked?page=PAGE_NUM"
        } if result['total_pages'] > 1 else None
        
        # Set empty state
        page_config.set_empty_state('👍', 'No liked videos', "You haven't liked any videos yet.")
        
        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if rows else None,
            pagination=pagination
        )
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
        
        # Create page configuration
        page_config = create_stats_page_config('disliked', ingress_path)
        page_config.title = '👎 Disliked Videos'
        page_config.title_suffix = f"{result['total_count']} total"
        
        # Create table data
        columns = [
            TableColumn('song', 'Song', width='50%'),
            TableColumn('artist', 'Artist'),
            TableColumn('plays', 'Plays'),
            TableColumn('last_played', 'Last Played')
        ]
        
        rows = []
        for video in result['videos']:
            formatted_video = format_videos_for_display([video])[0]
            
            # Format song title with YouTube link
            song_html = format_youtube_link(
                formatted_video.get('yt_video_id'), 
                formatted_video.get('title', 'Unknown'),
                icon=False
            )
            
            # Format last played date
            last_played = '-'
            if formatted_video.get('date_last_played'):
                last_played = str(formatted_video['date_last_played'])[:10]
            
            cells = [
                TableCell(formatted_video.get('title', 'Unknown'), song_html),
                TableCell(formatted_video.get('artist', '-'), style='color: #64748b;'),
                TableCell(formatted_video.get('play_count', 0), style='color: #64748b;'),
                TableCell(last_played, style='color: #64748b; white-space: nowrap;')
            ]
            rows.append(TableRow(cells))
        
        table_data = TableData(columns, rows)
        
        # Create pagination
        pagination = {
            'current_page': result['current_page'],
            'total_pages': result['total_pages'],
            'page_numbers': list(range(max(1, page-2), min(result['total_pages']+1, page+3))),
            'prev_url': f"/stats/disliked?page={page-1}" if page > 1 else None,
            'next_url': f"/stats/disliked?page={page+1}" if page < result['total_pages'] else None,
            'page_url_template': "/stats/disliked?page=PAGE_NUM"
        } if result['total_pages'] > 1 else None
        
        # Set empty state
        page_config.set_empty_state('👎', 'No disliked videos', "You haven't disliked any videos yet.")
        
        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if rows else None,
            pagination=pagination
        )
    except Exception as e:
        logger.error(f"Error rendering disliked stats: {e}")
        return "<h1>Error loading disliked videos</h1>", 500


# ============================================================================
# DEBUG ROUTES
# ============================================================================

