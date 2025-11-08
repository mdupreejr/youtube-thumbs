"""
Time utility functions for YouTube Thumbs Rating.

Handles quota reset time calculations and other time-related operations.
"""
from datetime import datetime, timedelta, timezone
from typing import Tuple, Union


def get_last_quota_reset_time() -> datetime:
    """
    Calculate when quota last reset (midnight Pacific Time).
    YouTube API quota resets at midnight Pacific Time (UTC-8 or UTC-7 during DST).

    Returns:
        datetime: The last quota reset time in UTC (timezone-aware)
    """
    # Get current time in UTC
    now_utc = datetime.now(timezone.utc)

    # Convert to Pacific Time (simplified: assume PST = UTC-8)
    # TODO: Handle PST/PDT transition properly
    pacific_offset = timedelta(hours=-8)
    now_pacific = now_utc + pacific_offset

    # Get midnight today in Pacific Time
    midnight_today_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert back to UTC
    midnight_today_utc = midnight_today_pacific - pacific_offset

    # If current time is before today's reset, use yesterday's reset
    if now_utc < midnight_today_utc:
        last_reset_utc = midnight_today_utc - timedelta(days=1)
    else:
        last_reset_utc = midnight_today_utc

    return last_reset_utc


def get_next_quota_reset_time() -> datetime:
    """
    Calculate when quota will next reset (midnight Pacific Time).

    Returns:
        datetime: The next quota reset time in UTC (timezone-aware)
    """
    last_reset = get_last_quota_reset_time()
    next_reset = last_reset + timedelta(days=1)
    return next_reset


def get_time_until_quota_reset() -> Tuple[int, int]:
    """
    Calculate hours and minutes until next quota reset.

    Returns:
        Tuple[int, int]: (hours, minutes) until next quota reset
    """
    now_utc = datetime.now(timezone.utc)
    next_reset = get_next_quota_reset_time()
    time_until_reset = next_reset - now_utc

    hours = int(time_until_reset.total_seconds() / 3600)
    minutes = int((time_until_reset.total_seconds() % 3600) / 60)

    return hours, minutes


def now_utc() -> datetime:
    """
    Get current time in UTC (timezone-aware).

    Use this instead of datetime.utcnow() which is deprecated and timezone-naive.

    Returns:
        datetime: Current time in UTC with timezone info
    """
    return datetime.now(timezone.utc)


def now_utc_string() -> str:
    """
    Get current time in UTC as ISO format string.

    Returns:
        str: Current time in UTC as ISO string (e.g., "2025-11-08T10:30:00+00:00")
    """
    return datetime.now(timezone.utc).isoformat()


# ========================================
# Time Formatting Utilities
# ========================================

def format_relative_time(timestamp_input: Union[str, datetime]) -> str:
    """
    Format timestamp as relative time (e.g., "2h ago", "yesterday").

    Args:
        timestamp_input: ISO format timestamp string or datetime object

    Returns:
        Relative time string

    Examples:
        >>> # Just now (< 1 minute ago)
        >>> format_relative_time("2024-01-15T12:00:00")
        'just now'

        >>> # Minutes ago
        >>> format_relative_time("2024-01-15T11:30:00")  # 30 min ago
        '30m ago'

        >>> # Hours ago
        >>> format_relative_time("2024-01-15T09:00:00")  # 3 hours ago
        '3h ago'

        >>> # Yesterday
        >>> format_relative_time("2024-01-14T12:00:00")
        'yesterday'

        >>> # Days ago
        >>> format_relative_time("2024-01-10T12:00:00")  # 5 days ago
        '5d ago'

        >>> # Older than 30 days (shows date)
        >>> format_relative_time("2023-12-01T12:00:00")
        'Dec 01, 2023'

        >>> # Can also accept datetime objects
        >>> format_relative_time(datetime(2024, 1, 15, 12, 0, 0))
        'just now'
    """
    # Handle None or empty input
    if timestamp_input is None:
        return "unknown"

    # Handle string input
    if isinstance(timestamp_input, str):
        # Handle empty or whitespace-only strings
        if not timestamp_input.strip():
            return "unknown"
        timestamp_str = timestamp_input
    # Handle datetime objects
    elif isinstance(timestamp_input, datetime):
        timestamp = timestamp_input
    else:
        # Unexpected type
        return "unknown"

    try:
        # Parse string to datetime if needed
        if isinstance(timestamp_input, str):
            timestamp = datetime.fromisoformat(timestamp_str.replace(' ', 'T'))

        # Normalize both timestamps to UTC for comparison
        # SQLite stores timestamps as strings without timezone, treat them as UTC
        if timestamp.tzinfo is None:
            # Naive datetime from SQLite - assume UTC
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        # Get current time in UTC
        now = datetime.now(timezone.utc)

        delta = now - timestamp

        # Handle future timestamps
        if delta.total_seconds() < 0:
            return timestamp.strftime('%b %d, %Y')

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
    except (ValueError, AttributeError, TypeError):
        return "unknown"


def parse_timestamp(timestamp_str: Union[str, datetime]) -> datetime:
    """
    Parse timestamp string into datetime object, or return datetime if already a datetime.

    Handles both ISO format timestamps and timestamps with space instead of 'T'.
    Also accepts datetime objects directly (returns them unchanged).
    This is a common pattern in the codebase for parsing database timestamps.

    Args:
        timestamp_str: Timestamp string in ISO format (or with space instead of 'T'),
                      or a datetime object

    Returns:
        datetime object

    Raises:
        ValueError: If timestamp_str is None, empty, or cannot be parsed

    Examples:
        >>> # ISO format with T
        >>> parse_timestamp("2024-01-15T12:30:45")
        datetime(2024, 1, 15, 12, 30, 45)

        >>> # ISO format with space
        >>> parse_timestamp("2024-01-15 12:30:45")
        datetime(2024, 1, 15, 12, 30, 45)

        >>> # datetime object (Python 3.12 SQLite behavior)
        >>> parse_timestamp(datetime(2024, 1, 15, 12, 30, 45))
        datetime(2024, 1, 15, 12, 30, 45)

        >>> # Invalid input
        >>> parse_timestamp(None)
        ValueError: Invalid timestamp: None

        >>> parse_timestamp("")
        ValueError: Invalid timestamp: empty string
    """
    if timestamp_str is None:
        raise ValueError("Invalid timestamp: None")

    # If already a datetime object, return it directly
    if isinstance(timestamp_str, datetime):
        return timestamp_str

    if not isinstance(timestamp_str, str):
        raise ValueError(f"Invalid timestamp: expected string or datetime, got {type(timestamp_str).__name__}")
    if not timestamp_str.strip():
        raise ValueError("Invalid timestamp: empty string")

    return datetime.fromisoformat(timestamp_str.replace(' ', 'T'))


def format_absolute_timestamp(timestamp_input: Union[str, datetime]) -> str:
    """
    Format timestamp as readable absolute time without year (e.g., "11-08 07:28:40").

    Args:
        timestamp_input: ISO format timestamp string or datetime object

    Returns:
        Formatted timestamp string (MM-DD HH:MM:SS)

    Examples:
        >>> format_absolute_timestamp("2025-11-08T07:28:40")
        '11-08 07:28:40'

        >>> format_absolute_timestamp("2025-11-08 07:28:40")
        '11-08 07:28:40'

        >>> format_absolute_timestamp(datetime(2025, 11, 8, 7, 28, 40))
        '11-08 07:28:40'
    """
    # Handle None or empty input
    if timestamp_input is None:
        return ""

    # Handle string input
    if isinstance(timestamp_input, str):
        if not timestamp_input.strip():
            return ""
        timestamp_str = timestamp_input
    # Handle datetime objects
    elif isinstance(timestamp_input, datetime):
        timestamp = timestamp_input
    else:
        return ""

    try:
        # Parse string to datetime if needed
        if isinstance(timestamp_input, str):
            timestamp = datetime.fromisoformat(timestamp_str.replace(' ', 'T'))

        # Format as MM-DD HH:MM:SS (no year)
        return timestamp.strftime('%m-%d %H:%M:%S')
    except (ValueError, AttributeError, TypeError):
        return ""


def format_duration(seconds: int) -> str:
    """
    Format duration in seconds as MM:SS.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (MM:SS)

    Examples:
        >>> format_duration(90)
        '1:30'

        >>> format_duration(3665)
        '61:05'

        >>> format_duration(45)
        '0:45'

        >>> format_duration(0)
        '0:00'
    """
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"
