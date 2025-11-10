"""
Helper functions for queue tab pages.

These functions create page configurations for the Queue Monitor tabs:
- Pending: Items waiting to be processed
- History: Recently completed/failed items
- Errors: Failed items with error details
- Statistics: Queue performance metrics
"""

from typing import Tuple, Dict, Any
from helpers.template_helpers import PageConfig, TableData, TableColumn, TableRow, TableCell, format_badge
from helpers.time_helpers import format_absolute_timestamp


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

    # Add sub-tabs
    page_config.add_sub_tab('Pending', '/logs/pending-ratings?tab=pending', current_tab == 'pending')
    page_config.add_sub_tab('History', '/logs/pending-ratings?tab=history', current_tab == 'history')
    page_config.add_sub_tab('Errors', '/logs/pending-ratings?tab=errors', current_tab == 'errors')
    page_config.add_sub_tab('Statistics', '/logs/pending-ratings?tab=statistics', current_tab == 'statistics')

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

    # Get pending items
    pending_items = db.list_pending_queue_items(limit=1000)
    formatted_items = [format_queue_item(item, db) for item in pending_items]
    formatted_items = [item for item in formatted_items if item]
    formatted_items.sort(key=lambda x: x.get('requested_at') or '', reverse=True)

    # Create table columns
    columns = [
        TableColumn('type', 'Type', width='10%'),
        TableColumn('title', 'Title', width='20%'),
        TableColumn('artist', 'Artist', width='15%'),
        TableColumn('operation', 'Operation', width='20%'),
        TableColumn('queued', 'Queued At', width='15%'),
        TableColumn('attempts', 'Attempts', width='10%'),
        TableColumn('status', 'Status', width='10%')
    ]

    # Create table rows
    rows = []
    for item in formatted_items:
        # Type badge
        if item['type'] == 'search':
            type_html = '<span style="color: #3b82f6;">🔍 Search</span>'
        else:
            type_html = '<span style="color: #8b5cf6;">⭐ Rating</span>'

        # Operation with callback
        operation_html = f"<strong>{item['operation']}</strong>"
        if item.get('callback'):
            operation_html += f'<br><span style="font-size: 0.85em; color: #64748b;">{item["callback"]}</span>'

        # Status
        if item.get('last_error'):
            status_html = f'<span style="color: #ef4444; font-size: 0.9em;">{item["last_error"][:50]}...</span>'
        else:
            status_html = '<span style="color: #10b981;">Pending</span>'

        cells = [
            TableCell(item['type'], type_html),
            TableCell(item['ha_title']),
            TableCell(item.get('ha_artist') or '—'),
            TableCell(item['operation'], operation_html),
            TableCell(item['requested_at'] or '—'),
            TableCell(str(item['attempts']), f'<span style="text-align: center; display: block;">{item["attempts"]}</span>'),
            TableCell(item.get('last_error') or 'Pending', status_html)
        ]
        rows.append(TableRow(cells, clickable=True, row_id=item['id']))

    table_data = TableData(columns, rows)

    status_message = f"Operations waiting to be processed by the background worker. The worker processes one item per minute to respect API quotas and rate limits. <strong>{len(formatted_items)} operation{'s' if len(formatted_items) != 1 else ''} in queue</strong>"

    return page_config, table_data, status_message


def _create_queue_history_tab(ingress_path: str, current_tab: str, db) -> Tuple[PageConfig, TableData, str]:
    """Create page configuration for History queue tab."""
    # Create page config with sub-tabs
    page_config = PageConfig(
        title='📊 Queue Monitor',
        nav_active='queue',
        storage_key='queue-history'
    )

    # Add sub-tabs
    page_config.add_sub_tab('Pending', '/logs/pending-ratings?tab=pending', current_tab == 'pending')
    page_config.add_sub_tab('History', '/logs/pending-ratings?tab=history', current_tab == 'history')
    page_config.add_sub_tab('Errors', '/logs/pending-ratings?tab=errors', current_tab == 'errors')
    page_config.add_sub_tab('Statistics', '/logs/pending-ratings?tab=statistics', current_tab == 'statistics')

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
            type_html = '<span style="color: #3b82f6;">🔍 Search</span>'
        else:
            type_html = '<span style="color: #8b5cf6;">⭐ Rating</span>'

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

    status_message = f"Recently completed and failed operations. Shows the last 200 processed items. <strong>{len(formatted_items)} recent operation{'s' if len(formatted_items) != 1 else ''}</strong>"

    return page_config, table_data, status_message


def _create_queue_errors_tab(ingress_path: str, current_tab: str, db) -> Tuple[PageConfig, TableData, str]:
    """Create page configuration for Errors queue tab."""
    # Create page config with sub-tabs
    page_config = PageConfig(
        title='📊 Queue Monitor',
        nav_active='queue',
        storage_key='queue-errors'
    )

    # Add sub-tabs
    page_config.add_sub_tab('Pending', '/logs/pending-ratings?tab=pending', current_tab == 'pending')
    page_config.add_sub_tab('History', '/logs/pending-ratings?tab=history', current_tab == 'history')
    page_config.add_sub_tab('Errors', '/logs/pending-ratings?tab=errors', current_tab == 'errors')
    page_config.add_sub_tab('Statistics', '/logs/pending-ratings?tab=statistics', current_tab == 'statistics')

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
            type_html = '<span style="color: #3b82f6;">🔍 Search</span>'
        else:
            type_html = '<span style="color: #8b5cf6;">⭐ Rating</span>'

        # Error message truncated
        error_msg = item.get('last_error') or 'Unknown error'
        error_html = f'<span style="color: #ef4444; font-size: 0.9em;">{error_msg[:100]}'
        if len(error_msg) > 100:
            error_html += '...'
        error_html += '</span>'

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

    status_message = f"Failed operations with detailed error messages. Helps identify recurring issues. <strong>{len(formatted_items)} failed operation{'s' if len(formatted_items) != 1 else ''}</strong>"

    return page_config, table_data, status_message


def _create_queue_statistics_tab(ingress_path: str, current_tab: str, db) -> Tuple[PageConfig, TableData, str, Dict[str, Any]]:
    """Create page configuration for Statistics queue tab."""
    # Create page config with sub-tabs
    page_config = PageConfig(
        title='📊 Queue Monitor',
        nav_active='queue',
        storage_key='queue-statistics'
    )

    # Add sub-tabs
    page_config.add_sub_tab('Pending', '/logs/pending-ratings?tab=pending', current_tab == 'pending')
    page_config.add_sub_tab('History', '/logs/pending-ratings?tab=history', current_tab == 'history')
    page_config.add_sub_tab('Errors', '/logs/pending-ratings?tab=errors', current_tab == 'errors')
    page_config.add_sub_tab('Statistics', '/logs/pending-ratings?tab=statistics', current_tab == 'statistics')

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
