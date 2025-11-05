"""
Time formatting helper utilities.

Provides reusable time formatting functions for consistent display across the application.
"""
from datetime import datetime


def format_relative_time(timestamp_str: str) -> str:
    """
    Format timestamp as relative time (e.g., "2h ago", "yesterday").

    Args:
        timestamp_str: ISO format timestamp string

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
    except Exception:
        return timestamp_str
