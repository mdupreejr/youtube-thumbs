"""
Operations for opportunistic search results caching.
Stores all videos from YouTube searches (not just matched ones) to reduce API calls.
"""
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from logger import logger


class SearchCacheOperations:
    """Handles opportunistic caching of YouTube search results."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    def cache_search_results(self, videos: List[Dict[str, Any]], ttl_days: int = 30) -> int:
        """
        Cache all videos from a search result for future lookups.

        Args:
            videos: List of video dicts from YouTube API
            ttl_days: Time to live in days (default 30)

        Returns:
            Number of videos cached
        """
        if not videos:
            return 0

        expires_at = (datetime.utcnow() + timedelta(days=ttl_days)).strftime('%Y-%m-%d %H:%M:%S')
        cached_count = 0

        with self._lock:
            for video in videos:
                try:
                    yt_video_id = video.get('yt_video_id')
                    if not yt_video_id:
                        continue

                    # v4.0.46: Insert or update cache entry with ALL video fields
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO search_results_cache
                        (yt_video_id, yt_title, yt_channel, yt_channel_id, yt_duration,
                         yt_description, yt_published_at, yt_category_id, yt_live_broadcast,
                         yt_location, yt_recording_date, expires_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            yt_video_id,
                            video.get('title'),
                            video.get('channel'),
                            video.get('channel_id'),
                            video.get('duration'),
                            video.get('description'),
                            video.get('published_at'),
                            video.get('category_id'),
                            video.get('live_broadcast'),
                            video.get('location'),
                            video.get('recording_date'),
                            expires_at
                        )
                    )
                    cached_count += 1
                except Exception as exc:
                    logger.warning(f"Failed to cache video {video.get('yt_video_id')}: {exc}")
                    continue

            self._conn.commit()

        # Note: Logging moved to caller (youtube_api.py) to provide more context
        # The caller logs: "Opportunistically cached X/Y videos checked during search (Z duration matches)"
        return cached_count

    def find_by_duration(self, duration: int, tolerance: int = 2) -> Optional[List[Dict[str, Any]]]:
        """
        Find cached videos matching duration (with tolerance).

        Args:
            duration: Target duration in seconds
            tolerance: Allowed difference in seconds (default ±2)

        Returns:
            List of matching cached videos, or None if not found
        """
        min_duration = duration - tolerance
        max_duration = duration + tolerance

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT yt_video_id, yt_title, yt_channel, yt_channel_id, yt_duration,
                       yt_description, yt_published_at, yt_category_id, yt_live_broadcast,
                       yt_location, yt_recording_date
                FROM search_results_cache
                WHERE yt_duration BETWEEN ? AND ?
                  AND expires_at > datetime('now')
                ORDER BY yt_duration
                LIMIT 25
                """,
                (min_duration, max_duration)
            )
            results = cursor.fetchall()

            if results:
                return [dict(row) for row in results]

        return None

    def find_by_title_and_duration(self, title: str, duration: int, tolerance: int = 2) -> Optional[Dict[str, Any]]:
        """
        Find cached video matching title and duration.

        Args:
            title: Video title to match (case-insensitive partial match)
            duration: Target duration in seconds
            tolerance: Allowed difference in seconds (default ±2)

        Returns:
            Matching cached video dict, or None if not found
        """
        min_duration = duration - tolerance
        max_duration = duration + tolerance

        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT yt_video_id, yt_title, yt_channel, yt_channel_id, yt_duration,
                       yt_description, yt_published_at, yt_category_id, yt_live_broadcast,
                       yt_location, yt_recording_date
                FROM search_results_cache
                WHERE yt_duration BETWEEN ? AND ?
                  AND yt_title LIKE ?
                  AND expires_at > datetime('now')
                ORDER BY yt_duration
                LIMIT 1
                """,
                (min_duration, max_duration, f"%{title}%")
            )
            result = cursor.fetchone()

            if result:
                logger.info(f"Search cache HIT: '{title}' → {result['yt_video_id']}")
                return dict(result)

        return None

    def cleanup_expired(self) -> int:
        """
        Remove expired cache entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM search_results_cache WHERE expires_at < datetime('now')"
            )
            self._conn.commit()
            deleted = cursor.rowcount

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired search cache entries")

            return deleted

    def get_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats (total, expired, valid)
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN expires_at < datetime('now') THEN 1 ELSE 0 END) as expired,
                    SUM(CASE WHEN expires_at >= datetime('now') THEN 1 ELSE 0 END) as valid
                FROM search_results_cache
                """
            )
            result = cursor.fetchone()
            return dict(result) if result else {'total': 0, 'expired': 0, 'valid': 0}
