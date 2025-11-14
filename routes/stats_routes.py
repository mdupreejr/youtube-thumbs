"""
Statistics and debug routes for viewing video statistics and ratings.
Now using BaseRouteHandler for consistency and error prevention.
"""
import os
import traceback
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, Response, g
from logging_helper import LoggingHelper, LogType

# Import the base handler for consistent routing
from helpers.base_route_handler import BaseRouteHandler

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)
from constants import YOUTUBE_CATEGORIES
from helpers.video_helpers import get_video_title, get_video_artist, format_videos_for_display
from helpers.time_helpers import format_relative_time
from helpers.validation_helpers import validate_page_param
from helpers.response_helpers import error_response
from helpers.request_helpers import get_real_ip
from helpers.pagination_helpers import generate_page_numbers
from helpers.template import (
    TableData, TableColumn, TableRow, TableCell,
    create_stats_page_config, format_youtube_link,
    build_video_table_rows
)
from helpers.page_builder import StatsPageBuilder
from helpers.sorting_helpers import sort_table_data
from helpers.constants.empty_states import EMPTY_STATE_NO_LIKED, EMPTY_STATE_NO_DISLIKED

bp = Blueprint('stats', __name__)

# Global database reference and handler
_db = None
_handler = None


class StatsRouteHandler(BaseRouteHandler):
    """Handler wrapper for stats routes with validation."""

    def __init__(self, database):
        super().__init__(db=database)


def init_stats_routes(database):
    """Initialize stats routes with dependencies."""
    global _db, _handler
    _db = database
    _handler = StatsRouteHandler(database)


# ============================================================================
# STATS DASHBOARD ROUTES
# ============================================================================

@bp.route('/stats')
def stats_dashboard() -> str:
    """
    Unified stats dashboard with multiple tabs: overview, analytics, api, categories, discovery.
    Supports ?tab=<tab_name> parameter to select which tab to display.
    All tabs use the same stats.html template with conditional rendering.
    """
    try:
        # Get ingress path for proper link generation
        ingress_path = g.ingress_path

        # Get requested tab from query parameter (default: overview)
        current_tab = request.args.get('tab', 'overview')
        if current_tab not in ['overview', 'analytics', 'api', 'categories', 'discovery']:
            current_tab = 'overview'

        # Dispatch to appropriate handler based on tab
        if current_tab == 'overview':
            return _render_stats_overview_tab(ingress_path)
        elif current_tab == 'analytics':
            return _render_stats_analytics_tab(ingress_path)
        elif current_tab == 'api':
            return _render_stats_api_tab(ingress_path)
        elif current_tab == 'categories':
            return _render_stats_categories_tab(ingress_path)
        elif current_tab == 'discovery':
            return _render_stats_discovery_tab(ingress_path)

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering stats dashboard", e)
        return "<h1>Error loading statistics</h1><p>An internal error occurred. Please try again later.</p>", 500


def _render_stats_overview_tab(ingress_path: str) -> str:
    """Render the overview tab of the stats dashboard."""
    # Fetch fresh data
    summary = _db.get_stats_summary()
    most_played = _db.get_most_played(10)
    top_channels = _db.get_top_channels(10)
    recent = _db.get_recent_activity(15)

    # Use handler to ensure all required fields exist with defaults
    if _handler:
        _handler.ensure_dict_fields(summary, {
            'total_videos': 0,
            'total_plays': 0,
            'liked': 0,
            'disliked': 0,
            'unrated': 0,
            'unique_channels': 0
        })

    # Calculate rating percentages (ensure integers to avoid type errors)
    liked = int(summary.get('liked', 0) or 0)
    disliked = int(summary.get('disliked', 0) or 0)
    unrated = int(summary.get('unrated', 0) or 0)
    total_plays = int(summary.get('total_plays', 0) or 0)
    total = liked + disliked + unrated

    if total > 0:
        rating_percentages = {
            'liked': (liked / total) * 100,
            'disliked': (disliked / total) * 100,
            'unrated': (unrated / total) * 100
        }
    else:
        rating_percentages = {'liked': 0, 'disliked': 0, 'unrated': 0}

    # Add missing fields expected by the template
    summary['skipped'] = total_plays - total  # Videos played but not rated/unrated

    # Calculate like percentage (liked vs disliked, not counting unrated/skipped)
    if liked + disliked > 0:
        summary['like_percentage'] = (liked / (liked + disliked)) * 100
    else:
        summary['like_percentage'] = 0

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

    # Prepare template data with ingress_path
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

    if _handler:
        return _handler.render_page('stats.html', **template_data)
    else:
        if _handler:
        return _handler.render_page('stats.html', **template_data)
    else:
        return render_template('stats.html', **template_data)


def _render_stats_analytics_tab(ingress_path: str) -> str:
    """Render the analytics tab of the stats dashboard."""
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

    # Prepare template data with ingress_path
    template_data = {
        'ingress_path': ingress_path,
        'current_tab': 'analytics',
        'listening_patterns': patterns,
        'heatmap_data': heatmap_data,
        'play_distribution': play_dist,
        'retention_analysis': retention,
        'correlation_stats': correlation,
        'max_hour_plays': max_hour_plays,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    if _handler:
        return _handler.render_page('stats.html', **template_data)
    else:
        return render_template('stats.html', **template_data)


def _render_stats_api_tab(ingress_path: str) -> str:
    """Render the API & Queue tab of the stats dashboard."""

    # Fetch API and queue data
    api_summary = _db.get_api_usage_summary(days=30)
    hourly_usage = _db.get_api_hourly_usage()
    api_calls = _db.get_api_call_summary(hours=24)
    queue_stats = _db.get_queue_statistics()
    queue_activity = _db.get_recent_queue_activity(limit=20)
    queue_errors = _db.get_queue_errors(limit=10)

    # Prepare template data with ingress_path
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

    if _handler:
        return _handler.render_page('stats.html', **template_data)
    else:
        return render_template('stats.html', **template_data)


def _render_stats_categories_tab(ingress_path: str) -> str:
    """Render the categories tab of the stats dashboard."""

    # Fetch category and duration data
    category_breakdown = _db.get_category_breakdown()
    duration_analysis = _db.get_duration_analysis()

    # Map category IDs to names and calculate percentages
    total_categorized = sum(item.get('count', 0) for item in category_breakdown)
    for item in category_breakdown:
        cat_id = item.get('yt_category_id')
        item['category_name'] = YOUTUBE_CATEGORIES.get(cat_id, f'Category {cat_id}')
        item['percentage'] = (item.get('count', 0) / total_categorized * 100) if total_categorized > 0 else 0

    # Prepare template data with ingress_path
    template_data = {
        'ingress_path': ingress_path,
        'current_tab': 'categories',
        'category_breakdown': category_breakdown,
        'duration_analysis': duration_analysis,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    if _handler:
        return _handler.render_page('stats.html', **template_data)
    else:
        return render_template('stats.html', **template_data)


def _render_stats_discovery_tab(ingress_path: str) -> str:
    """Render the discovery tab of the stats dashboard."""

    # Fetch discovery data
    discovery_trends = _db.get_discovery_stats()
    source_breakdown = _db.get_source_breakdown()
    top_channels = _db.get_top_channels(15)
    recommendations = _db.get_recommendations('likes', 10)

    # Calculate source percentages
    total_sources = sum(item.get('count', 0) for item in source_breakdown)
    for item in source_breakdown:
        item['percentage'] = (item.get('count', 0) / total_sources * 100) if total_sources > 0 else 0

    # Prepare template data with ingress_path
    template_data = {
        'ingress_path': ingress_path,
        'current_tab': 'discovery',
        'discovery_trends': discovery_trends,
        'source_breakdown': source_breakdown,
        'top_channels': top_channels,
        'recommendations': recommendations,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    if _handler:
        return _handler.render_page('stats.html', **template_data)
    else:
        return render_template('stats.html', **template_data)


# ============================================================================
# STATS PAGINATED VIEWS (separate routes for table-based pages)
# ============================================================================

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

        # Server-side sorting support
        sort_by = request.args.get('sort_by', 'last_played')
        sort_dir = request.args.get('sort_dir', 'desc')

        result = _db.get_rated_videos('like', page=page, per_page=50)

        # Sort using unified helper
        sort_key_map = {
            'song': 'ha_title',
            'artist': 'ha_artist',
            'plays': 'play_count',
            'last_played': 'date_last_played'
        }
        sort_table_data(result['videos'], sort_by, sort_dir, sort_key_map)

        # Use builder pattern for consistent page creation
        builder = StatsPageBuilder('liked', ingress_path)
        builder.set_title('👍 Liked Videos', f"{result['total_count']} total")
        builder.set_empty_state(**EMPTY_STATE_NO_LIKED)

        # Create table data
        columns = [
            TableColumn('song', 'Song', width='50%'),
            TableColumn('artist', 'Artist'),
            TableColumn('plays', 'Plays'),
            TableColumn('last_played', 'Last Played')
        ]
        
        rows = build_video_table_rows(result['videos'], format_videos_for_display, format_youtube_link)

        # Set table and pagination
        builder.set_table(columns, rows)
        page_numbers = generate_page_numbers(result['current_page'], result['total_pages'])
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
        LoggingHelper.log_error_with_trace(f"Error rendering liked stats: {e}", e)
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

        # Server-side sorting support
        sort_by = request.args.get('sort_by', 'last_played')
        sort_dir = request.args.get('sort_dir', 'desc')

        result = _db.get_rated_videos('dislike', page=page, per_page=50)

        # Sort using unified helper
        sort_key_map = {
            'song': 'ha_title',
            'artist': 'ha_artist',
            'plays': 'play_count',
            'last_played': 'date_last_played'
        }
        sort_table_data(result['videos'], sort_by, sort_dir, sort_key_map)

        # Use builder pattern for consistent page creation
        builder = StatsPageBuilder('disliked', ingress_path)
        builder.set_title('👎 Disliked Videos', f"{result['total_count']} total")
        builder.set_empty_state(**EMPTY_STATE_NO_DISLIKED)

        # Create table data
        columns = [
            TableColumn('song', 'Song', width='50%'),
            TableColumn('artist', 'Artist'),
            TableColumn('plays', 'Plays'),
            TableColumn('last_played', 'Last Played')
        ]
        
        rows = build_video_table_rows(result['videos'], format_videos_for_display, format_youtube_link)

        # Set table and pagination
        builder.set_table(columns, rows)
        page_numbers = generate_page_numbers(result['current_page'], result['total_pages'])
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
        LoggingHelper.log_error_with_trace(f"Error rendering disliked stats: {e}", e)
        return "<h1>Error loading disliked videos</h1>", 500


# ============================================================================
# DEBUG ROUTES
# ============================================================================

