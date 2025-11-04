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


def format_relative_time(timestamp_str: str) -> str:
    """
    Format timestamp as relative time (e.g., "2h ago", "yesterday").

    Args:
        timestamp_str: ISO format timestamp string

    Returns:
        Relative time string
    """
    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace(' ', 'T'))
        delta = datetime.now() - timestamp

        if delta.days > 30:
            return timestamp.strftime('%b %d, %Y')
        elif delta.days > 1:
            return f"{delta.days}d ago"
        elif delta.days == 1:
            return "yesterday"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours}h ago"
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            return f"{minutes}m ago"
        else:
            return "just now"
    except:
        return timestamp_str


@bp.route('/logs')
def logs_viewer():
    """
    Main logs viewer page with tabs for rated songs, matches, and errors.
    """
    try:
        # Get query parameters
        current_tab = request.args.get('tab', 'rated')
        if current_tab not in ['rated', 'matches', 'errors']:
            current_tab = 'rated'

        try:
            page = int(request.args.get('page', 1))
            if page < 1:
                page = 1
        except (ValueError, TypeError):
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

        # Handle each tab
        if current_tab == 'rated':
            rating_filter = request.args.get('rating', 'all')
            if rating_filter not in ['like', 'dislike', 'all']:
                rating_filter = 'all'

            result = _db.get_rated_songs(page, 50, period_filter, rating_filter)

            # Format songs for template
            formatted_songs = []
            for song in result['songs']:
                title = (song.get('ha_title') or song.get('yt_title') or 'Unknown').strip() or 'Unknown'
                artist = (song.get('ha_artist') or song.get('yt_channel') or 'Unknown').strip() or 'Unknown'

                # Format relative time
                time_ago = format_relative_time(song.get('date_last_played', ''))

                formatted_songs.append({
                    'yt_video_id': song.get('yt_video_id'),
                    'title': title,
                    'artist': artist,
                    'rating': song.get('rating'),
                    'play_count': song.get('play_count', 0),
                    'time_ago': time_ago,
                    'timestamp': song.get('date_last_played'),
                    'source': song.get('source', 'unknown')
                })

            template_data.update({
                'rating_filter': rating_filter,
                'songs': formatted_songs,
                'total_count': result['total_count'],
                'total_pages': result['total_pages']
            })

        elif current_tab == 'matches':
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

            template_data.update({
                'matches': formatted_matches,
                'total_count': result['total_count'],
                'total_pages': result['total_pages']
            })

        elif current_tab == 'errors':
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

            template_data.update({
                'level_filter': level_filter,
                'errors': formatted_errors,
                'total_count': result.get('total_count', 0),
                'total_pages': result.get('total_pages', 0),
                'log_error': result.get('error')
            })

        # Generate page numbers for pagination
        total_pages = template_data.get('total_pages', 0)
        page_numbers = []
        if total_pages <= 10:
            page_numbers = list(range(1, total_pages + 1))
        elif total_pages > 1:
            page_numbers = [1]
            start = max(2, page - 2)
            end = min(total_pages - 1, page + 2)
            if start > 2:
                page_numbers.append('...')
            for p in range(start, end + 1):
                page_numbers.append(p)
            if end < total_pages - 1:
                page_numbers.append('...')
            if total_pages > 1:
                page_numbers.append(total_pages)

        template_data['page_numbers'] = page_numbers

        return render_template('logs_viewer.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering logs page: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return f"<h1>Error loading logs</h1><p>{str(e)}</p>", 500
