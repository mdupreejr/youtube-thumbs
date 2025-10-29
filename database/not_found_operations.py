"""
Not found search cache database operations.
"""
import os
import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from logger import logger
from video_helpers import get_content_hash
from error_handler import log_and_suppress, validate_environment_variable


class NotFoundOperations:
    """Handles caching of failed search attempts to prevent repeat API calls."""

    def __init__(self, db_connection):
        self.db = db_connection
        self._conn = db_connection.connection
        self._lock = db_connection.lock
        self._timestamp = db_connection.timestamp
        # Make cache duration configurable via environment variable
        self.cache_hours = validate_environment_variable(
            'NOT_FOUND_CACHE_HOURS',
            default=24,
            converter=int,
            validator=lambda x: 1 <= x <= 168  # 1 hour to 1 week
        )

    def is_recently_not_found(
        self,
        title: str,
        artist: Optional[str] = None,
        duration: Optional[int] = None
    ) -> bool:
        """
        Check if this content was recently searched and not found.

        Args:
            title: Media title
            artist: Media artist (optional) - stored for debugging but not used in hash
            duration: Media duration in seconds (optional)

        Returns:
            True if search failed within cache period, False otherwise

        Note:
            The artist parameter is intentionally not used in the content hash.
            This is because:
            1. YouTube search already considers all text in the query
            2. Different artists might have the same song title/duration
            3. We want to avoid repeated searches even if artist metadata varies
            The artist is still stored in the database for debugging purposes.
        """
        if not title:
            return False

        # Use content hash for consistent identification
        search_hash = get_content_hash(title, duration)

        with self._lock:
            cur = self._conn.execute(
                """
                SELECT last_attempted, attempt_count
                FROM not_found_searches
                WHERE search_hash = ?
                  AND last_attempted > datetime('now', '-' || ? || ' hours')
                """,
                (search_hash, self.cache_hours)
            )
            row = cur.fetchone()

        if row:
            last_attempted = row['last_attempted']
            attempt_count = row['attempt_count']
            logger.info(
                "Skipping search for '%s' - not found %d times, last attempt: %s",
                title, attempt_count, last_attempted
            )
            return True

        return False

    def record_not_found(
        self,
        title: str,
        artist: Optional[str] = None,
        duration: Optional[int] = None,
        search_query: Optional[str] = None
    ) -> bool:
        """
        Record a failed search attempt.

        Args:
            title: Media title that wasn't found
            artist: Media artist (optional) - stored for debugging but not used in hash
            duration: Media duration in seconds (optional)
            search_query: The actual query sent to YouTube (optional)

        Returns:
            True if successfully recorded, False otherwise

        Note:
            Artist is stored in the database for debugging but not included
            in the content hash to maximize cache hits across artist variations.
        """
        if not title:
            return False

        search_hash = get_content_hash(title, duration)
        timestamp = self._timestamp('')

        with self._lock:
            try:
                with self._conn:
                    # Use UPSERT syntax to handle race conditions atomically
                    self._conn.execute(
                        """
                        INSERT INTO not_found_searches
                        (search_hash, title, artist, duration, search_query, last_attempted, attempt_count)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                        ON CONFLICT(search_hash) DO UPDATE SET
                            last_attempted = excluded.last_attempted,
                            attempt_count = attempt_count + 1,
                            search_query = COALESCE(excluded.search_query, search_query)
                        """,
                        (search_hash, title, artist, duration, search_query, timestamp)
                    )
                    logger.info(
                        "Cached not found result for '%s' (duration: %s)",
                        title, duration
                    )
                    return True

            except sqlite3.DatabaseError as exc:
                # Re-raise for critical failures
                if "no such table" in str(exc).lower():
                    raise
                return log_and_suppress(
                    exc,
                    "Failed to record not found search for '%s'",
                    title,
                    level="error",
                    return_value=False
                )

    def cleanup_old_entries(self, days: int = 2) -> int:
        """
        Remove old entries from the not found cache.

        Args:
            days: Remove entries older than this many days

        Returns:
            Number of entries removed
        """
        with self._lock:
            try:
                with self._conn:
                    cur = self._conn.execute(
                        """
                        DELETE FROM not_found_searches
                        WHERE datetime(last_attempted, '+' || ? || ' days') < datetime('now')
                        """,
                        (days,)
                    )
                    deleted = cur.rowcount
                    if deleted > 0:
                        logger.info(
                            "Cleaned up %d old entries from not found cache (older than %d days)",
                            deleted, days
                        )
                    return deleted
            except sqlite3.DatabaseError as exc:
                return log_and_suppress(
                    exc,
                    "Failed to cleanup not found cache",
                    level="error",
                    return_value=0
                )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the not found cache.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM not_found_searches").fetchone()[0]
            recent = self._conn.execute(
                """
                SELECT COUNT(*) FROM not_found_searches
                WHERE last_attempted > datetime('now', '-' || ? || ' hours')
                """,
                (self.cache_hours,)
            ).fetchone()[0]

        return {
            'total_cached': total,
            'recent_cached': recent,
            'cache_hours': self.cache_hours
        }