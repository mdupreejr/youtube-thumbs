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

        Args:
            api_method: The YouTube API method called (e.g., 'search', 'videos.rate', 'videos.list')
            success: Whether the call succeeded
            quota_cost: Quota units consumed (default 1, search is typically 100)
            error_message: Optional error message if call failed
        """
        with self._lock:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

            self._conn.execute(
                """
                INSERT INTO api_usage (timestamp, date, api_method, success, quota_cost, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (timestamp, date_str, api_method, 1 if success else 0, quota_cost, error_message)
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

            # Get overall statistics
            cursor = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    SUM(quota_cost) as total_quota,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls
                FROM api_usage
                WHERE date >= ?
                """,
                (cutoff_date,)
            )
            overall = cursor.fetchone()

            # Get daily statistics
            cursor = self._conn.execute(
                """
                SELECT
                    date,
                    COUNT(*) as calls,
                    SUM(quota_cost) as quota_used,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                FROM api_usage
                WHERE date >= ?
                GROUP BY date
                ORDER BY date DESC
                """,
                (cutoff_date,)
            )
            daily_stats = [dict(row) for row in cursor.fetchall()]

            # Get method breakdown
            cursor = self._conn.execute(
                """
                SELECT
                    api_method,
                    COUNT(*) as calls,
                    SUM(quota_cost) as quota_used,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                FROM api_usage
                WHERE date >= ?
                GROUP BY api_method
                ORDER BY calls DESC
                """,
                (cutoff_date,)
            )
            method_breakdown = [dict(row) for row in cursor.fetchall()]

            return {
                'period_days': days,
                'total_calls': overall['total_calls'] or 0,
                'total_quota': overall['total_quota'] or 0,
                'successful_calls': overall['successful_calls'] or 0,
                'failed_calls': overall['failed_calls'] or 0,
                'daily_stats': daily_stats,
                'method_breakdown': method_breakdown
            }

    def get_daily_usage(self, date_str: str = None) -> Dict[str, Any]:
        """
        Get API usage for a specific day.

        Args:
            date_str: Date in YYYY-MM-DD format (default: today)

        Returns:
            Dictionary with daily usage statistics
        """
        if not date_str:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    SUM(quota_cost) as total_quota,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls
                FROM api_usage
                WHERE date = ?
                """,
                (date_str,)
            )
            overall = cursor.fetchone()

            cursor = self._conn.execute(
                """
                SELECT
                    api_method,
                    COUNT(*) as calls,
                    SUM(quota_cost) as quota_used
                FROM api_usage
                WHERE date = ?
                GROUP BY api_method
                ORDER BY calls DESC
                """,
                (date_str,)
            )
            methods = [dict(row) for row in cursor.fetchall()]

            return {
                'date': date_str,
                'total_calls': overall['total_calls'] or 0,
                'total_quota': overall['total_quota'] or 0,
                'successful_calls': overall['successful_calls'] or 0,
                'failed_calls': overall['failed_calls'] or 0,
                'method_breakdown': methods
            }

    def get_hourly_usage(self, date_str: str = None) -> List[Dict[str, Any]]:
        """
        Get hourly API usage for a specific day.

        Args:
            date_str: Date in YYYY-MM-DD format (default: today)

        Returns:
            List of hourly usage statistics
        """
        if not date_str:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    strftime('%H', timestamp) as hour,
                    COUNT(*) as calls,
                    SUM(quota_cost) as quota_used,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                FROM api_usage
                WHERE date = ?
                GROUP BY hour
                ORDER BY hour
                """,
                (date_str,)
            )
            return [dict(row) for row in cursor.fetchall()]
