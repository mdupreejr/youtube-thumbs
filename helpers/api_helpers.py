"""
API utility functions for YouTube Thumbs Rating.

Handles quota checking and other API-related helpers.
"""
from datetime import datetime, timezone
from logger import logger
from helpers.time_helpers import get_last_quota_reset_time, get_next_quota_reset_time, get_time_until_quota_reset


def check_quota_recently_exceeded(db):
    """
    Check if quota was exceeded since the last quota reset.
    YouTube API quota resets at midnight Pacific Time, so any quota error
    since the last reset means we should skip API calls until the next reset.

    Args:
        db: Database instance

    Returns:
        bool: True if quota exceeded since last reset, False otherwise
    """
    try:
        with db._lock:
            cursor = db._conn.execute(
                """
                SELECT timestamp, error_message
                FROM api_call_log
                WHERE success = 0
                  AND (error_message LIKE '%quota%' OR error_message LIKE '%Quota%')
                ORDER BY timestamp DESC
                LIMIT 1
                """,
            )
            row = cursor.fetchone()

            if not row:
                return False

            last_quota_error = dict(row)
            error_time_str = last_quota_error.get('timestamp')

            if not error_time_str:
                return False

            # Parse timestamp
            if isinstance(error_time_str, str):
                error_dt = datetime.fromisoformat(error_time_str.replace('Z', '+00:00'))
            else:
                error_dt = error_time_str

            # Ensure error_dt has timezone
            if error_dt.tzinfo is None:
                error_dt = error_dt.replace(tzinfo=timezone.utc)

            # Get last quota reset time
            last_reset = get_last_quota_reset_time()
           

            # If quota error occurred AFTER last reset, quota is still exhausted
            if error_dt > last_reset:
                hours_until, minutes_until = get_time_until_quota_reset()
                logger.info(f"Quota exceeded since last reset - skipping API call")
                logger.info(f"Quota will reset in {hours_until}h {minutes_until}m (midnight Pacific Time)")
                return True

            return False

    except Exception as e:
        logger.debug(f"Error checking quota status: {e}")
        return False  # If we can't check, allow the attempt
