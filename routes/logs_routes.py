"""
Routes for logs viewer page.

Provides endpoints for viewing rated songs, match history, and error logs.
"""

from flask import Blueprint, render_template, request, jsonify, g
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
    TableData, TableColumn, TableRow, TableCell, PageConfig,
    create_api_calls_page_config,
    format_badge, format_time_ago, truncate_text,
    format_song_display, format_status_badge
)
from helpers.page_builder import LogsPageBuilder, ApiCallsPageBuilder
from routes.logs_routes_queue_helpers import (
    _create_queue_pending_tab,
    _create_queue_history_tab,
    _create_queue_errors_tab,
    _create_queue_statistics_tab
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
    ingress_path = g.ingress_path

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

        # Use builder pattern for consistent page creation
        builder = ApiCallsPageBuilder(ingress_path)

        # Add filters
        builder.add_filter('method', 'API Method', [
            {'value': '', 'label': 'All Methods', 'selected': not method_filter},
            {'value': 'search', 'label': 'search', 'selected': method_filter == 'search'},
            {'value': 'videos.list', 'label': 'videos.list', 'selected': method_filter == 'videos.list'}
        ])
        builder.add_filter('success', 'Status', [
            {'value': '', 'label': 'All', 'selected': success_filter_str is None},
            {'value': 'true', 'label': 'Success', 'selected': success_filter_str == 'true'},
            {'value': 'false', 'label': 'Failed', 'selected': success_filter_str == 'false'}
        ])
        builder.set_filter_button_text('Apply Filters')
        builder.set_empty_state('📊', 'No API calls found', 'No API calls have been logged yet, or none match your filters.')

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
            status_html = format_status_badge(log.get('success'))
            
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

        # Set table
        builder.set_table(columns, rows)

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

        builder.set_summary_stats(summary_stats)

        # Set pagination
        total_count = result['total_count']
        total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
        page_numbers = generate_page_numbers(page, total_pages)

        query_params = {}
        if method_filter:
            query_params['method'] = method_filter
        if success_filter_str:
            query_params['success'] = success_filter_str

        builder.set_pagination(page, total_pages, page_numbers, query_params)

        builder.set_status_message(
            f"Showing {len(result['logs'])} of {total_count} API calls • Page {page}/{total_pages}"
        )

        # Build and render
        page_config, table_data, pagination, status_message, summary_stats = builder.build()

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if table_data and table_data.rows else None,
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
    Now uses the unified table_viewer.html template.
    """
    try:
        current_tab = request.args.get('tab', 'pending')
        if current_tab not in ['pending', 'history', 'errors', 'statistics']:
            current_tab = 'pending'

        ingress_path = g.ingress_path

        # Create page configuration based on tab
        if current_tab == 'pending':
            page_config, table_data, status_message = _create_queue_pending_tab(ingress_path, current_tab, _db)
        elif current_tab == 'history':
            page_config, table_data, status_message = _create_queue_history_tab(ingress_path, current_tab, _db)
        elif current_tab == 'errors':
            page_config, table_data, status_message = _create_queue_errors_tab(ingress_path, current_tab, _db)
        elif current_tab == 'statistics':
            page_config, table_data, status_message, summary_stats = _create_queue_statistics_tab(ingress_path, current_tab, _db)
            return render_template(
                'table_viewer.html',
                ingress_path=ingress_path,
                page_config=page_config.to_dict(),
                table_data=None,
                summary_stats=summary_stats,
                status_message=status_message
            )
        else:
            page_config, table_data, status_message = _create_queue_pending_tab(ingress_path, current_tab, _db)

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if table_data and table_data.rows else None,
            status_message=status_message
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


@bp.route('/logs/pending-ratings/item/<int:item_id>')
def queue_item_detail_page(item_id: int):
    """Render a full page with queue item details."""
    from helpers.static_helpers import static_url
    import json

    ingress_path = g.ingress_path

    try:
        # Get queue item from unified queue
        queue_item = _db.get_queue_item_by_id(item_id)
        if not queue_item:
            logger.error(f"Queue item not found: {item_id}")
            return render_template('error.html',
                                 error=f'Queue item not found: {item_id}',
                                 ingress_path=ingress_path,
                                 static_url=static_url), 404

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
                'queue_id': item_id,
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
                'api_response_data': queue_item.get('api_response_data'),
                'payload': payload
            }

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
                    logger.debug(f"Could not find completed search result for queue {item_id}: {e}")

            details = {
                'type': 'search',
                'queue_id': item_id,
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
                'api_response_data': queue_item.get('api_response_data'),
                'payload': payload,
                # Add YouTube metadata if found
                'yt_video_id': found_video.get('yt_video_id') if found_video else None,
                'yt_title': found_video.get('yt_title') if found_video else None,
                'yt_channel': found_video.get('yt_channel') if found_video else None,
                'yt_duration': found_video.get('yt_duration') if found_video else None,
                'yt_url': found_video.get('yt_url') if found_video else None
            }

        else:
            logger.error(f"Invalid queue item type: {item_type}")
            return render_template('error.html',
                                 error=f'Invalid item type: {item_type}',
                                 ingress_path=ingress_path,
                                 static_url=static_url), 400

        # Parse API response data for template
        api_debug = {}
        if details.get('api_response_data'):
            try:
                api_data = details['api_response_data']
                if isinstance(api_data, str):
                    api_data = json.loads(api_data)

                api_debug['cache_hit'] = api_data.get('cache_hit', False)
                api_debug['search_query'] = api_data.get('search_query')

                # Parse search results
                if api_data.get('search_response'):
                    items = api_data['search_response'].get('items', [])
                    api_debug['search_results_count'] = len(items)
                    api_debug['top_results'] = [
                        {
                            'title': item.get('snippet', {}).get('title', 'Unknown'),
                            'video_id': item.get('id', {}).get('videoId', 'Unknown')
                        }
                        for item in items[:5]
                    ]

                api_debug['videos_checked'] = api_data.get('videos_checked')
                api_debug['candidates_found'] = api_data.get('candidates_found')

                if api_data.get('batch_responses'):
                    api_debug['batch_responses_count'] = len(api_data['batch_responses'])

                if api_data.get('error'):
                    api_debug['error'] = {
                        'type': api_data['error'].get('type', 'Unknown'),
                        'message': api_data['error'].get('message', 'Unknown')
                    }

                # Store raw JSON for details view
                api_debug['raw_json'] = json.dumps(api_data, indent=2)

            except Exception as e:
                logger.warning(f"Failed to parse API response data for display: {e}")
                api_debug['raw_json'] = str(details.get('api_response_data'))

        # Determine back URL from referer
        back_url = request.referrer if request.referrer and 'pending-ratings' in request.referrer else None

        return render_template('queue_item_detail.html',
                             data=details,
                             api_debug=api_debug,
                             ingress_path=ingress_path,
                             back_url=back_url,
                             static_url=static_url)

    except Exception as e:
        logger.error(f"Error rendering queue item detail page ({item_id}): {e}")
        import traceback
        logger.error(traceback.format_exc())
        return render_template('error.html',
                             error=f'Internal server error: {str(e)}',
                             ingress_path=ingress_path,
                             static_url=static_url), 500


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

@bp.route('/logs')
def logs_viewer():
    """
    Main logs viewer page with tabs for rated songs, matches, errors, and queue.
    Now uses the unified table_viewer.html template.
    """
    try:
        # Get query parameters
        current_tab = request.args.get('tab', 'rated')
        if current_tab not in ['rated', 'matches', 'errors', 'recent']:
            current_tab = 'rated'

        page, _ = validate_page_param(request.args)
        if not page:  # If validation failed, default to 1
            page = 1

        period_filter = request.args.get('period', 'all')
        if period_filter not in ['hour', 'day', 'week', 'month', 'all']:
            period_filter = 'all'

        # Get ingress path
        ingress_path = g.ingress_path

        # Create page configuration
        if current_tab == 'rated':
            page_config, table_data, pagination, status_message = _create_rated_songs_page(page, period_filter, ingress_path)
        elif current_tab == 'matches':
            page_config, table_data, pagination, status_message = _create_matches_page(page, period_filter, ingress_path)
        elif current_tab == 'errors':
            page_config, table_data, pagination, status_message = _create_errors_page(page, period_filter, ingress_path)
        elif current_tab == 'recent':
            page_config, table_data, pagination, status_message = _create_recent_page(ingress_path)
        else:
            page_config, table_data, pagination, status_message = _create_rated_songs_page(page, period_filter, ingress_path)

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if table_data and table_data.rows else None,
            pagination=pagination,
            status_message=status_message
        )

    except Exception as e:
        logger.error(f"Error rendering logs page: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading logs</h1><p>An internal error occurred. Please try again later.</p>", 500


# ============================================================================
# TABLE VIEWER PAGE CREATORS
# ============================================================================

def _create_rated_songs_page(page: int, period_filter: str, ingress_path: str):
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
    result = _db.get_rated_songs(page, 50, period_filter, rating_filter)

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


def _create_matches_page(page: int, period_filter: str, ingress_path: str):
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
    result = _db.get_match_history(page, 50, period_filter)
    
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


def _create_errors_page(page: int, period_filter: str, ingress_path: str):
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


def _create_recent_page(ingress_path: str):
    """Create page config and table data for recent videos."""
    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('recent', ingress_path)
    builder.set_empty_state('📭', 'No Videos Yet', 'No videos have been added to the database yet.')

    # Get data
    videos = _db.get_recently_added(limit=25)

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


def _create_queue_page(ingress_path: str):
    """Create page config and table data for queue statistics."""
    # Use builder pattern for consistent page creation
    builder = LogsPageBuilder('queue', ingress_path)
    builder.set_empty_state('⚙️', 'No Queue Activity', 'No rating queue activity found.')

    # Get queue statistics
    stats = _db.get_queue_statistics()
    activity = _db.get_recent_queue_activity(limit=30)

    # For now, create a simplified view of recent ratings
    columns = [
        TableColumn('requested', 'Requested'),
        TableColumn('song', 'Song'),
        TableColumn('rating', 'Rating'),
        TableColumn('status', 'Status'),
        TableColumn('attempts', 'Attempts'),
        TableColumn('last_attempt', 'Last Attempt'),
        TableColumn('error', 'Error')
    ]

    rows = []
    for rating in activity['recent_ratings']:
        if rating.get('requested_at'):
            requested_relative = format_relative_time(parse_timestamp(rating['requested_at']))
        else:
            requested_relative = 'Unknown'

        if rating.get('last_attempt'):
            last_attempt_relative = format_relative_time(parse_timestamp(rating['last_attempt']))
        else:
            last_attempt_relative = 'Never'

        # Format status badge
        status = rating.get('status', 'pending')
        if status == 'success':
            status_html = format_status_badge(True)
        elif status == 'failed':
            status_html = format_status_badge(False)
        else:
            status_html = format_badge('⏳ Pending', 'warning')

        # Format rating
        rating_type = rating.get('requested_rating')
        rating_emoji = '👍' if rating_type == 'like' else '👎' if rating_type == 'dislike' else '?'

        cells = [
            TableCell(requested_relative),
            TableCell(rating.get('ha_title', 'Unknown')),
            TableCell(rating_emoji),
            TableCell(status, status_html),
            TableCell(rating.get('attempts', 0)),
            TableCell(last_attempt_relative),
            TableCell(rating.get('error') or '-')
        ]
        rows.append(TableRow(cells))

    # Set table and status
    builder.set_table(columns, rows)
    builder.set_status_message(
        f"Queue: {stats['rating_queue']['pending']} pending, {stats['rating_queue']['processed_24h']} processed (24h)"
    )

    return builder.build()
