"""
Statistics and debug routes for viewing video statistics and ratings.
Extracted from app.py for better organization.
"""
import os
import traceback
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, Response, g
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)
from constants import YOUTUBE_CATEGORIES
from helpers.video_helpers import get_video_title, get_video_artist, format_videos_for_display
from helpers.time_helpers import format_relative_time
from helpers.validation_helpers import validate_page_param
from helpers.response_helpers import error_response
from helpers.request_helpers import get_real_ip
from helpers.template_helpers import (
    TableData, TableColumn, TableRow, TableCell,
    create_stats_page_config, format_youtube_link
)
from helpers.page_builder import StatsPageBuilder

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
        ingress_path = g.ingress_path

        # Check cache first (5 minute TTL)
        cached = _db.get_cached_stats('stats_overview')
        if cached:
            # Add ingress_path to cached data
            cached['ingress_path'] = ingress_path
            cached['current_tab'] = 'overview'
            return render_template('stats.html', **cached)

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

        # Get additional analytics for overview
        retention = _db.get_retention_analysis()
        play_dist = _db.get_play_distribution()

        # Calculate percentage for play distribution
        total_videos = sum(item['video_count'] for item in play_dist)
        if total_videos > 0:
            for item in play_dist:
                item['percentage'] = (item['video_count'] / total_videos) * 100
        else:
            for item in play_dist:
                item['percentage'] = 0

        discovery = _db.get_discovery_stats()
        correlation = _db.get_correlation_stats()

        # Prepare template data
        template_data = {
            'ingress_path': ingress_path,
            'current_tab': 'overview',
            'summary': summary,
            'rating_percentages': rating_percentages,
            'most_played': formatted_most_played,
            'top_channels': top_channels,
            'recent_activity': recent_activity,
            'retention': retention,
            'play_distribution': play_dist,
            'discovery': discovery,
            'correlation': correlation,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Cache for 5 minutes
        _db.set_cached_stats('stats_overview', template_data, ttl_seconds=300)

        return render_template('stats.html', **template_data)

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering stats page: {e}", e)

        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading statistics</h1><p>An internal error occurred. Please try again later.</p>", 500


@bp.route('/stats/analytics')
def stats_analytics_page() -> str:
    """Analytics tab with listening patterns, play distributions, and retention analysis."""
    try:
        ingress_path = g.ingress_path
        
        # Check cache first (5 minute TTL)
        cached = _db.get_cached_stats('stats_analytics')
        if cached:
            cached['ingress_path'] = ingress_path
            cached['current_tab'] = 'analytics'
            return render_template('stats.html', **cached)

        # Fetch analytics data
        patterns = _db.get_listening_patterns()
        play_dist = _db.get_play_distribution()
        retention = _db.get_retention_analysis()
        correlation = _db.get_correlation_stats()
        
        # Process listening patterns for heatmap
        heatmap_data = []
        day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        
        # Create 7x24 grid for heatmap
        max_plays = 0
        for day in range(7):
            day_data = []
            for hour in range(24):
                plays = 0
                # Find matching data from patterns
                for pattern in patterns.get('by_hour', []):
                    if pattern.get('hour') == hour and pattern.get('day') == day:
                        # Now matches both day and hour combination
                        plays = pattern.get('play_count', 0)
                        max_plays = max(max_plays, plays)
                        break
                day_data.append(plays)
            heatmap_data.append({
                'day': day_names[day],
                'hours': day_data
            })
        
        # Calculate heat intensities (0-5 scale)
        for day_row in heatmap_data:
            day_row['heat_levels'] = []
            for plays in day_row['hours']:
                if max_plays == 0:
                    level = 0
                else:
                    percentage = (plays / max_plays) * 100
                    if percentage == 0:
                        level = 0
                    elif percentage < 10:
                        level = 1
                    elif percentage < 30:
                        level = 2
                    elif percentage < 50:
                        level = 3
                    elif percentage < 75:
                        level = 4
                    else:
                        level = 5
                day_row['heat_levels'].append(level)
        
        # Process play distribution for percentages
        total_videos = sum(item.get('video_count', 0) for item in play_dist)
        for item in play_dist:
            item['percentage'] = (item.get('video_count', 0) / total_videos * 100) if total_videos > 0 else 0

        # Calculate max play count for hourly bar chart
        max_hour_plays = max((p.get('play_count', 0) for p in patterns.get('by_hour', [])), default=0)

        template_data = {
            'current_tab': 'analytics',
            'listening_patterns': patterns,
            'heatmap_data': heatmap_data,
            'play_distribution': play_dist,
            'retention_analysis': retention,
            'correlation_stats': correlation,
            'max_hour_plays': max_hour_plays,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        _db.set_cached_stats('stats_analytics', template_data, ttl_seconds=300)
        return render_template('stats.html', **template_data)

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering analytics page: {e}", e)

        return "<h1>Error loading analytics</h1><p>An internal error occurred. Please try again later.</p>", 500


@bp.route('/stats/api')
def stats_api_page() -> str:
    """API usage and queue health metrics tab."""
    try:
        ingress_path = g.ingress_path
        
        # Check cache first (5 minute TTL)
        cached = _db.get_cached_stats('stats_api')
        if cached:
            cached['ingress_path'] = ingress_path
            cached['current_tab'] = 'api'
            return render_template('stats.html', **cached)

        # Fetch API and queue data
        api_summary = _db.get_api_usage_summary(days=30)
        hourly_usage = _db.get_api_hourly_usage()
        api_calls = _db.get_api_call_summary(hours=24)
        queue_stats = _db.get_queue_statistics()
        queue_activity = _db.get_recent_queue_activity(limit=20)
        queue_errors = _db.get_queue_errors(limit=10)

        template_data = {
            'ingress_path': ingress_path,
            'current_tab': 'api',
            'api_summary': api_summary,
            'hourly_usage': hourly_usage,
            'api_calls': api_calls,
            'queue_stats': queue_stats,
            'queue_activity': queue_activity,
            'queue_errors': queue_errors,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        _db.set_cached_stats('stats_api', template_data, ttl_seconds=300)
        return render_template('stats.html', **template_data)

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering API stats page: {e}", e)

        return "<h1>Error loading API statistics</h1><p>An internal error occurred. Please try again later.</p>", 500


@bp.route('/stats/categories')
def stats_categories_page() -> str:
    """Categories and duration analysis tab."""
    try:
        ingress_path = g.ingress_path
        
        # Check cache first (5 minute TTL)
        cached = _db.get_cached_stats('stats_categories')
        if cached:
            cached['ingress_path'] = ingress_path
            cached['current_tab'] = 'categories'
            return render_template('stats.html', **cached)

        # Fetch category and duration data
        category_breakdown = _db.get_category_breakdown()
        duration_analysis = _db.get_duration_analysis()
        
        # Map category IDs to names and calculate percentages
        total_categorized = sum(item.get('count', 0) for item in category_breakdown)
        for item in category_breakdown:
            cat_id = item.get('yt_category_id')
            item['category_name'] = YOUTUBE_CATEGORIES.get(cat_id, f'Category {cat_id}')
            item['percentage'] = (item.get('count', 0) / total_categorized * 100) if total_categorized > 0 else 0

        template_data = {
            'ingress_path': ingress_path,
            'current_tab': 'categories',
            'category_breakdown': category_breakdown,
            'duration_analysis': duration_analysis,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        _db.set_cached_stats('stats_categories', template_data, ttl_seconds=300)
        return render_template('stats.html', **template_data)

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering categories page: {e}", e)

        return "<h1>Error loading categories</h1><p>An internal error occurred. Please try again later.</p>", 500


@bp.route('/stats/discovery')
def stats_discovery_page() -> str:
    """Discovery trends and recommendations tab."""
    try:
        ingress_path = g.ingress_path
        
        # Check cache first (5 minute TTL)
        cached = _db.get_cached_stats('stats_discovery')
        if cached:
            cached['ingress_path'] = ingress_path
            cached['current_tab'] = 'discovery'
            return render_template('stats.html', **cached)

        # Fetch discovery data
        discovery_trends = _db.get_discovery_stats()
        source_breakdown = _db.get_source_breakdown()
        top_channels = _db.get_top_channels(15)
        recommendations = _db.get_recommendations('likes', 10)
        
        # Calculate source percentages
        total_sources = sum(item.get('count', 0) for item in source_breakdown)
        for item in source_breakdown:
            item['percentage'] = (item.get('count', 0) / total_sources * 100) if total_sources > 0 else 0

        template_data = {
            'ingress_path': ingress_path,
            'current_tab': 'discovery',
            'discovery_trends': discovery_trends,
            'source_breakdown': source_breakdown,
            'top_channels': top_channels,
            'recommendations': recommendations,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        _db.set_cached_stats('stats_discovery', template_data, ttl_seconds=300)
        return render_template('stats.html', **template_data)

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering discovery page: {e}", e)

        return "<h1>Error loading discovery</h1><p>An internal error occurred. Please try again later.</p>", 500


@bp.route('/stats/liked')
def stats_liked_page() -> str:
    """Show paginated list of liked videos."""
    try:
        ingress_path = g.ingress_path
        page, error = validate_page_param(request.args)
        if error:
            return error_response('Invalid page parameter', 400)
        if not page:
            page = 1

        result = _db.get_rated_videos('like', page=page, per_page=50)
        
        # Use builder pattern for consistent page creation
        builder = StatsPageBuilder('liked', ingress_path)
        builder.set_title('👍 Liked Videos', f"{result['total_count']} total")
        builder.set_empty_state('👍', 'No liked videos', "You haven't liked any videos yet.")

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

        # Set table and pagination
        builder.set_table(columns, rows)
        page_numbers = list(range(max(1, page-2), min(result['total_pages']+1, page+3)))
        builder.set_pagination(result['current_page'], result['total_pages'], page_numbers)

        # Build and render
        page_config, table_data, pagination = builder.build()

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if table_data and table_data.rows else None,
            pagination=pagination
        )
    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering liked stats: {e}", e)
        return "<h1>Error loading liked videos</h1>", 500


@bp.route('/stats/disliked')
def stats_disliked_page() -> str:
    """Show paginated list of disliked videos."""
    try:
        ingress_path = g.ingress_path
        page, error = validate_page_param(request.args)
        if error:
            return error_response('Invalid page parameter', 400)
        if not page:
            page = 1

        result = _db.get_rated_videos('dislike', page=page, per_page=50)

        # Use builder pattern for consistent page creation
        builder = StatsPageBuilder('disliked', ingress_path)
        builder.set_title('👎 Disliked Videos', f"{result['total_count']} total")
        builder.set_empty_state('👎', 'No disliked videos', "You haven't disliked any videos yet.")

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

        # Set table and pagination
        builder.set_table(columns, rows)
        page_numbers = list(range(max(1, page-2), min(result['total_pages']+1, page+3)))
        builder.set_pagination(result['current_page'], result['total_pages'], page_numbers)

        # Build and render
        page_config, table_data, pagination = builder.build()

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if table_data and table_data.rows else None,
            pagination=pagination
        )
    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering disliked stats: {e}", e)
        return "<h1>Error loading disliked videos</h1>", 500


# ============================================================================
# DEBUG ROUTES
# ============================================================================

