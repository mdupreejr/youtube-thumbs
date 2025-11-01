"""
YouTube API usage tracking operations.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Any
import sqlite3
import threading


class APIUsageOperations:
    """Handles YouTube API usage tracking operations."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    def record_api_call(
        self,
        api_method: str,
        success: bool = True,
        quota_cost: int = 1,
        error_message: str = None
    ) -> None:
        """
        Record an API call for usage tracking.
        Increments the hourly counter for the current date and hour.

        Args:
            api_method: The YouTube API method called (deprecated, kept for compatibility)
            success: Whether the call succeeded (deprecated, kept for compatibility)
            quota_cost: Quota units consumed (deprecated, kept for compatibility)
            error_message: Optional error message if call failed (deprecated, kept for compatibility)
        """
        with self._lock:
            now = datetime.utcnow()
            date_str = now.strftime('%Y-%m-%d')
            hour = now.hour

            # Validate hour is within expected range
            if not (0 <= hour <= 23):
                raise ValueError(f"Invalid hour: {hour}")

            hour_col = f"hour_{hour:02d}"

            # Insert or update the row for today
            self._conn.execute(
                f"""
                INSERT INTO api_usage (date, {hour_col})
                VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET {hour_col} = {hour_col} + 1
                """,
                (date_str,)
            )
            self._conn.commit()

    def get_usage_summary(self, days: int = 30) -> Dict[str, Any]:
        """
        Get API usage summary for the last N days.

        Args:
            days: Number of days to look back (default 30)

        Returns:
            Dictionary with usage statistics
        """
        with self._lock:
            cutoff_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

            # Get all rows within the date range
            cursor = self._conn.execute(
                """
                SELECT * FROM api_usage
                WHERE date >= ?
                ORDER BY date DESC
                """,
                (cutoff_date,)
            )
            rows = [dict(row) for row in cursor.fetchall()]

            # Calculate overall statistics
            total_calls = 0
            daily_stats = []

            for row in rows:
                # Sum all hourly columns for this day
                day_total = sum(row.get(f'hour_{h:02d}', 0) or 0 for h in range(24))
                total_calls += day_total

                daily_stats.append({
                    'date': row['date'],
                    'calls': day_total
                })

            return {
                'period_days': days,
                'total_calls': total_calls,
                'daily_stats': daily_stats
            }

    def get_daily_usage(self, date_str: str = None) -> Dict[str, Any]:
        """
        Get API usage for a specific day with hourly breakdown.

        Args:
            date_str: Date in YYYY-MM-DD format (default: today)

        Returns:
            Dictionary with daily usage statistics including hourly breakdown
        """
        if not date_str:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM api_usage
                WHERE date = ?
                """,
                (date_str,)
            )
            row = cursor.fetchone()

            if not row:
                # No data for this date
                return {
                    'date': date_str,
                    'total_calls': 0,
                    'hourly_breakdown': {f'hour_{h:02d}': 0 for h in range(24)}
                }

            row_dict = dict(row)
            hourly_breakdown = {f'hour_{h:02d}': row_dict.get(f'hour_{h:02d}', 0) or 0 for h in range(24)}
            total_calls = sum(hourly_breakdown.values())

            return {
                'date': date_str,
                'total_calls': total_calls,
                'hourly_breakdown': hourly_breakdown
            }

    def get_hourly_usage(self, date_str: str = None) -> List[Dict[str, Any]]:
        """
        Get hourly API usage for a specific day.

        Args:
            date_str: Date in YYYY-MM-DD format (default: today)

        Returns:
            List of hourly usage statistics in the format [{'hour': '00', 'calls': 5}, ...]
        """
        if not date_str:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM api_usage
                WHERE date = ?
                """,
                (date_str,)
            )
            row = cursor.fetchone()

            if not row:
                # No data for this date, return zeros for all hours
                return [{'hour': f'{h:02d}', 'calls': 0} for h in range(24)]

            row_dict = dict(row)
            result = []
            for h in range(24):
                hour_str = f'{h:02d}'
                calls = row_dict.get(f'hour_{hour_str}', 0) or 0
                result.append({'hour': hour_str, 'calls': calls})

            return result
