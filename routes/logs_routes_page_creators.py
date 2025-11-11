"""
Page creator functions for logs routes.

Extracted from routes/logs_routes.py for better code organization.
Each function creates the page configuration and table data for a specific tab.
"""

from flask import request
from helpers.pagination_helpers import generate_page_numbers
from helpers.time_helpers import format_relative_time
from helpers.video_helpers import get_video_title, get_video_artist
from helpers.template_helpers import (
    TableColumn, TableRow, TableCell,
    format_badge, format_time_ago, truncate_text,
    format_song_display, format_status_badge
)
from helpers.page_builder import LogsPageBuilder
from helpers.log_parsers import parse_error_log


def _create_rated_songs_page(page: int, period_filter: str, ingress_path: str, db):
    """Create page config and table data for rated songs."""
    # Get filters
    rating_filter = request.args.get('rating', 'all')
    if rating_filter not in ['like', 'dislike', 'all']:
        rating_filter = 'all'

    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('rated', ingress_path)

    # Add filters
    builder.add_filter('period', 'Time Period', [
        {'value': 'hour', 'label': 'Last Hour', 'selected': period_filter == 'hour'},
        {'value': 'day', 'label': 'Last Day', 'selected': period_filter == 'day'},
        {'value': 'week', 'label': 'Last Week', 'selected': period_filter == 'week'},
        {'value': 'month', 'label': 'Last Month', 'selected': period_filter == 'month'},
        {'value': 'all', 'label': 'All Time', 'selected': period_filter == 'all'}
    ])

    builder.add_filter('rating', 'Rating Type', [
        {'value': 'all', 'label': 'All', 'selected': rating_filter == 'all'},
        {'value': 'like', 'label': 'Likes', 'selected': rating_filter == 'like'},
        {'value': 'dislike', 'label': 'Dislikes', 'selected': rating_filter == 'dislike'}
    ])

    builder.add_hidden_field('tab', 'rated')
    builder.set_empty_state('📭', 'No rated songs found', 'Try adjusting your filters')

    # Get data
    result = db.get_rated_songs(page, 50, period_filter, rating_filter)

    # Create table columns
    columns = [
        TableColumn('time', 'Time'),
        TableColumn('song', 'Song'),
        TableColumn('artist', 'Artist'),
        TableColumn('rating', 'Rating'),
        TableColumn('plays', 'Plays'),
        TableColumn('video_id', 'Video ID')
    ]

    # Create table rows
    rows = []
    for song in result['songs']:
        title = get_video_title(song)
        artist = get_video_artist(song)

        # Format relative time
        timestamp = song.get('date_last_played') or song.get('date_added')
        time_ago = format_relative_time(timestamp) if timestamp else 'unknown'

        # Format rating
        rating = song.get('rating')
        if rating == 'like':
            rating_html = format_badge('👍 Like', 'success')
        elif rating == 'dislike':
            rating_html = format_badge('👎 Dislike', 'error')
        else:
            rating_html = format_badge('➖ None', 'info')

        # Format video link
        video_id = song.get('yt_video_id')
        video_link = f'<a href="https://youtube.com/watch?v={video_id}" target="_blank">{video_id}</a>'

        cells = [
            TableCell(time_ago),
            TableCell(title),
            TableCell(artist or '-'),
            TableCell(rating, rating_html),
            TableCell(song.get('play_count', 0), format_badge(str(song.get('play_count', 0)), 'info')),
            TableCell(video_id, video_link)
        ]
        rows.append(TableRow(cells))

    # Set table data
    builder.set_table(columns, rows)

    # Set pagination
    total_count = result['total_count']
    total_pages = result['total_pages']
    page_numbers = generate_page_numbers(page, total_pages)

    builder.set_pagination(
        page,
        total_pages,
        page_numbers,
        '/logs',
        {'tab': 'rated', 'period': period_filter, 'rating': rating_filter}
    )

    # Set status message
    builder.set_status_message(
        f"Showing {len(result['songs'])} of {total_count} rated songs • Page {page}/{total_pages}"
    )

    return builder.build()


def _create_matches_page(page: int, period_filter: str, ingress_path: str, db):
    """Create page config and table data for matches."""
    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('matches', ingress_path)

    # Add period filter
    builder.add_filter('period', 'Time Period', [
        {'value': 'hour', 'label': 'Last Hour', 'selected': period_filter == 'hour'},
        {'value': 'day', 'label': 'Last Day', 'selected': period_filter == 'day'},
        {'value': 'week', 'label': 'Last Week', 'selected': period_filter == 'week'},
        {'value': 'month', 'label': 'Last Month', 'selected': period_filter == 'month'},
        {'value': 'all', 'label': 'All Time', 'selected': period_filter == 'all'}
    ])

    builder.add_hidden_field('tab', 'matches')
    builder.set_empty_state('🔍', 'No matches found', 'Try adjusting your filters')

    # Get data
    result = db.get_match_history(page, 50, period_filter)

    # Create table columns
    columns = [
        TableColumn('time', 'Time'),
        TableColumn('ha_song', 'HA Song'),
        TableColumn('youtube_match', 'YouTube Match'),
        TableColumn('duration', 'Duration', width='80px'),
        TableColumn('plays', 'Plays', width='70px')
    ]

    # Create table rows
    rows = []
    for match in result['matches']:
        # Format time
        activity_timestamp = match.get('date_last_played') or match.get('yt_match_last_attempt') or match.get('date_added')
        time_ago = format_relative_time(activity_timestamp) if activity_timestamp else 'Unknown'

        # Format HA song info
        ha_title = match.get('ha_title', 'Unknown').strip() or 'Unknown'
        ha_artist = match.get('ha_artist', 'Unknown').strip() or 'Unknown'
        ha_song_html = format_song_display(ha_title, ha_artist)

        # Format YouTube match info
        yt_title = match.get('yt_title', 'Unknown').strip() or 'Unknown'
        yt_channel = match.get('yt_channel', 'Unknown').strip() or 'Unknown'
        video_id = match.get('yt_video_id')
        yt_published_at = match.get('yt_published_at')
        yt_published_formatted = None
        if yt_published_at:
            try:
                from datetime import datetime
                if isinstance(yt_published_at, str):
                    pub_dt = datetime.fromisoformat(yt_published_at.replace('Z', '+00:00'))
                else:
                    pub_dt = yt_published_at
                yt_published_formatted = pub_dt.strftime('%b %d, %Y')
            except (ValueError, TypeError, AttributeError):
                yt_published_formatted = None

        yt_link = f'<a href="https://www.youtube.com/watch?v={video_id}" target="_blank" style="color: #2563eb; text-decoration: none; font-weight: 500;">{yt_title}</a>'
        yt_details = f'<span style="font-size: 0.85em; color: #64748b;">{yt_channel}'
        if yt_published_formatted:
            yt_details += f' • {yt_published_formatted}'
        yt_details += '</span>'
        yt_match_html = f'{yt_link}<br>{yt_details}'

        # Format duration
        ha_duration = match.get('ha_duration', 0)
        yt_duration = match.get('yt_duration', 0)
        duration_diff = yt_duration - ha_duration
        match_quality = 'good' if abs(duration_diff) <= 2 else 'fair'
        duration_color = '#10b981' if match_quality == 'good' else '#f59e0b'

        duration_html = f'<span style="color: #64748b;">{ha_duration}s</span> → <span style="color: #64748b;">{yt_duration}s</span><br>'
        duration_html += f'<span style="font-size: 0.85em; color: {duration_color};">'
        duration_html += f"{'+'if duration_diff > 0 else ''}{duration_diff}s"
        if match_quality == 'good':
            duration_html += ' ✓'
        duration_html += '</span>'

        cells = [
            TableCell(time_ago),
            TableCell(f'{ha_title} - {ha_artist}', ha_song_html),
            TableCell(yt_title, yt_match_html),
            TableCell(f'{ha_duration}s → {yt_duration}s', duration_html, style='text-align: center;'),
            TableCell(match.get('play_count', 0), style='text-align: center;')
        ]
        rows.append(TableRow(cells))

    # Set table and pagination
    builder.set_table(columns, rows)

    total_count = result['total_count']
    total_pages = result['total_pages']
    page_numbers = generate_page_numbers(page, total_pages)

    builder.set_pagination(
        page,
        total_pages,
        page_numbers,
        '/logs',
        {'tab': 'matches', 'period': period_filter}
    )

    builder.set_status_message(
        f"Showing {len(result['matches'])} of {total_count} matches • Page {page}/{total_pages}"
    )

    return builder.build()


def _create_errors_page(page: int, period_filter: str, ingress_path: str, db):
    """Create page config and table data for errors."""
    # Get filters
    level_filter = request.args.get('level', 'all')
    if level_filter not in ['ERROR', 'WARNING', 'INFO', 'all']:
        level_filter = 'all'

    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('errors', ingress_path)

    # Add filters
    builder.add_filter('period', 'Time Period', [
        {'value': 'hour', 'label': 'Last Hour', 'selected': period_filter == 'hour'},
        {'value': 'day', 'label': 'Last Day', 'selected': period_filter == 'day'},
        {'value': 'week', 'label': 'Last Week', 'selected': period_filter == 'week'},
        {'value': 'month', 'label': 'Last Month', 'selected': period_filter == 'month'},
        {'value': 'all', 'label': 'All Time', 'selected': period_filter == 'all'}
    ])

    builder.add_filter('level', 'Level', [
        {'value': 'all', 'label': 'All', 'selected': level_filter == 'all'},
        {'value': 'ERROR', 'label': 'ERROR', 'selected': level_filter == 'ERROR'},
        {'value': 'WARNING', 'label': 'WARNING', 'selected': level_filter == 'WARNING'},
        {'value': 'INFO', 'label': 'INFO', 'selected': level_filter == 'INFO'}
    ])

    builder.add_hidden_field('tab', 'errors')
    builder.set_empty_state('✓', 'No errors found', 'System is running smoothly!')

    # Get data
    result = parse_error_log(period_filter, level_filter, page, 50)

    # Create table columns
    columns = [
        TableColumn('time', 'Time'),
        TableColumn('level', 'Level'),
        TableColumn('message', 'Message')
    ]

    # Create table rows
    rows = []
    for error in result.get('errors', []):
        # Format time
        time_ago = format_relative_time(error['timestamp'])

        # Format level badge
        level = error['level']
        if level == 'ERROR':
            level_html = format_badge(level, 'error')
        elif level == 'WARNING':
            level_html = format_badge(level, 'warning')
        elif level == 'INFO':
            level_html = format_badge(level, 'info')
        else:
            level_html = format_badge(level, 'info')

        # Format message with truncation
        message = error['message']
        truncated = len(message) > 150
        if truncated:
            display_message = message[:150] + '...'
            message_html = f'<div>{display_message}</div><button onclick="showFullMessage(this)" style="color: #2563eb; background: none; border: none; cursor: pointer; font-size: 0.8em;">Show more</button><div style="display: none;">{message}</div>'
        else:
            message_html = message

        cells = [
            TableCell(error['timestamp'], f'<span title="{time_ago}">{error["timestamp"]}</span>'),
            TableCell(level, level_html),
            TableCell(message, message_html)
        ]
        rows.append(TableRow(cells))

    # Set table and pagination
    builder.set_table(columns, rows)

    total_count = result.get('total_count', 0)
    total_pages = result.get('total_pages', 0)
    page_numbers = generate_page_numbers(page, total_pages)

    builder.set_pagination(
        page,
        total_pages,
        page_numbers,
        '/logs',
        {'tab': 'errors', 'period': period_filter, 'level': level_filter}
    )

    builder.set_status_message(
        f"Showing {len(result.get('errors', []))} of {total_count} errors • Page {page}/{total_pages}"
    )

    # Add custom JS for message expansion
    builder.set_custom_js('''
        function showFullMessage(btn) {
            const container = btn.parentNode;
            const shortMsg = container.firstChild;
            const fullMsg = container.lastChild;

            if (fullMsg.style.display === 'none') {
                shortMsg.style.display = 'none';
                fullMsg.style.display = 'block';
                btn.textContent = 'Show less';
            } else {
                shortMsg.style.display = 'block';
                fullMsg.style.display = 'none';
                btn.textContent = 'Show more';
            }
        }
    ''')

    return builder.build()


def _create_recent_page(ingress_path: str, db):
    """Create page config and table data for recent videos."""
    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('recent', ingress_path)
    builder.set_empty_state('📭', 'No Videos Yet', 'No videos have been added to the database yet.')

    # Get data
    videos = db.get_recently_added(limit=25)

    # Create table columns
    columns = [
        TableColumn('date_added', 'Date Added', width='15%'),
        TableColumn('title', 'Title', width='25%'),
        TableColumn('artist', 'Artist', width='15%'),
        TableColumn('channel', 'Channel', width='20%'),
        TableColumn('rating', 'Rating', width='10%'),
        TableColumn('plays', 'Plays', width='10%'),
        TableColumn('link', 'Link', width='5%')
    ]

    # Create table rows
    rows = []
    for video in videos:
        # Format relative time for date_added
        date_added = video.get('date_added')
        time_ago = format_relative_time(date_added) if date_added else 'unknown'

        # Format rating
        rating = video.get('rating')
        if rating == 'like':
            rating_html = format_badge('👍 Like', 'success')
        elif rating == 'dislike':
            rating_html = format_badge('👎 Dislike', 'error')
        else:
            rating_html = format_badge('- None', 'default')

        # Format link
        yt_url = video.get('yt_url')
        link_html = '<a href="{}" target="_blank" style="color: #2563eb; text-decoration: none; font-size: 1.2em;" title="Watch on YouTube">🔗</a>'.format(yt_url) if yt_url else '-'

        cells = [
            TableCell(time_ago, f'<span title="{date_added or "Unknown"}">{time_ago}</span>'),
            TableCell(video.get('ha_title') or video.get('yt_title') or 'Unknown',
                     f'<span style="font-weight: 500;">{video.get("ha_title") or video.get("yt_title") or "Unknown"}</span>'),
            TableCell(video.get('ha_artist') or '-'),
            TableCell(video.get('yt_channel') or '-'),
            TableCell(rating or 'None', rating_html),
            TableCell(video.get('play_count', 0), style='text-align: center;'),
            TableCell('Link' if yt_url else '-', link_html, style='text-align: center;')
        ]
        rows.append(TableRow(cells))

    # Set table and status
    builder.set_table(columns, rows)
    builder.set_status_message(f"Showing {len(videos)} recently added videos")

    return builder.build()
