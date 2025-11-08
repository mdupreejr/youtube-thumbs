"""
Time utility functions for YouTube Thumbs Rating.

Handles quota reset time calculations and other time-related operations.
"""
from datetime import datetime, timedelta, timezone
from typing import Tuple


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
