"""
Time formatting helper utilities.

Provides reusable time formatting functions for consistent display across the application.
"""
from datetime import datetime
from typing import Union


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
        delta = datetime.utcnow() - timestamp

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
