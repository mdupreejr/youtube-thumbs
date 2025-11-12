"""
Routes for logs viewer page.

Provides endpoints for viewing rated songs, match history, and error logs.
"""

from flask import Blueprint, render_template, request, jsonify, g
import json
from logging_helper import LoggingHelper, LogType
from helpers.pagination_helpers import generate_page_numbers
from helpers.time_helpers import format_relative_time, format_absolute_timestamp
from helpers.validation_helpers import validate_page_param
from helpers.template import (
    TableColumn, TableRow, TableCell,
    format_badge, truncate_text, format_status_badge
)
from helpers.page_builder import ApiCallsPageBuilder
from helpers.queue_item_helpers import extract_queue_item_details
from routes.logs_routes_helpers import (
    _create_queue_pending_tab,
    _create_queue_history_tab,
    _create_queue_errors_tab,
    _create_queue_statistics_tab,
    _create_rated_songs_page,
    _create_matches_page,
    _create_errors_page,
    _create_recent_page
)

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

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
                TableCell(formatted_timestamp, format_relative_time(formatted_timestamp)),
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
        LoggingHelper.log_error_with_trace("Error displaying queue", e)
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

        # Extract details using shared helper
        details = extract_queue_item_details(queue_item, _db)

        if not details:
            logger.error(f"Invalid queue item type: {queue_item.get('type')}")
            return jsonify({'success': False, 'error': f'Invalid item type: {queue_item.get("type")}'}), 400

        return jsonify({'success': True, 'data': details})

    except Exception as e:
        LoggingHelper.log_error_with_trace(f"Error getting queue item details ({queue_id})", e)
        return jsonify({'success': False, 'error': 'Internal server error occurred'}), 500


@bp.route('/logs/pending-ratings/item/<int:item_id>')
def queue_item_detail_page(item_id: int):
    """Render a full page with queue item details."""
    ingress_path = g.ingress_path

    try:
        # Get queue item from unified queue
        queue_item = _db.get_queue_item_by_id(item_id)
        if not queue_item:
            logger.error(f"Queue item not found: {item_id}")
            return render_template('error.html',
                                 error=f'Queue item not found: {item_id}',
                                 ingress_path=ingress_path), 404

        # Extract details using shared helper
        details = extract_queue_item_details(queue_item, _db)

        if not details:
            logger.error(f"Invalid queue item type: {queue_item.get('type')}")
            return render_template('error.html',
                                 error=f'Invalid item type: {queue_item.get("type")}',
                                 ingress_path=ingress_path), 400

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
                             back_url=back_url)

    except Exception as e:
        LoggingHelper.log_error_with_trace(f"Error rendering queue item detail page ({item_id})", e)
        return render_template('error.html',
                             error=f'Internal server error: {str(e)}',
                             ingress_path=ingress_path), 500


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
            page_config, table_data, pagination, status_message = _create_rated_songs_page(page, period_filter, ingress_path, _db)
        elif current_tab == 'matches':
            page_config, table_data, pagination, status_message = _create_matches_page(page, period_filter, ingress_path, _db)
        elif current_tab == 'errors':
            page_config, table_data, pagination, status_message = _create_errors_page(page, period_filter, ingress_path, _db)
        elif current_tab == 'recent':
            page_config, table_data, pagination, status_message = _create_recent_page(ingress_path, _db)
        else:
            page_config, table_data, pagination, status_message = _create_rated_songs_page(page, period_filter, ingress_path, _db)

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if table_data and table_data.rows else None,
            pagination=pagination,
            status_message=status_message
        )

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering logs page", e)
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading logs</h1><p>An internal error occurred. Please try again later.</p>", 500
