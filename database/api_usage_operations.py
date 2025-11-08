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
        Record an API call for aggregate hourly usage tracking.
        Increments the hourly counter by quota_cost for the current date and hour.

        Args:
            api_method: The YouTube API method called (unused in aggregate tracking)
            success: Whether the call succeeded (unused in aggregate tracking)
            quota_cost: Quota units consumed (added to hourly total)
            error_message: Optional error message if call failed (unused in aggregate tracking)

        Note: This tracks aggregate quota usage per hour. For detailed call logs,
              use log_api_call_detailed() instead.
        """
        with self._lock:
            now = datetime.utcnow()
            date_str = now.strftime('%Y-%m-%d')
            hour = now.hour

            # Validate hour is within expected range
            if not (0 <= hour <= 23):
                raise ValueError(f"Invalid hour: {hour}")

            hour_col = f"hour_{hour:02d}"

            # Insert or update the row for today, incrementing by quota_cost
            # nosec B608 - hour_col is validated to be hour_00 through hour_23 (line 40)
            self._conn.execute(
                f"""
                INSERT INTO api_usage (date, {hour_col})
                VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET {hour_col} = {hour_col} + ?
                """,
                (date_str, quota_cost, quota_cost)
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

    def log_api_call_detailed(
        self,
        api_method: str,
        operation_type: str = None,
        query_params: str = None,
        quota_cost: int = 1,
        success: bool = True,
        error_message: str = None,
        results_count: int = None,
        context: str = None
    ) -> None:
        """
        Log a detailed API call for analysis and debugging.

        Args:
            api_method: The YouTube API method called (e.g., 'search', 'videos.list')
            operation_type: Type of operation (e.g., 'search_video', 'get_details')
            query_params: Search query or request parameters (truncated for storage)
            quota_cost: Quota units consumed (search=100, videos.list=1, etc.)
            success: Whether the call succeeded
            error_message: Error message if call failed
            results_count: Number of results returned
            context: Additional context (e.g., 'manual_retry', 'history_tracker')
        """
        with self._lock:
            # Truncate long parameters to avoid bloating database
            if query_params and len(query_params) > 500:
                query_params = query_params[:497] + '...'

            if error_message and len(error_message) > 500:
                error_message = error_message[:497] + '...'

            if context and len(context) > 200:
                context = context[:197] + '...'

            self._conn.execute(
                """
                INSERT INTO api_call_log (
                    api_method, operation_type, query_params, quota_cost,
                    success, error_message, results_count, context
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (api_method, operation_type, query_params, quota_cost,
                 success, error_message, results_count, context)
            )
            self._conn.commit()

    def get_api_call_log(
        self,
        limit: int = 100,
        offset: int = 0,
        method_filter: str = None,
        success_filter: bool = None
    ) -> Dict[str, Any]:
        """
        Get detailed API call logs with pagination.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
            method_filter: Filter by API method (optional)
            success_filter: Filter by success status (optional)

        Returns:
            Dictionary with logs and pagination info
        """
        with self._lock:
            # Build query with filters
            where_clauses = []
            params = []

            if method_filter:
                where_clauses.append("api_method = ?")
                params.append(method_filter)

            if success_filter is not None:
                where_clauses.append("success = ?")
                params.append(1 if success_filter else 0)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            # Get total count
            # SECURITY WARNING: Using f-string for SQL query construction
            # This is ONLY safe because where_sql contains HARDCODED SQL fragments
            # NEVER add user input directly to where_sql - always use parameterized queries (?)
            # All user inputs MUST go through the params list
            count_query = f"SELECT COUNT(*) as count FROM api_call_log WHERE {where_sql}"
            cursor = self._conn.execute(count_query, params)
            total_count = cursor.fetchone()['count']

            # Get logs
            log_query = f"""
                SELECT * FROM api_call_log
                WHERE {where_sql}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """
            cursor = self._conn.execute(log_query, params + [limit, offset])
            logs = [dict(row) for row in cursor.fetchall()]

            return {
                'logs': logs,
                'total_count': total_count,
                'limit': limit,
                'offset': offset
            }

    def get_api_call_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get summary statistics of API calls for the last N hours.

        Args:
            hours: Number of hours to look back

        Returns:
            Dictionary with summary statistics
        """
        with self._lock:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)

            # Total calls and quota
            cursor = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    SUM(quota_cost) as total_quota,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls
                FROM api_call_log
                WHERE timestamp >= ?
                """,
                (cutoff_time,)
            )
            summary = dict(cursor.fetchone())

            # Breakdown by method
            cursor = self._conn.execute(
                """
                SELECT
                    api_method,
                    COUNT(*) as call_count,
                    SUM(quota_cost) as quota_used
                FROM api_call_log
                WHERE timestamp >= ?
                GROUP BY api_method
                ORDER BY quota_used DESC
                """,
                (cutoff_time,)
            )
            by_method = [dict(row) for row in cursor.fetchall()]

            # Breakdown by operation type
            cursor = self._conn.execute(
                """
                SELECT
                    operation_type,
                    COUNT(*) as call_count,
                    SUM(quota_cost) as quota_used
                FROM api_call_log
                WHERE timestamp >= ? AND operation_type IS NOT NULL
                GROUP BY operation_type
                ORDER BY quota_used DESC
                """,
                (cutoff_time,)
            )
            by_operation = [dict(row) for row in cursor.fetchall()]

            return {
                'period_hours': hours,
                'summary': summary,
                'by_method': by_method,
                'by_operation': by_operation
            }
