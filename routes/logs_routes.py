"""
Routes for logs viewer page.

Provides endpoints for viewing rated songs, match history, and error logs.
"""

from flask import Blueprint, render_template, request
from datetime import datetime, timedelta
from typing import Dict, Any, List
import os
import re
from logger import logger
from helpers.pagination_helpers import generate_page_numbers
from helpers.time_helpers import format_relative_time, parse_timestamp
from helpers.validation_helpers import validate_page_param
from video_helpers import get_video_title, get_video_artist

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

        # Format relative time
        time_ago = format_relative_time(match.get('date_added', ''))

        formatted_matches.append({
            'yt_video_id': match.get('yt_video_id'),
            'ha_title': ha_title,
            'ha_artist': ha_artist,
            'ha_duration': ha_duration,
            'yt_title': yt_title,
            'yt_channel': yt_channel,
            'yt_duration': yt_duration,
            'duration_diff': duration_diff,
            'match_quality': match_quality,
            'match_attempts': match.get('yt_match_attempts', 0),
            'play_count': match.get('play_count', 0),
            'time_ago': time_ago,
            'timestamp': match.get('date_added')
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

    return {
        'recent_videos': videos,
        'total_count': len(videos),
        'total_pages': 0  # Recent tab doesn't use pagination
    }


@bp.route('/logs')
def logs_viewer():
    """
    Main logs viewer page with tabs for rated songs, matches, and errors.
    """
    try:
        # Get query parameters
        current_tab = request.args.get('tab', 'rated')
        if current_tab not in ['rated', 'matches', 'errors', 'quota_prober', 'recent']:
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
        elif current_tab == 'quota_prober':
            template_data.update(_handle_quota_prober_tab(page, period_filter))
        elif current_tab == 'recent':
            template_data.update(_handle_recent_tab())

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
