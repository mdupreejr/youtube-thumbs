"""
Routes for logs viewer page.

Provides endpoints for viewing rated songs, match history, and error logs.
"""

from flask import Blueprint, render_template, request, jsonify
from datetime import datetime, timedelta
from typing import Dict, Any, List
import os
import re
from logger import logger
from helpers.pagination_helpers import generate_page_numbers
from helpers.time_helpers import format_relative_time, parse_timestamp, format_absolute_timestamp
from helpers.validation_helpers import validate_page_param
from helpers.video_helpers import get_video_title, get_video_artist
from helpers.template_helpers import (
    TableData, TableColumn, TableRow, TableCell,
    create_api_calls_page_config,
    format_badge, format_time_ago, truncate_text
)

bp = Blueprint('logs', __name__)

# Global database reference (set by init function)
_db = None


def init_logs_routes(database):
    """
    Initialize logs routes with database reference.

    Args:
        database: Database instance
    """
    global _db
    _db = database


@bp.route('/logs/api-calls')
def api_calls_log():
    """Display detailed YouTube API call logs."""
    ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

    try:
        # Get pagination parameters
        page, error = validate_page_param(request.args)
        if error:
            return error

        # Get filter parameters
        method_filter = request.args.get('method', None)
        success_filter_str = request.args.get('success', None)
        success_filter = None if success_filter_str is None else (success_filter_str.lower() == 'true')

        # Get logs from database
        per_page = 50
        offset = (page - 1) * per_page
        result = _db.get_api_call_log(
            limit=per_page,
            offset=offset,
            method_filter=method_filter if method_filter else None,
            success_filter=success_filter
        )

        # Get summary statistics
        summary = _db.get_api_call_summary(hours=24)

        # Create page configuration
        page_config = create_api_calls_page_config(ingress_path)
        
        # Add filters
        page_config.add_filter('method', 'API Method', [
            {'value': '', 'label': 'All Methods', 'selected': not method_filter},
            {'value': 'search', 'label': 'search', 'selected': method_filter == 'search'},
            {'value': 'videos.list', 'label': 'videos.list', 'selected': method_filter == 'videos.list'}
        ])
        page_config.add_filter('success', 'Status', [
            {'value': '', 'label': 'All', 'selected': success_filter_str is None},
            {'value': 'true', 'label': 'Success', 'selected': success_filter_str == 'true'},
            {'value': 'false', 'label': 'Failed', 'selected': success_filter_str == 'false'}
        ])
        page_config.filter_button_text = 'Apply Filters'

        # Create table data
        columns = [
            TableColumn('time', 'Time'),
            TableColumn('method', 'Method'),
            TableColumn('operation', 'Operation'),
            TableColumn('query', 'Query'),
            TableColumn('quota', 'Quota'),
            TableColumn('status', 'Status'),
            TableColumn('results', 'Results'),
            TableColumn('context', 'Context')
        ]

        rows = []
        for log in result['logs']:
            # Format method badge
            method_html = log.get('api_method', '')
            if method_html == 'search':
                method_html = format_badge('🔍 search', 'info')
            elif method_html == 'videos.list':
                method_html = format_badge('📹 videos.list', 'info')
            else:
                method_html = format_badge(method_html)

            # Format status badge
            status_html = format_badge('✓ Success', 'success') if log.get('success') else format_badge('✗ Failed', 'error')
            
            # Format quota cost
            quota_cost = log.get('quota_cost', 0)
            quota_style = 'color: #dc2626;' if quota_cost >= 100 else 'color: #059669;'
            quota_html = f'<span style="{quota_style}">{quota_cost}</span>'

            # Format query and context
            query_text = truncate_text(log.get('query_params', ''), 80)
            context_text = ''
            if log.get('error_message'):
                context_text = truncate_text(log.get('error_message'), 100)
            elif log.get('context'):
                context_text = truncate_text(log.get('context'), 60)
            else:
                context_text = '-'

            formatted_timestamp = format_absolute_timestamp(log.get('timestamp'))
            cells = [
                TableCell(formatted_timestamp, format_time_ago(formatted_timestamp)),
                TableCell(log.get('api_method', ''), method_html),
                TableCell(log.get('operation_type') or '-'),
                TableCell(query_text if query_text else '-'),
                TableCell(quota_cost, quota_html),
                TableCell('Success' if log.get('success') else 'Failed', status_html),
                TableCell(log.get('results_count') if log.get('results_count') is not None else '-', 
                         style='text-align: center;'),
                TableCell(context_text)
            ]
            rows.append(TableRow(cells))

        table_data = TableData(columns, rows)

        # Create summary statistics
        summary_stats = None
        if summary:
            main_stats = [
                {'label': 'Total Calls (24h)', 'value': summary['summary'].get('total_calls', 0)},
                {'label': 'Quota Used (24h)', 'value': summary['summary'].get('total_quota', 0), 'style': 'color: #dc2626;'},
                {'label': 'Successful Calls', 'value': summary['summary'].get('successful_calls', 0), 'style': 'color: #16a34a;'},
                {'label': 'Failed Calls', 'value': summary['summary'].get('failed_calls', 0), 'style': 'color: #dc2626;'}
            ]
            
            breakdowns = []
            if summary.get('by_method'):
                breakdowns.append({
                    'title': '📌 By API Method',
                    'rows': [
                        {
                            'label': method['api_method'],
                            'count': method['call_count'],
                            'count_suffix': 'calls',
                            'quota': f"{method['quota_used']} quota"
                        }
                        for method in summary['by_method']
                    ]
                })
            
            if summary.get('by_operation'):
                breakdowns.append({
                    'title': '🔧 By Operation Type',
                    'rows': [
                        {
                            'label': op['operation_type'],
                            'count': op['call_count'],
                            'count_suffix': 'calls',
                            'quota': f"{op['quota_used']} quota"
                        }
                        for op in summary['by_operation']
                    ]
                })
            
            summary_stats = {
                'main_stats': main_stats,
                'breakdowns': breakdowns
            }

        # Create pagination
        total_count = result['total_count']
        total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
        page_numbers = generate_page_numbers(page, total_pages)
        
        pagination = {
            'current_page': page,
            'total_pages': total_pages,
            'page_numbers': page_numbers,
            'prev_url': f"/logs/api-calls?page={page-1}" + (f"&method={method_filter}" if method_filter else "") + (f"&success={success_filter_str}" if success_filter_str else ""),
            'next_url': f"/logs/api-calls?page={page+1}" + (f"&method={method_filter}" if method_filter else "") + (f"&success={success_filter_str}" if success_filter_str else ""),
            'page_url_template': f"/logs/api-calls?page=PAGE_NUM" + (f"&method={method_filter}" if method_filter else "") + (f"&success={success_filter_str}" if success_filter_str else "")
        } if total_pages > 1 else None

        # Set empty state
        page_config.set_empty_state('📊', 'No API calls found', 'No API calls have been logged yet, or none match your filters.')

        # Status message
        status_message = f"Showing {len(result['logs'])} of {total_count} API calls • Page {page}/{total_pages}"

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if rows else None,
            summary_stats=summary_stats,
            pagination=pagination,
            status_message=status_message
        )

    except Exception as e:
        logger.error(f"Error displaying API call logs: {e}")
        return "<h1>Error loading API call logs</h1>", 500


@bp.route('/logs/pending-ratings')
def pending_ratings_log():
    """
    Display comprehensive queue viewer with multiple tabs.
    Architecture spec: Pending, History, Errors, Statistics tabs.
    """
    ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
    current_tab = request.args.get('tab', 'pending')

    try:
        # Helper function to format queue items
        def format_queue_item(item):
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
                video = _db.get_video(yt_video_id) if yt_video_id else None

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

        # Fetch data based on tab
        data = {}

        if current_tab == 'pending':
            # Get pending items
            pending_items = _db.list_pending_queue_items(limit=1000)
            data['queue_items'] = [format_queue_item(item) for item in pending_items if format_queue_item(item)]
            data['queue_items'].sort(key=lambda x: x.get('requested_at') or '', reverse=True)

        elif current_tab == 'history':
            # Get completed and failed items
            history_items = _db.list_queue_history(limit=200)
            data['history_items'] = [format_queue_item(item) for item in history_items if format_queue_item(item)]

        elif current_tab == 'errors':
            # Get failed items
            error_items = _db.list_queue_failed(limit=200)
            data['error_items'] = [format_queue_item(item) for item in error_items if format_queue_item(item)]

        elif current_tab == 'statistics':
            # Get queue statistics
            data['statistics'] = _db.get_queue_statistics()
            data['recent_activity'] = _db.get_recent_queue_activity(limit=50)
            data['performance'] = _db.get_queue_performance_metrics(hours=24)

        return render_template(
            'logs_queue.html',
            ingress_path=ingress_path,
            current_tab=current_tab,
            **data
        )

    except Exception as e:
        logger.error(f"Error displaying queue: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return "<h1>Error loading queue</h1>", 500


@bp.route('/api/queue-item/<int:queue_id>')
def get_queue_item_details(queue_id: int):
    """Get full details for a queue item by ID."""
    try:
        # Get queue item from unified queue
        queue_item = _db.get_queue_item_by_id(queue_id)
        if not queue_item:
            logger.error(f"Queue item not found: {queue_id}")
            return jsonify({'success': False, 'error': f'Queue item not found: {queue_id}'}), 404

        payload = queue_item.get('payload', {})
        item_type = queue_item['type']

        if item_type == 'rating':
            # Extract rating info from payload
            yt_video_id = payload.get('yt_video_id')
            rating = payload.get('rating')
            
            # Get video details if available
            video = _db.get_video(yt_video_id) if yt_video_id else None

            # Format the response with all available details
            details = {
                'type': 'rating',
                'queue_id': queue_id,
                'yt_video_id': yt_video_id,
                'ha_title': video.get('ha_title', 'Unknown') if video else 'Unknown',
                'ha_artist': video.get('ha_artist', 'Unknown') if video else 'Unknown',
                'yt_title': video.get('yt_title') if video else None,
                'yt_channel': video.get('yt_channel') if video else None,
                'yt_duration': video.get('yt_duration') if video else None,
                'ha_duration': video.get('ha_duration') if video else None,
                'operation': f"Rate as {rating}",
                'rating': rating,
                'requested_at': queue_item.get('requested_at'),
                'attempts': queue_item.get('attempts', 0),
                'last_attempt': queue_item.get('last_attempt'),
                'last_error': queue_item.get('last_error'),
                'status': queue_item.get('status'),
                'completed_at': queue_item.get('completed_at'),
                'current_rating': video.get('rating') if video else None,
                'play_count': video.get('play_count', 0) if video else 0,
                'date_added': video.get('date_added') if video else None,
                'date_last_played': video.get('date_last_played') if video else None,
                'api_response_data': queue_item.get('api_response_data'),  # v4.0.64: YouTube API debug data
                'payload': payload
            }

            return jsonify({'success': True, 'data': details})

        elif item_type == 'search':
            # Extract search info from payload
            ha_media = payload
            callback_rating = ha_media.get('callback_rating')

            # Try to find if search found a video to get YouTube metadata
            found_video = None
            if queue_item.get('status') == 'completed':
                # Search was completed, try to find the video by title+artist
                try:
                    found_video = _db.find_by_title_and_duration(
                        ha_media.get('ha_title'),
                        ha_media.get('ha_duration')
                    )
                    if not found_video and ha_media.get('ha_artist'):
                        # Try content hash lookup as fallback
                        found_video = _db.find_by_content_hash(
                            ha_media.get('ha_title'),
                            ha_media.get('ha_duration'),
                            ha_media.get('ha_artist')
                        )
                except Exception as e:
                    logger.debug(f"Could not find completed search result for queue {queue_id}: {e}")

            details = {
                'type': 'search',
                'queue_id': queue_id,
                'ha_title': ha_media.get('ha_title', 'Unknown'),
                'ha_artist': ha_media.get('ha_artist', 'Unknown'),
                'ha_album': ha_media.get('ha_album'),
                'ha_duration': ha_media.get('ha_duration'),
                'ha_app_name': ha_media.get('ha_app_name'),
                'operation': 'Search for YouTube match',
                'callback_rating': callback_rating,
                'status': queue_item.get('status'),
                'requested_at': queue_item.get('requested_at'),
                'attempts': queue_item.get('attempts', 0),
                'last_attempt': queue_item.get('last_attempt'),
                'last_error': queue_item.get('last_error'),
                'completed_at': queue_item.get('completed_at'),
                'api_response_data': queue_item.get('api_response_data'),  # v4.0.64: YouTube API debug data
                'payload': payload,
                # Add YouTube metadata if found
                'yt_video_id': found_video.get('yt_video_id') if found_video else None,
                'yt_title': found_video.get('yt_title') if found_video else None,
                'yt_channel': found_video.get('yt_channel') if found_video else None,
                'yt_duration': found_video.get('yt_duration') if found_video else None,
                'yt_url': found_video.get('yt_url') if found_video else None
            }

            return jsonify({'success': True, 'data': details})

        else:
            logger.error(f"Invalid queue item type: {item_type}")
            return jsonify({'success': False, 'error': f'Invalid item type: {item_type}'}), 400

    except Exception as e:
        logger.error(f"Error getting queue item details ({queue_id}): {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': f'Internal server error: {str(e)}'}), 500


def parse_error_log(
    period_filter: str = 'all',
    level_filter: str = 'all',
    page: int = 1,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Parse error log file and return paginated results.

    Args:
        period_filter: Time period ('hour', 'day', 'week', 'month', 'all')
        level_filter: Log level ('ERROR', 'WARNING', 'INFO', 'all')
        page: Page number (1-indexed)
        limit: Number of entries per page

    Returns:
        Dictionary with errors list, pagination info, and total count
    """
    log_path = '/config/youtube_thumbs/errors.log'

    # Check if log file exists
    if not os.path.exists(log_path):
        return {
            'errors': [],
            'page': 1,
            'total_pages': 0,
            'total_count': 0
        }

    # Determine time cutoff
    cutoff = None
    if period_filter != 'all':
        now = datetime.now()
        if period_filter == 'hour':
            cutoff = now - timedelta(hours=1)
        elif period_filter == 'day':
            cutoff = now - timedelta(days=1)
        elif period_filter == 'week':
            cutoff = now - timedelta(weeks=1)
        elif period_filter == 'month':
            cutoff = now - timedelta(days=30)

    # Read and parse log file
    errors = []
    log_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\w+) \| (.+)$')

    try:
        # Read last 2000 lines for performance
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Seek to end and read backwards
            lines = f.readlines()
            lines = lines[-2000:]  # Last 2000 lines

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue

            match = log_pattern.match(line)
            if match:
                timestamp_str, level, message = match.groups()

                # Parse timestamp
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue

                # Apply period filter
                if cutoff and timestamp < cutoff:
                    continue

                # Apply level filter
                if level_filter != 'all' and level != level_filter:
                    continue

                errors.append({
                    'timestamp': timestamp_str,
                    'level': level,
                    'message': message,
                    'timestamp_obj': timestamp
                })

    except Exception as e:
        logger.error(f"Error reading error log file: {e}")
        return {
            'errors': [],
            'page': 1,
            'total_pages': 0,
            'total_count': 0,
            'error': f'Failed to read log file: {str(e)}'
        }

    # Paginate results
    total_count = len(errors)
    if total_count == 0:
        return {
            'errors': [],
            'page': 1,
            'total_pages': 0,
            'total_count': 0
        }

    total_pages = (total_count + limit - 1) // limit
    page = max(1, min(page, total_pages))
    start = (page - 1) * limit
    end = start + limit

    return {
        'errors': errors[start:end],
        'page': page,
        'total_pages': total_pages,
        'total_count': total_count
    }


def categorize_quota_prober_event(message: str) -> str:
    """
    Categorize QuotaProber log event by message content.

    Args:
        message: Log message text

    Returns:
        Event category: 'probe', 'retry', 'success', 'error', 'recovery', 'other'
    """
    message_lower = message.lower()

    if 'time to check' in message_lower or 'quota prober:' in message_lower:
        return 'probe'
    elif 'retrying match' in message_lower or 'pending videos to retry' in message_lower or 'found' in message_lower and 'pending' in message_lower:
        return 'retry'
    elif 'successfully matched' in message_lower or '✓' in message:
        return 'success'
    elif 'no match found' in message_lower or 'failed' in message_lower or '✗' in message or 'error' in message_lower:
        return 'error'
    elif 'quota restored' in message_lower:
        return 'recovery'
    else:
        return 'other'


def parse_quota_prober_log(
    time_filter: str = 'all',
    event_filter: str = 'all',
    level_filter: str = 'all',
    page: int = 1,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Parse main log file for QuotaProber-related entries and return paginated results.

    Args:
        time_filter: Time period ('hour', 'day', 'week', 'month', 'all')
        event_filter: Event type ('probes', 'retries', 'successes', 'errors', 'recoveries', 'all')
        level_filter: Log level ('ERROR', 'WARNING', 'INFO', 'DEBUG', 'all')
        page: Page number (1-indexed)
        limit: Number of entries per page

    Returns:
        Dictionary with logs list, pagination info, statistics, and total count
    """
    log_path = '/config/youtube_thumbs/youtube_thumbs.log'

    # Check if log file exists
    if not os.path.exists(log_path):
        return {
            'logs': [],
            'page': 1,
            'total_pages': 0,
            'total_count': 0,
            'stats': {'probes': 0, 'recoveries': 0, 'retries': 0, 'resolved': 0}
        }

    # Determine time cutoff
    cutoff = None
    if time_filter != 'all':
        now = datetime.now()
        if time_filter == 'hour':
            cutoff = now - timedelta(hours=1)
        elif time_filter == 'day':
            cutoff = now - timedelta(days=1)
        elif time_filter == 'week':
            cutoff = now - timedelta(weeks=1)
        elif time_filter == 'month':
            cutoff = now - timedelta(days=30)

    # Read and parse log file
    logs = []
    stats = {'probes': 0, 'recoveries': 0, 'retries': 0, 'resolved': 0}

    try:
        # Read last 2000 lines (same as error log)
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-2000:]

        # Parse each line
        log_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\w+) \| (.+)$')

        for line in lines:
            match = log_pattern.match(line.strip())
            if not match:
                continue

            timestamp_str, level, message = match.groups()

            # Filter by QuotaProber keywords
            message_lower = message.lower()
            is_quota_prober = any(keyword in message_lower for keyword in [
                'quota prober',
                'quota restored',
                'pending videos to retry',
                'retrying match for',
                'successfully matched',
                'no match found'
            ])

            if not is_quota_prober:
                continue

            # Filter by log level
            if level_filter != 'all' and level != level_filter:
                continue

            # Parse timestamp
            try:
                timestamp = parse_timestamp(timestamp_str)
            except (ValueError, AttributeError):
                # Skip lines with unparseable timestamps
                continue

            # Filter by time period
            if cutoff and timestamp < cutoff:
                continue

            # Categorize event
            event_type = categorize_quota_prober_event(message)

            # Filter by event type
            if event_filter != 'all' and event_type != event_filter:
                continue

            # Update statistics
            if 'time to check' in message_lower:
                stats['probes'] += 1
            elif 'quota restored' in message_lower:
                stats['recoveries'] += 1
            elif 'found' in message_lower and 'pending videos to retry' in message_lower:
                stats['retries'] += 1
            elif 'successfully matched' in message_lower or '✓' in message:
                stats['resolved'] += 1

            # Add to results
            logs.append({
                'timestamp': timestamp_str,
                'timestamp_relative': format_relative_time(timestamp_str),
                'level': level,
                'message': message,
                'event_type': event_type
            })

    except Exception as e:
        logger.error(f"Error parsing quota prober log: {e}")

    # Reverse to show newest first
    logs.reverse()

    # Pagination
    total_count = len(logs)
    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
    page = max(1, min(page, total_pages if total_pages > 0 else 1))
    start = (page - 1) * limit
    end = start + limit

    return {
        'logs': logs[start:end],
        'page': page,
        'total_pages': total_pages,
        'total_count': total_count,
        'stats': stats
    }


def _handle_rated_tab(page, period_filter):
    """Handle rated songs tab."""
    rating_filter = request.args.get('rating', 'all')
    if rating_filter not in ['like', 'dislike', 'all']:
        rating_filter = 'all'

    result = _db.get_rated_songs(page, 50, period_filter, rating_filter)

    # Format songs for template
    formatted_songs = []
    for song in result['songs']:
        title = get_video_title(song)
        artist = get_video_artist(song)

        # Format relative time - use date_last_played, fallback to date_added
        timestamp = song.get('date_last_played') or song.get('date_added')
        time_ago = format_relative_time(timestamp) if timestamp else 'unknown'

        formatted_songs.append({
            'yt_video_id': song.get('yt_video_id'),
            'title': title,
            'artist': artist,
            'rating': song.get('rating'),
            'play_count': song.get('play_count', 0),
            'time_ago': time_ago,
            'timestamp': timestamp,
            'source': song.get('source', 'unknown')
        })

    return {
        'rating_filter': rating_filter,
        'songs': formatted_songs,
        'total_count': result['total_count'],
        'total_pages': result['total_pages']
    }


def _handle_matches_tab(page, period_filter):
    """Handle match history tab."""
    result = _db.get_match_history(page, 50, period_filter)

    # Format matches for template
    formatted_matches = []
    for match in result['matches']:
        ha_title = (match.get('ha_title') or 'Unknown').strip() or 'Unknown'
        ha_artist = (match.get('ha_artist') or 'Unknown').strip() or 'Unknown'
        yt_title = (match.get('yt_title') or 'Unknown').strip() or 'Unknown'
        yt_channel = (match.get('yt_channel') or 'Unknown').strip() or 'Unknown'

        # Calculate duration difference
        ha_duration = match.get('ha_duration') or 0
        yt_duration = match.get('yt_duration') or 0
        duration_diff = yt_duration - ha_duration

        # Determine match quality (good if duration diff <= 2 seconds)
        match_quality = 'good' if abs(duration_diff) <= 2 else 'fair'

        # Format relative time - use most recent activity (played, matched, or added)
        activity_timestamp = match.get('date_last_played') or match.get('yt_match_last_attempt') or match.get('date_added')
        time_ago = format_relative_time(activity_timestamp) if activity_timestamp else 'Unknown'

        # Format YouTube published date if available
        yt_published_at = match.get('yt_published_at')
        yt_published_formatted = None
        if yt_published_at:
            try:
                # YouTube API returns ISO 8601 string like "2023-10-15T12:00:00Z"
                if isinstance(yt_published_at, str):
                    pub_dt = datetime.fromisoformat(yt_published_at.replace('Z', '+00:00'))
                else:
                    pub_dt = yt_published_at
                yt_published_formatted = pub_dt.strftime('%b %d, %Y')
            except (ValueError, TypeError, AttributeError) as e:
                logger.debug(f"Failed to format YouTube published date '{yt_published_at}': {e}")
                yt_published_formatted = None

        formatted_matches.append({
            'yt_video_id': match.get('yt_video_id'),
            'ha_title': ha_title,
            'ha_artist': ha_artist,
            'ha_duration': ha_duration,
            'yt_title': yt_title,
            'yt_channel': yt_channel,
            'yt_duration': yt_duration,
            'yt_published_at': yt_published_formatted,
            'duration_diff': duration_diff,
            'match_quality': match_quality,
            # v4.0.0: Removed match_attempts (yt_match_attempts field removed from schema)
            'play_count': match.get('play_count', 0),
            'time_ago': time_ago,
            'timestamp': activity_timestamp,
            'date_last_played': match.get('date_last_played')
        })

    return {
        'matches': formatted_matches,
        'total_count': result['total_count'],
        'total_pages': result['total_pages']
    }


def _handle_errors_tab(page, period_filter):
    """Handle error logs tab."""
    level_filter = request.args.get('level', 'all')
    if level_filter not in ['ERROR', 'WARNING', 'INFO', 'all']:
        level_filter = 'all'

    result = parse_error_log(period_filter, level_filter, page, 50)

    # Format errors for template
    formatted_errors = []
    for error in result.get('errors', []):
        # Format relative time
        time_ago = format_relative_time(error['timestamp'])

        # Truncate long messages
        message = error['message']
        truncated = len(message) > 150
        if truncated:
            display_message = message[:150] + '...'
        else:
            display_message = message

        formatted_errors.append({
            'timestamp': error['timestamp'],
            'time_ago': time_ago,
            'level': error['level'],
            'message': message,
            'display_message': display_message,
            'truncated': truncated
        })

    return {
        'level_filter': level_filter,
        'errors': formatted_errors,
        'total_count': result.get('total_count', 0),
        'total_pages': result.get('total_pages', 0),
        'log_error': result.get('error')
    }


def _handle_quota_prober_tab(page, period_filter):
    """Handle quota prober logs tab."""
    # Get quota prober specific filters
    event_filter = request.args.get('event', 'all')
    if event_filter not in ['probe', 'retry', 'success', 'error', 'recovery', 'all']:
        event_filter = 'all'

    level_filter = request.args.get('level', 'all')
    if level_filter not in ['ERROR', 'WARNING', 'INFO', 'DEBUG', 'all']:
        level_filter = 'all'

    # Parse quota prober logs
    result = parse_quota_prober_log(
        time_filter=period_filter,
        event_filter=event_filter,
        level_filter=level_filter,
        page=page,
        limit=50
    )

    # Format logs for template
    formatted_logs = []
    for log in result['logs']:
        message = log['message']
        truncated = len(message) > 200
        if truncated:
            display_message = message[:200] + '...'
        else:
            display_message = message

        # Calculate time_ago fresh instead of using stale database value
        time_ago = format_relative_time(log['timestamp'])

        formatted_logs.append({
            'timestamp': log['timestamp'],
            'time_ago': time_ago,
            'level': log['level'],
            'event_type': log['event_type'],
            'message': message,
            'display_message': display_message,
            'truncated': truncated
        })

    return {
        'event_filter': event_filter,
        'level_filter': level_filter,
        'quota_prober_logs': formatted_logs,
        'quota_prober_stats': result.get('stats', {}),
        'total_count': result.get('total_count', 0),
        'total_pages': result.get('total_pages', 0)
    }


def _handle_recent_tab():
    """Handle recently added videos tab."""
    videos = _db.get_recently_added(limit=25)

    # v4.0.33: Format videos with relative time for issue #68
    formatted_videos = []
    for video in videos:
        # Format relative time for date_added
        date_added = video.get('date_added')
        time_ago = format_relative_time(date_added) if date_added else 'unknown'

        formatted_videos.append({
            'yt_video_id': video.get('yt_video_id'),
            'ha_title': video.get('ha_title'),
            'ha_artist': video.get('ha_artist'),
            'yt_title': video.get('yt_title'),
            'yt_channel': video.get('yt_channel'),
            'yt_url': video.get('yt_url'),
            'rating': video.get('rating'),
            'play_count': video.get('play_count', 0),
            'date_added': date_added,
            'time_ago': time_ago,
            'source': video.get('source')
        })

    return {
        'recent_videos': formatted_videos,
        'total_count': len(formatted_videos),
        'total_pages': 0  # Recent tab doesn't use pagination
    }


def _handle_queue_tab():
    """Handle queue statistics and activity tab."""
    # Get queue statistics
    stats = _db.get_queue_statistics()

    # Get recent activity
    activity = _db.get_recent_queue_activity(limit=30)

    # Get performance metrics
    metrics = _db.get_queue_performance_metrics(hours=24)

    # Get recent errors
    errors = _db.get_queue_errors(limit=20)

    # Format timestamps in activity
    for rating in activity['recent_ratings']:
        if rating.get('requested_at'):
            rating['requested_at_relative'] = format_relative_time(parse_timestamp(rating['requested_at']))
        if rating.get('last_attempt'):
            rating['last_attempt_relative'] = format_relative_time(parse_timestamp(rating['last_attempt']))

    for search in activity['recent_searches']:
        if search.get('requested_at'):
            search['requested_at_relative'] = format_relative_time(parse_timestamp(search['requested_at']))
        if search.get('last_attempt'):
            search['last_attempt_relative'] = format_relative_time(parse_timestamp(search['last_attempt']))

    # Format timestamps in errors
    for error in errors['rating_errors']:
        if error.get('last_attempt'):
            error['last_attempt_relative'] = format_relative_time(parse_timestamp(error['last_attempt']))

    for error in errors['search_errors']:
        if error.get('last_attempt'):
            error['last_attempt_relative'] = format_relative_time(parse_timestamp(error['last_attempt']))

    # Format last activity timestamps in stats
    if stats['worker_health'].get('last_rating_activity'):
        stats['worker_health']['last_rating_activity_relative'] = format_relative_time(
            parse_timestamp(stats['worker_health']['last_rating_activity'])
        )
    if stats['worker_health'].get('last_search_activity'):
        stats['worker_health']['last_search_activity_relative'] = format_relative_time(
            parse_timestamp(stats['worker_health']['last_search_activity'])
        )

    return {
        'queue_stats': stats,
        'queue_activity': activity,
        'queue_metrics': metrics,
        'queue_errors': errors,
        'total_count': 0,  # Queue tab doesn't use pagination
        'total_pages': 0
    }


@bp.route('/logs')
def logs_viewer():
    """
    Main logs viewer page with tabs for rated songs, matches, errors, and queue.
    """
    try:
        # Get query parameters
        current_tab = request.args.get('tab', 'rated')
        if current_tab not in ['rated', 'matches', 'errors', 'recent', 'queue']:
            current_tab = 'rated'

        page, _ = validate_page_param(request.args)
        if not page:  # If validation failed, default to 1
            page = 1

        period_filter = request.args.get('period', 'all')
        if period_filter not in ['hour', 'day', 'week', 'month', 'all']:
            period_filter = 'all'

        # Get ingress path
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

        # Initialize template data
        template_data = {
            'current_tab': current_tab,
            'ingress_path': ingress_path,
            'page': page,
            'period_filter': period_filter
        }

        # Handle each tab with dedicated functions
        if current_tab == 'rated':
            template_data.update(_handle_rated_tab(page, period_filter))
        elif current_tab == 'matches':
            template_data.update(_handle_matches_tab(page, period_filter))
        elif current_tab == 'errors':
            template_data.update(_handle_errors_tab(page, period_filter))
        elif current_tab == 'recent':
            template_data.update(_handle_recent_tab())
        elif current_tab == 'queue':
            template_data.update(_handle_queue_tab())

        # Generate page numbers for pagination
        total_pages = template_data.get('total_pages', 0)
        page_numbers = generate_page_numbers(page, total_pages)
        template_data['page_numbers'] = page_numbers

        return render_template('logs_viewer.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering logs page: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading logs</h1><p>An internal error occurred. Please try again later.</p>", 500
