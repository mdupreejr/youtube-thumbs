"""
Log parsing utilities for error logs and quota prober logs.

Extracted from routes/logs_routes.py for better code organization.
"""

from datetime import datetime, timedelta
from typing import Dict, Any
import os
import re
from logging_helper import LoggingHelper, LogType
from helpers.time_helpers import format_relative_time, parse_timestamp

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)


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
