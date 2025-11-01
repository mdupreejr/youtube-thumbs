"""
Server-side statistics caching operations.
All statistics are pre-computed on the server and cached in the database.
NO client-side JavaScript processing required.
"""
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


class StatsCacheOperations:
    """Handles server-side statistics caching."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    def get_cached_stats(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached statistics if available and not expired.

        Args:
            cache_key: Unique identifier for the cached data

        Returns:
            Cached data as dict, or None if expired/not found
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT cache_data, expires_at
                FROM stats_cache
                WHERE cache_key = ?
                """,
                (cache_key,)
            )
            result = cursor.fetchone()

            if not result:
                return None

            # Check if expired
            # Handle both string and datetime types (SQLite may return either)
            expires_at_raw = result['expires_at']
            if isinstance(expires_at_raw, str):
                expires_at = datetime.fromisoformat(expires_at_raw.replace(' ', 'T'))
            elif isinstance(expires_at_raw, datetime):
                expires_at = expires_at_raw
            else:
                # Invalid type, delete cache entry and return None
                self._conn.execute("DELETE FROM stats_cache WHERE cache_key = ?", (cache_key,))
                self._conn.commit()
                return None

            if datetime.utcnow() > expires_at:
                # Expired, delete and return None
                self._conn.execute("DELETE FROM stats_cache WHERE cache_key = ?", (cache_key,))
                self._conn.commit()
                return None

            # Return cached data
            return json.loads(result['cache_data'])

    def set_cached_stats(self, cache_key: str, data: Dict[str, Any], ttl_seconds: int = 300) -> None:
        """
        Store statistics in cache.

        Args:
            cache_key: Unique identifier for the cached data
            data: Statistics data to cache (will be JSON serialized)
            ttl_seconds: Time to live in seconds (default 5 minutes)
        """
        with self._lock:
            generated_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            expires_at = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).strftime('%Y-%m-%d %H:%M:%S')
            cache_data = json.dumps(data)

            self._conn.execute(
                """
                INSERT OR REPLACE INTO stats_cache (cache_key, cache_data, generated_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (cache_key, cache_data, generated_at, expires_at)
            )
            self._conn.commit()

    def invalidate_cache(self, cache_key: Optional[str] = None) -> None:
        """
        Invalidate cached statistics.

        Args:
            cache_key: Specific key to invalidate, or None to clear all
        """
        with self._lock:
            if cache_key:
                self._conn.execute("DELETE FROM stats_cache WHERE cache_key = ?", (cache_key,))
            else:
                self._conn.execute("DELETE FROM stats_cache")
            self._conn.commit()

    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            cursor = self._conn.execute(
                "DELETE FROM stats_cache WHERE expires_at < ?",
                (now,)
            )
            self._conn.commit()
            return cursor.rowcount
