"""
Database operations for logging system.

Provides methods to query rated songs, match history, and match details
for the logs viewer UI.
"""

import threading
from typing import Dict, Any, List
from datetime import datetime, timedelta


class LogsOperations:
    """Handles database operations for logs viewer."""

    def __init__(self, conn, lock: threading.Lock):
        """
        Initialize logs operations.

        Args:
            conn: SQLite database connection
            lock: Threading lock for database access
        """
        self._conn = conn
        self._lock = lock

    def _get_period_timestamp(self, period: str) -> str:
        """
        Convert period filter to timestamp.

        Args:
            period: 'hour', 'day', 'week', 'month', or 'all'

        Returns:
            ISO format timestamp string, or None for 'all'
        """
        if period == 'all':
            return None

        now = datetime.now()
        if period == 'hour':
            cutoff = now - timedelta(hours=1)
        elif period == 'day':
            cutoff = now - timedelta(days=1)
        elif period == 'week':
            cutoff = now - timedelta(weeks=1)
        elif period == 'month':
            cutoff = now - timedelta(days=30)
        else:
            return None

        return cutoff.strftime('%Y-%m-%d %H:%M:%S')

    def get_rated_songs(
        self,
        page: int = 1,
        limit: int = 50,
        period: str = 'all',
        rating_filter: str = 'all'
    ) -> Dict[str, Any]:
        """
        Get paginated list of rated songs with filters.

        Args:
            page: Page number (1-indexed)
            limit: Number of songs per page
            period: Time period filter ('hour', 'day', 'week', 'month', 'all')
            rating_filter: Rating type filter ('like', 'dislike', 'all')

        Returns:
            Dictionary with songs list, pagination info, and total count
        """
        # Build WHERE clause
        where_conditions = ["rating != 'none'"]
        params = []

        # Add period filter
        period_timestamp = self._get_period_timestamp(period)
        if period_timestamp:
            where_conditions.append("date_last_played >= ?")
            params.append(period_timestamp)

        # Add rating filter
        if rating_filter in ['like', 'dislike']:
            where_conditions.append("rating = ?")
            params.append(rating_filter)

        where_clause = " AND ".join(where_conditions)

        with self._lock:
            # Get total count
            count_query = f"SELECT COUNT(*) as count FROM video_ratings WHERE {where_clause}"
            cursor = self._conn.execute(count_query, params)
            total_count = cursor.fetchone()['count']

        # Handle empty results
        if total_count == 0:
            return {
                'songs': [],
                'page': 1,
                'total_pages': 0,
                'total_count': 0
            }

        # Calculate pagination
        total_pages = (total_count + limit - 1) // limit
        page = max(1, min(page, total_pages))
        offset = (page - 1) * limit

        with self._lock:
            # Get rated songs
            query = f"""
                SELECT yt_video_id, ha_title, ha_artist, yt_title, yt_channel,
                       rating, date_last_played, play_count, source
                FROM video_ratings
                WHERE {where_clause}
                ORDER BY date_last_played DESC
                LIMIT ? OFFSET ?
            """
            cursor = self._conn.execute(query, params + [limit, offset])
            songs = cursor.fetchall()

        # Convert to list of dicts
        songs_list = [dict(song) for song in songs]

        return {
            'songs': songs_list,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count
        }

    def get_match_history(
        self,
        page: int = 1,
        limit: int = 50,
        period: str = 'all'
    ) -> Dict[str, Any]:
        """
        Get paginated list of YouTube matches.

        Args:
            page: Page number (1-indexed)
            limit: Number of matches per page
            period: Time period filter ('hour', 'day', 'week', 'month', 'all')

        Returns:
            Dictionary with matches list, pagination info, and total count
        """
        # Build WHERE clause
        where_conditions = ["yt_match_pending = 0", "yt_video_id IS NOT NULL"]
        params = []

        # Add period filter
        period_timestamp = self._get_period_timestamp(period)
        if period_timestamp:
            where_conditions.append("date_added >= ?")
            params.append(period_timestamp)

        where_clause = " AND ".join(where_conditions)

        with self._lock:
            # Get total count
            count_query = f"SELECT COUNT(*) as count FROM video_ratings WHERE {where_clause}"
            cursor = self._conn.execute(count_query, params)
            total_count = cursor.fetchone()['count']

        # Handle empty results
        if total_count == 0:
            return {
                'matches': [],
                'page': 1,
                'total_pages': 0,
                'total_count': 0
            }

        # Calculate pagination
        total_pages = (total_count + limit - 1) // limit
        page = max(1, min(page, total_pages))
        offset = (page - 1) * limit

        with self._lock:
            # Get match history
            query = f"""
                SELECT yt_video_id, ha_title, ha_artist, ha_duration,
                       yt_title, yt_channel, yt_duration,
                       date_added, yt_match_attempts, play_count
                FROM video_ratings
                WHERE {where_clause}
                ORDER BY date_added DESC
                LIMIT ? OFFSET ?
            """
            cursor = self._conn.execute(query, params + [limit, offset])
            matches = cursor.fetchall()

        # Convert to list of dicts
        matches_list = [dict(match) for match in matches]

        return {
            'matches': matches_list,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count
        }

    def get_match_details(self, yt_video_id: str) -> Dict[str, Any]:
        """
        Get full match details for a single video.

        Args:
            yt_video_id: YouTube video ID

        Returns:
            Dictionary with all match information, or None if not found
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT yt_video_id, ha_title, ha_artist, ha_duration,
                       yt_title, yt_channel, yt_duration, yt_url,
                       date_added, yt_match_attempts, play_count,
                       yt_match_pending, source
                FROM video_ratings
                WHERE yt_video_id = ?
                """,
                (yt_video_id,)
            )
            result = cursor.fetchone()

        if result:
            return dict(result)
        return None
