"""
Helper functions for logs routes.

Consolidated from logs_routes_page_creators.py and logs_routes_queue_helpers.py.
Contains all page creator functions for both log viewer tabs and queue monitor tabs.
"""

from typing import Tuple, Dict, Any
from flask import request
from helpers.pagination_helpers import generate_page_numbers
from helpers.time_helpers import format_relative_time, format_absolute_timestamp
from helpers.video_helpers import get_video_title, get_video_artist
from helpers.template import (
    PageConfig, TableData, TableColumn, TableRow, TableCell,
    format_badge, format_time_ago, truncate_text,
    format_song_display, format_status_badge,
    format_rating_badge, format_log_level_badge,
    create_period_filter, create_rating_filter,
    add_queue_tabs, format_count_message
)
from helpers.page_builder import LogsPageBuilder
from helpers.log_parsers import parse_error_log


# ============================================================================
# LOG VIEWER PAGE CREATORS (Rated Songs, Matches, Errors, Recent)
# ============================================================================

def _create_rated_songs_page(page: int, period_filter: str, ingress_path: str, db):
    """Create page config and table data for rated songs."""
    # Get filters
    rating_filter = request.args.get('rating', 'all')
    if rating_filter not in ['like', 'dislike', 'all']:
        rating_filter = 'all'

    # Server-side sorting support
    sort_by = request.args.get('sort_by', 'time')
    sort_dir = request.args.get('sort_dir', 'desc')

    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('rated', ingress_path)

    # Add filters (using helpers to consolidate repeated patterns)
    period_opts = create_period_filter(period_filter)
    builder.add_filter(period_opts['name'], period_opts['label'], period_opts['options'])

    # Custom rating filter options for this page
    builder.add_filter('rating', 'Rating Type', [
        {'value': 'all', 'label': 'All', 'selected': rating_filter == 'all'},
        {'value': 'like', 'label': 'Likes', 'selected': rating_filter == 'like'},
        {'value': 'dislike', 'label': 'Dislikes', 'selected': rating_filter == 'dislike'}
    ])

    builder.add_hidden_field('tab', 'rated')
    builder.set_empty_state('📭', 'No rated songs found', 'Try adjusting your filters')

    # Get data
    result = db.get_rated_songs(page, 50, period_filter, rating_filter)

    # Map sort columns to data keys
    sort_key_map = {
        'time': 'date_last_played',
        'song': 'ha_title',
        'artist': 'ha_artist',
        'rating': 'rating',
        'plays': 'play_count',
        'video_id': 'yt_video_id'
    }

    sort_key = sort_key_map.get(sort_by, 'date_last_played')
    reverse = (sort_dir == 'desc')

    # Sort the songs
    if sort_key == 'play_count':
        result['songs'].sort(key=lambda x: int(x.get(sort_key) or 0), reverse=reverse)
    else:
        result['songs'].sort(key=lambda x: (x.get(sort_key) or '').lower() if isinstance(x.get(sort_key), str) else (x.get(sort_key) or ''), reverse=reverse)

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

        # Format rating (using helper to consolidate repeated pattern)
        rating = song.get('rating')
        rating_html = format_rating_badge(rating)

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
    # Server-side sorting support
    sort_by = request.args.get('sort_by', 'time')
    sort_dir = request.args.get('sort_dir', 'desc')

    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('matches', ingress_path)

    # Add period filter (using helper to consolidate repeated pattern)
    period_opts = create_period_filter(period_filter)
    builder.add_filter(period_opts['name'], period_opts['label'], period_opts['options'])

    builder.add_hidden_field('tab', 'matches')
    builder.set_empty_state('🔍', 'No matches found', 'Try adjusting your filters')

    # Get data
    result = db.get_match_history(page, 50, period_filter)

    # Map sort columns to data keys
    sort_key_map = {
        'time': 'date_last_played',
        'ha_song': 'ha_title',
        'youtube_match': 'yt_title',
        'duration': 'yt_duration',
        'plays': 'play_count'
    }

    sort_key = sort_key_map.get(sort_by, 'date_last_played')
    reverse = (sort_dir == 'desc')

    # Sort the matches
    if sort_key in ['play_count', 'yt_duration']:
        result['matches'].sort(key=lambda x: int(x.get(sort_key) or 0), reverse=reverse)
    else:
        result['matches'].sort(key=lambda x: (x.get(sort_key) or '').lower() if isinstance(x.get(sort_key), str) else (x.get(sort_key) or ''), reverse=reverse)

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

    # Server-side sorting support
    sort_by = request.args.get('sort_by', 'time')
    sort_dir = request.args.get('sort_dir', 'desc')

    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('errors', ingress_path)

    # Add filters (using helper to consolidate repeated pattern)
    period_opts = create_period_filter(period_filter)
    builder.add_filter(period_opts['name'], period_opts['label'], period_opts['options'])

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

    # Map sort columns to data keys
    sort_key_map = {
        'time': 'timestamp',
        'level': 'level',
        'message': 'message'
    }

    sort_key = sort_key_map.get(sort_by, 'timestamp')
    reverse = (sort_dir == 'desc')

    # Sort the errors
    result['errors'].sort(key=lambda x: x.get(sort_key) or '', reverse=reverse)

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

        # Format level badge (using helper to consolidate repeated pattern)
        level = error['level']
        level_html = format_log_level_badge(level)

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
    # Server-side sorting support
    sort_by = request.args.get('sort_by', 'date_added')
    sort_dir = request.args.get('sort_dir', 'desc')

    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('recent', ingress_path)
    builder.set_empty_state('📭', 'No Videos Yet', 'No videos have been added to the database yet.')

    # Get data
    videos = db.get_recently_added(limit=25)

    # Map sort columns to data keys
    sort_key_map = {
        'date_added': 'date_added',
        'title': 'ha_title',
        'artist': 'ha_artist',
        'channel': 'yt_channel',
        'rating': 'rating',
        'plays': 'play_count',
        'link': 'yt_url'
    }

    sort_key = sort_key_map.get(sort_by, 'date_added')
    reverse = (sort_dir == 'desc')

    # Sort the videos
    if sort_key == 'play_count':
        videos.sort(key=lambda x: int(x.get(sort_key) or 0), reverse=reverse)
    else:
        videos.sort(key=lambda x: (x.get(sort_key) or '').lower() if isinstance(x.get(sort_key), str) else (x.get(sort_key) or ''), reverse=reverse)

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

        # Format rating (using helper to consolidate repeated pattern)
        rating = video.get('rating')
        rating_html = format_rating_badge(rating)

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


# ============================================================================
# QUEUE MONITOR PAGE CREATORS (Pending, History, Errors, Statistics)
# ============================================================================

def format_queue_item(item, db):
    """
    Format a queue item for display in tables.

    Args:
        item: Queue item dict from database
        db: Database instance for lookups

    Returns:
        Formatted item dict or None if invalid
    """
    payload = item.get('payload', {})

    if item['type'] == 'search':
        ha_media = payload
        callback_rating = ha_media.get('callback_rating')

        return {
            'type': 'search',
            'id': str(item['id']),
            'ha_title': ha_media.get('ha_title', 'Unknown'),
            'ha_artist': ha_media.get('ha_artist'),
            'operation': 'Search for YouTube match',
            'callback': f"then rate {callback_rating}" if callback_rating else None,
            'requested_at': format_absolute_timestamp(item.get('requested_at')),
            'completed_at': format_absolute_timestamp(item.get('completed_at')),
            'last_attempt': format_absolute_timestamp(item.get('last_attempt')),
            'attempts': item.get('attempts', 0),
            'last_error': item.get('last_error'),
            'status': item.get('status'),
            'yt_video_id': None
        }

    elif item['type'] == 'rating':
        yt_video_id = payload.get('yt_video_id')
        rating = payload.get('rating')
        video = db.get_video(yt_video_id) if yt_video_id else None

        return {
            'type': 'rating',
            'id': str(item['id']),
            'ha_title': video.get('ha_title', 'Unknown') if video else 'Unknown',
            'ha_artist': video.get('ha_artist') if video else None,
            'operation': f"Rate as {rating}",
            'callback': None,
            'requested_at': format_absolute_timestamp(item.get('requested_at')),
            'completed_at': format_absolute_timestamp(item.get('completed_at')),
            'last_attempt': format_absolute_timestamp(item.get('last_attempt')),
            'attempts': item.get('attempts', 0),
            'last_error': item.get('last_error'),
            'status': item.get('status'),
            'yt_video_id': yt_video_id
        }
    return None


def _create_queue_pending_tab(ingress_path: str, current_tab: str, db) -> Tuple[PageConfig, TableData, str]:
    """Create page configuration for Pending queue tab."""
    # Create page config with sub-tabs
    page_config = PageConfig(
        title='📊 Queue Monitor',
        nav_active='queue',
        storage_key='queue-pending'
    )

    # Add sub-tabs (using helper to consolidate repeated pattern)
    add_queue_tabs(page_config, current_tab, ingress_path)

    # Set empty state
    page_config.set_empty_state('✓', 'Queue is empty', 'No operations waiting to be processed.')

    # Add row click handler for navigation
    page_config.custom_js = f'''
        document.querySelectorAll('.clickable-row').forEach(row => {{
            row.style.cursor = 'pointer';
            row.addEventListener('click', function() {{
                const rowId = this.dataset.rowId;
                window.location.href = '{ingress_path}/logs/pending-ratings/item/' + rowId;
            }});
        }});
    '''

    # Get pending AND failed items (failed items can be retried)
    # Pending tab shows all items that need attention: pending to be processed, or failed awaiting retry
    with db._lock:
        cursor = db._conn.execute("""
            SELECT * FROM queue
            WHERE status IN ('pending', 'failed')
            ORDER BY
                CASE
                    WHEN status = 'pending' THEN 1
                    WHEN status = 'failed' THEN 2
                END,
                priority ASC,
                requested_at ASC
            LIMIT ?
        """, (1000,))
        pending_items = [dict(row) for row in cursor.fetchall()]

    formatted_items = [format_queue_item(item, db) for item in pending_items]
    formatted_items = [item for item in formatted_items if item]

    # Server-side sorting support
    sort_by = request.args.get('sort_by', 'queued')
    sort_dir = request.args.get('sort_dir', 'desc')

    # Map column keys to item keys
    sort_key_map = {
        'title': 'ha_title',
        'artist': 'ha_artist',
        'operation': 'operation',
        'queued': 'requested_at',
        'attempts': 'attempts',
        'status': 'last_error'
    }

    sort_key = sort_key_map.get(sort_by, 'requested_at')
    reverse = (sort_dir == 'desc')

    # Sort items
    if sort_key == 'attempts':
        formatted_items.sort(key=lambda x: int(x.get(sort_key) or 0), reverse=reverse)
    else:
        formatted_items.sort(key=lambda x: x.get(sort_key) or '', reverse=reverse)

    # Create table columns
    columns = [
        TableColumn('title', 'Title', width='25%'),
        TableColumn('artist', 'Artist', width='20%'),
        TableColumn('operation', 'Operation', width='25%'),
        TableColumn('queued', 'Queued At', width='15%'),
        TableColumn('attempts', 'Attempts', width='10%'),
        TableColumn('status', 'Status', width='15%')
    ]

    # Create table rows
    rows = []
    for item in formatted_items:
        # Operation with type indicator and callback
        # Add type emoji to operation for visual clarity
        type_emoji = '🔍' if item['type'] == 'search' else '⭐'
        operation_html = f"<strong>{type_emoji} {item['operation']}</strong>"
        if item.get('callback'):
            operation_html += f'<br><span style="font-size: 0.85em; color: #64748b;">{item["callback"]}</span>'

        # Status
        if item.get('last_error'):
            error_msg = truncate_text(item["last_error"], max_length=50, suffix='...')
            status_html = f'<span style="color: #ef4444; font-size: 0.9em;">{error_msg}</span>'
        else:
            status_html = format_badge('Pending', 'info')

        cells = [
            TableCell(item['ha_title']),
            TableCell(item.get('ha_artist') or '—'),
            TableCell(item['operation'], operation_html),
            TableCell(item['requested_at'] or '—'),
            TableCell(str(item['attempts']), f'<span style="text-align: center; display: block;">{item["attempts"]}</span>'),
            TableCell(item.get('last_error') or 'Pending', status_html)
        ]
        rows.append(TableRow(cells, clickable=True, row_id=item['id']))

    table_data = TableData(columns, rows)

    # Use helper for consistent count message formatting
    count_msg = format_count_message(len(formatted_items), 'operation', 'in queue')
    status_message = f"Operations waiting to be processed by the background worker. The worker processes one item per minute to respect API quotas and rate limits. {count_msg}"

    return page_config, table_data, status_message


def _create_queue_history_tab(ingress_path: str, current_tab: str, db) -> Tuple[PageConfig, TableData, str]:
    """Create page configuration for History queue tab."""
    # Create page config with sub-tabs
    page_config = PageConfig(
        title='📊 Queue Monitor',
        nav_active='queue',
        storage_key='queue-history'
    )

    # Add sub-tabs (using helper to consolidate repeated pattern)
    add_queue_tabs(page_config, current_tab, ingress_path)

    # Set empty state
    page_config.set_empty_state('📭', 'No history available', 'No recently completed operations.')

    # Add row click handler for navigation
    page_config.custom_js = f'''
        document.querySelectorAll('.clickable-row').forEach(row => {{
            row.style.cursor = 'pointer';
            row.addEventListener('click', function() {{
                const rowId = this.dataset.rowId;
                window.location.href = '{ingress_path}/logs/pending-ratings/item/' + rowId;
            }});
        }});
    '''

    # Get history items
    history_items = db.list_queue_history(limit=200)
    formatted_items = [format_queue_item(item, db) for item in history_items]
    formatted_items = [item for item in formatted_items if item]

    # Server-side sorting support
    sort_by = request.args.get('sort_by', 'completed')
    sort_dir = request.args.get('sort_dir', 'desc')

    # Map column keys to item keys
    sort_key_map = {
        'type': 'type',
        'title': 'ha_title',
        'artist': 'ha_artist',
        'operation': 'operation',
        'queued': 'requested_at',
        'completed': 'completed_at',
        'duration': 'completed_at',  # Not calculated, sort by completion time
        'status': 'status'
    }

    sort_key = sort_key_map.get(sort_by, 'completed_at')
    reverse = (sort_dir == 'desc')

    # Sort items
    formatted_items.sort(key=lambda x: x.get(sort_key) or '', reverse=reverse)

    # Create table columns
    columns = [
        TableColumn('type', 'Type', width='10%'),
        TableColumn('title', 'Title', width='20%'),
        TableColumn('artist', 'Artist', width='12%'),
        TableColumn('operation', 'Operation', width='18%'),
        TableColumn('queued', 'Queued At', width='13%'),
        TableColumn('completed', 'Completed', width='13%'),
        TableColumn('duration', 'Duration', width='7%'),
        TableColumn('status', 'Status', width='7%')
    ]

    # Create table rows
    rows = []
    for item in formatted_items:
        # Type badge
        if item['type'] == 'search':
            type_html = format_badge('🔍 Search', 'info')
        else:
            type_html = format_badge('⭐ Rating', 'info')

        # Status badge
        if item['status'] == 'completed':
            status_html = format_badge('✓ Completed', 'success')
        else:
            status_html = format_badge('✗ Failed', 'error')

        cells = [
            TableCell(item['type'], type_html),
            TableCell(item['ha_title']),
            TableCell(item.get('ha_artist') or '—'),
            TableCell(item['operation']),
            TableCell(item['requested_at'] or '—'),
            TableCell(item['completed_at'] or '—'),
            TableCell('—'),  # Duration not calculated
            TableCell(item['status'], status_html)
        ]
        rows.append(TableRow(cells, clickable=True, row_id=item['id']))

    table_data = TableData(columns, rows)

    # Use helper for consistent count message formatting
    count_msg = format_count_message(len(formatted_items), 'recent operation')
    status_message = f"Recently completed and failed operations. Shows the last 200 processed items. {count_msg}"

    return page_config, table_data, status_message


def _create_queue_errors_tab(ingress_path: str, current_tab: str, db) -> Tuple[PageConfig, TableData, str]:
    """Create page configuration for Errors queue tab."""
    # Create page config with sub-tabs
    page_config = PageConfig(
        title='📊 Queue Monitor',
        nav_active='queue',
        storage_key='queue-errors'
    )

    # Add sub-tabs (using helper to consolidate repeated pattern)
    add_queue_tabs(page_config, current_tab, ingress_path)

    # Set empty state
    page_config.set_empty_state('✓', 'No errors', 'All operations completing successfully.')

    # Add row click handler for navigation
    page_config.custom_js = f'''
        document.querySelectorAll('.clickable-row').forEach(row => {{
            row.style.cursor = 'pointer';
            row.addEventListener('click', function() {{
                const rowId = this.dataset.rowId;
                window.location.href = '{ingress_path}/logs/pending-ratings/item/' + rowId;
            }});
        }});
    '''

    # Get error items
    error_items = db.list_queue_failed(limit=200)
    formatted_items = [format_queue_item(item, db) for item in error_items]
    formatted_items = [item for item in formatted_items if item]

    # Server-side sorting support
    sort_by = request.args.get('sort_by', 'last_attempt')
    sort_dir = request.args.get('sort_dir', 'desc')

    # Map column keys to item keys
    sort_key_map = {
        'type': 'type',
        'title': 'ha_title',
        'artist': 'ha_artist',
        'operation': 'operation',
        'last_attempt': 'last_attempt',
        'attempts': 'attempts',
        'error': 'last_error'
    }

    sort_key = sort_key_map.get(sort_by, 'last_attempt')
    reverse = (sort_dir == 'desc')

    # Sort items
    if sort_key == 'attempts':
        formatted_items.sort(key=lambda x: int(x.get(sort_key) or 0), reverse=reverse)
    else:
        formatted_items.sort(key=lambda x: x.get(sort_key) or '', reverse=reverse)

    # Create table columns
    columns = [
        TableColumn('type', 'Type', width='10%'),
        TableColumn('title', 'Title', width='20%'),
        TableColumn('artist', 'Artist', width='12%'),
        TableColumn('operation', 'Operation', width='15%'),
        TableColumn('last_attempt', 'Last Attempt', width='13%'),
        TableColumn('attempts', 'Attempts', width='10%'),
        TableColumn('error', 'Error Message', width='20%')
    ]

    # Create table rows
    rows = []
    for item in formatted_items:
        # Type badge
        if item['type'] == 'search':
            type_html = format_badge('🔍 Search', 'info')
        else:
            type_html = format_badge('⭐ Rating', 'info')

        # Error message truncated
        error_msg = item.get('last_error') or 'Unknown error'
        error_msg_short = truncate_text(error_msg, max_length=100, suffix='...')
        error_html = f'<span style="color: #ef4444; font-size: 0.9em;">{error_msg_short}</span>'

        cells = [
            TableCell(item['type'], type_html),
            TableCell(item['ha_title']),
            TableCell(item.get('ha_artist') or '—'),
            TableCell(item['operation']),
            TableCell(item.get('last_attempt') or item.get('requested_at') or '—'),
            TableCell(str(item['attempts']), f'<span style="text-align: center; display: block;">{item["attempts"]}</span>'),
            TableCell(error_msg, error_html)
        ]
        rows.append(TableRow(cells, clickable=True, row_id=item['id']))

    table_data = TableData(columns, rows)

    # Use helper for consistent count message formatting
    count_msg = format_count_message(len(formatted_items), 'failed operation')
    status_message = f"Failed operations with detailed error messages. Helps identify recurring issues. {count_msg}"

    return page_config, table_data, status_message


def _create_queue_statistics_tab(ingress_path: str, current_tab: str, db) -> Tuple[PageConfig, TableData, str, Dict[str, Any]]:
    """Create page configuration for Statistics queue tab."""
    # Create page config with sub-tabs
    page_config = PageConfig(
        title='📊 Queue Monitor',
        nav_active='queue',
        storage_key='queue-statistics'
    )

    # Add sub-tabs (using helper to consolidate repeated pattern)
    add_queue_tabs(page_config, current_tab, ingress_path)

    # Get queue statistics
    statistics = db.get_queue_statistics()

    # Build summary stats for display
    summary_stats = {}

    if statistics and statistics.get('overall_queue'):
        overall = statistics['overall_queue']
        rating_queue = statistics.get('rating_queue', {})
        search_queue = statistics.get('search_queue', {})

        # Main stats for overall queue
        main_stats = [
            {'label': 'Total Items', 'value': overall.get('total', 0)},
            {'label': 'Pending', 'value': overall.get('pending', 0), 'style': 'color: #f59e0b;'},
            {'label': 'Processing', 'value': overall.get('processing', 0), 'style': 'color: #3b82f6;'},
            {'label': 'Completed', 'value': overall.get('completed', 0), 'style': 'color: #16a34a;'},
            {'label': 'Failed', 'value': overall.get('failed', 0), 'style': 'color: #dc2626;'}
        ]

        summary_stats['main_stats'] = main_stats

        # Breakdowns for rating and search queues
        breakdowns = []

        if rating_queue:
            rating_breakdown = {
                'title': '⭐ Rating Queue',
                'rows': [
                    {'label': 'Pending', 'count': rating_queue.get('pending', 0), 'count_suffix': ''},
                    {'label': 'Processed (24h)', 'count': rating_queue.get('processed_24h', 0), 'count_suffix': ''},
                    {'label': 'Success Rate (24h)', 'count': f"{rating_queue.get('success_rate_24h', 0)}%", 'count_suffix': ''}
                ]
            }
            breakdowns.append(rating_breakdown)

        if search_queue:
            search_breakdown = {
                'title': '🔍 Search Queue',
                'rows': [
                    {'label': 'Total', 'count': search_queue.get('total', 0), 'count_suffix': ''},
                    {'label': 'Pending', 'count': search_queue.get('pending', 0), 'count_suffix': ''},
                    {'label': 'Processed (24h)', 'count': search_queue.get('processed_24h', 0), 'count_suffix': ''},
                    {'label': 'Success Rate (24h)', 'count': f"{search_queue.get('success_rate_24h', 0)}%", 'count_suffix': ''}
                ]
            }
            breakdowns.append(search_breakdown)

        summary_stats['breakdowns'] = breakdowns

    status_message = "Queue performance metrics and operational statistics."

    return page_config, None, status_message, summary_stats
