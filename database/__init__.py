"""
Database module for YouTube Thumbs addon.
Provides a unified interface for all database operations.
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from .connection import DatabaseConnection, DEFAULT_DB_PATH
from .video_operations import VideoOperations
from .pending_operations import PendingOperations
from .stats_operations import StatsOperations
from .api_usage_operations import APIUsageOperations
from .stats_cache_operations import StatsCacheOperations
from .search_cache_operations import SearchCacheOperations
from .logs_operations import LogsOperations
from video_helpers import get_content_hash
from error_handler import validate_environment_variable


class Database:
    """
    Unified database interface that combines all operations.
    Maintains backward compatibility with the original database.py.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        # Initialize connection
        self._connection = DatabaseConnection(db_path)

        # Expose connection properties for backward compatibility
        self.db_path = db_path
        self._conn = self._connection.connection
        self._lock = self._connection.lock

        # Initialize operation modules
        self._video_ops = VideoOperations(self._connection)
        self._pending_ops = PendingOperations(self._connection, self._video_ops)
        self._stats_ops = StatsOperations(self._connection)
        self._api_usage_ops = APIUsageOperations(self._conn, self._lock)
        self._stats_cache_ops = StatsCacheOperations(self._conn, self._lock)
        self._search_cache_ops = SearchCacheOperations(self._conn, self._lock)
        self._logs_ops = LogsOperations(self._conn, self._lock)

        # Not found cache configuration (previously in NotFoundOperations)
        # Default to 7 days (168 hours) to prevent wasting quota on failed searches
        self._not_found_cache_hours = validate_environment_variable(
            'NOT_FOUND_CACHE_HOURS',
            default=168,
            converter=int,
            validator=lambda x: 1 <= x <= 168  # 1 hour to 1 week
        )

    # Connection methods
    @staticmethod
    def _timestamp(ts: Optional[str] = None) -> Optional[str]:
        return DatabaseConnection.timestamp(ts)

    @staticmethod
    def _pending_video_id(title: str, channel: Optional[str], duration: Optional[int]) -> str:
        return PendingOperations._pending_video_id(title, channel, duration)

    # Video operations
    def upsert_video(self, video, date_added=None):
        return self._video_ops.upsert_video(video, date_added)

    def record_play(self, yt_video_id, timestamp=None):
        return self._video_ops.record_play(yt_video_id, timestamp)

    def record_rating(self, yt_video_id, rating, timestamp=None):
        return self._video_ops.record_rating(yt_video_id, rating, timestamp)

    def record_rating_local(self, yt_video_id, rating, timestamp=None):
        return self._video_ops.record_rating_local(yt_video_id, rating, timestamp)

    def get_video(self, yt_video_id):
        return self._video_ops.get_video(yt_video_id)

    def find_by_title_and_duration(self, title, duration):
        return self._video_ops.find_by_title_and_duration(title, duration)

    def find_by_content_hash(self, title, duration, artist=None):
        return self._video_ops.find_by_content_hash(title, duration, artist)

    def find_cached_video_combined(self, title: str, duration: int, artist: Optional[str] = None):
        return self._video_ops.find_cached_video_combined(title, duration, artist)

    def get_pending_videos(self, limit: int = 50, reason_filter: Optional[str] = None):
        return self._video_ops.get_pending_videos(limit, reason_filter)

    def resolve_pending_video(self, ha_content_id: str, youtube_data: Dict):
        return self._video_ops.resolve_pending_video(ha_content_id, youtube_data)

    def mark_pending_not_found(self, ha_content_id: str):
        return self._video_ops.mark_pending_not_found(ha_content_id)

    def cleanup_unknown_entries(self) -> Dict[str, int]:
        return self._video_ops.cleanup_unknown_entries()

    # Pending operations
    def upsert_pending_media(self, media, reason: str = 'quota_exceeded'):
        return self._pending_ops.upsert_pending_media(media, reason)

    def enqueue_rating(self, yt_video_id, rating):
        return self._pending_ops.enqueue_rating(yt_video_id, rating)

    def list_pending_ratings(self, limit=10):
        return self._pending_ops.list_pending_ratings(limit)

    def mark_pending_rating(self, yt_video_id, success, error=None):
        return self._pending_ops.mark_pending_rating(yt_video_id, success, error)

    # Not found cache operations (v1.64.0: consolidated into video_ratings table)
    def is_recently_not_found(self, title: str, artist: Optional[str] = None, duration: Optional[int] = None) -> bool:
        """
        Check if this content was recently searched and not found.
        Now queries video_ratings table instead of separate not_found_searches table.

        Args:
            title: Media title
            artist: Media artist (optional, used in hash for accurate matching)
            duration: Media duration in seconds (optional)

        Returns:
            True if search failed within cache period, False otherwise
        """
        if not title:
            return False

        # Use content hash for consistent identification (MUST include artist to match recording)
        content_hash = get_content_hash(title, duration, artist)

        with self._lock:
            cur = self._conn.execute(
                """
                SELECT ha_content_id, yt_match_last_attempt, yt_match_attempts
                FROM video_ratings
                WHERE ha_content_hash = ?
                  AND yt_video_id IS NULL
                  AND pending_reason = 'not_found'
                  AND yt_match_last_attempt > datetime('now', '-' || ? || ' hours')
                """,
                (content_hash, self._not_found_cache_hours)
            )
            row = cur.fetchone()

        if row:
            from logger import logger
            logger.debug(
                "Skipping search for '%s' - not found %d times, last attempt: %s",
                title, row['yt_match_attempts'], row['yt_match_last_attempt']
            )
            return True

        return False

    def record_not_found(self, title: str, artist: Optional[str] = None, duration: Optional[int] = None, search_query: Optional[str] = None) -> bool:
        """
        Record a failed search attempt.
        Now uses video_ratings table instead of separate not_found_searches table.

        Args:
            title: Media title that wasn't found
            artist: Media artist (optional)
            duration: Media duration in seconds (optional)
            search_query: The actual query sent to YouTube (optional, deprecated)

        Returns:
            True if successfully recorded, False otherwise
        """
        if not title:
            return False

        # Use upsert_pending_media with reason='not_found'
        media = {
            'title': title,
            'artist': artist,
            'duration': duration
        }

        try:
            self.upsert_pending_media(media, reason='not_found')
            from logger import logger
            logger.info(
                "Cached not found result for '%s' (duration: %s)",
                title, duration
            )
            return True
        except Exception as exc:
            from logger import logger
            from error_handler import log_and_suppress
            return log_and_suppress(
                exc,
                "Failed to record not found search for '%s'",
                title,
                level="error",
                return_value=False
            )

    def cleanup_old_not_found(self, days: int = 2) -> int:
        """
        Remove old not found entries from video_ratings.
        Now operates on video_ratings table instead of separate not_found_searches table.

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
                        DELETE FROM video_ratings
                        WHERE yt_video_id IS NULL
                          AND pending_reason = 'not_found'
                          AND datetime(yt_match_last_attempt, '+' || ? || ' days') < datetime('now')
                        """,
                        (days,)
                    )
                    deleted = cur.rowcount
                    if deleted > 0:
                        from logger import logger
                        logger.info(
                            "Cleaned up %d old not found entries (older than %d days)",
                            deleted, days
                        )
                    return deleted
            except Exception as exc:
                from logger import logger
                from error_handler import log_and_suppress
                return log_and_suppress(
                    exc,
                    "Failed to cleanup not found cache",
                    level="error",
                    return_value=0
                )

    # Stats operations
    def get_total_videos(self) -> int:
        return self._stats_ops.get_total_videos()

    def get_total_plays(self) -> int:
        return self._stats_ops.get_total_plays()

    def get_ratings_breakdown(self) -> Dict[str, int]:
        return self._stats_ops.get_ratings_breakdown()

    def get_most_played(self, limit: int = 10) -> List[Dict]:
        return self._stats_ops.get_most_played(limit)

    def get_top_rated(self, limit: int = 10) -> List[Dict]:
        return self._stats_ops.get_top_rated(limit)

    def get_recent_activity(self, limit: int = 20) -> List[Dict]:
        return self._stats_ops.get_recent_activity(limit)

    def get_rated_videos(self, rating: str, page: int = 1, per_page: int = 50) -> Dict:
        return self._stats_ops.get_rated_videos(rating, page, per_page)

    def get_top_channels(self, limit: int = 10) -> List[Dict]:
        return self._stats_ops.get_top_channels(limit)

    def get_category_breakdown(self) -> List[Dict]:
        return self._stats_ops.get_category_breakdown()

    def get_plays_by_period(self, days: int = 7) -> List[Dict]:
        return self._stats_ops.get_plays_by_period(days)

    def get_recent_additions(self, days: int = 7) -> List[Dict]:
        return self._stats_ops.get_recent_additions(days)

    def get_stats_summary(self) -> Dict[str, Any]:
        return self._stats_ops.get_summary()

    def get_play_history(self, limit: int = 100, offset: int = 0,
                         date_from: Optional[str] = None,
                         date_to: Optional[str] = None) -> List[Dict]:
        return self._stats_ops.get_play_history(limit, offset, date_from, date_to)

    def get_rating_history(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        return self._stats_ops.get_rating_history(limit, offset)

    def search_history(self, query: str, limit: int = 50) -> List[Dict]:
        return self._stats_ops.search_history(query, limit)

    def get_listening_patterns(self) -> Dict:
        return self._stats_ops.get_listening_patterns()

    def get_discovery_stats(self) -> List[Dict]:
        return self._stats_ops.get_discovery_stats()

    def get_play_distribution(self) -> List[Dict]:
        return self._stats_ops.get_play_distribution()

    def get_correlation_stats(self) -> Dict:
        return self._stats_ops.get_correlation_stats()

    def get_retention_analysis(self) -> List[Dict]:
        return self._stats_ops.get_retention_analysis()

    def get_source_breakdown(self) -> List[Dict]:
        return self._stats_ops.get_source_breakdown()

    def get_duration_analysis(self) -> List[Dict]:
        return self._stats_ops.get_duration_analysis()

    def filter_videos(self, filters: Dict) -> Dict:
        return self._stats_ops.filter_videos(filters)

    def get_all_channels(self) -> List[Dict]:
        return self._stats_ops.get_all_channels()

    def get_all_categories(self) -> List[int]:
        return self._stats_ops.get_all_categories()

    def get_recommendations(self, based_on: str = 'likes', limit: int = 10) -> List[Dict]:
        return self._stats_ops.get_recommendations(based_on, limit)

    def get_unrated_videos(self, page: int = 1, limit: int = 50) -> Dict[str, Any]:
        return self._stats_ops.get_unrated_videos(page, limit)

    def get_pending_summary(self) -> Dict[str, Any]:
        return self._stats_ops.get_pending_summary()

    # API Usage Operations
    def record_api_call(self, api_method: str, success: bool = True, quota_cost: int = 1, error_message: str = None) -> None:
        """Record a YouTube API call for usage tracking."""
        return self._api_usage_ops.record_api_call(api_method, success, quota_cost, error_message)

    def get_api_usage_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get API usage summary for the last N days."""
        return self._api_usage_ops.get_usage_summary(days)

    def get_api_daily_usage(self, date_str: str = None) -> Dict[str, Any]:
        """Get API usage for a specific day."""
        return self._api_usage_ops.get_daily_usage(date_str)

    def get_api_hourly_usage(self, date_str: str = None) -> List[Dict[str, Any]]:
        """Get hourly API usage for a specific day."""
        return self._api_usage_ops.get_hourly_usage(date_str)

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
        """Log a detailed API call for analysis and debugging."""
        return self._api_usage_ops.log_api_call_detailed(
            api_method, operation_type, query_params, quota_cost,
            success, error_message, results_count, context
        )

    def get_api_call_log(
        self,
        limit: int = 100,
        offset: int = 0,
        method_filter: str = None,
        success_filter: bool = None
    ) -> Dict[str, Any]:
        """Get detailed API call logs with pagination."""
        return self._api_usage_ops.get_api_call_log(limit, offset, method_filter, success_filter)

    def get_api_call_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get summary statistics of API calls for the last N hours."""
        return self._api_usage_ops.get_api_call_summary(hours)

    # Stats Cache Operations
    def get_cached_stats(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached statistics."""
        return self._stats_cache_ops.get_cached_stats(cache_key)

    def set_cached_stats(self, cache_key: str, data: Dict[str, Any], ttl_seconds: int = 300) -> None:
        """Store statistics in cache."""
        return self._stats_cache_ops.set_cached_stats(cache_key, data, ttl_seconds)

    def invalidate_stats_cache(self, cache_key: Optional[str] = None) -> None:
        """Invalidate cached statistics."""
        return self._stats_cache_ops.invalidate_cache(cache_key)

    # Search Cache Operations (v1.67.1: Opportunistic caching)
    def cache_search_results(self, videos: List[Dict[str, Any]], ttl_days: int = 30) -> int:
        """Cache all videos from a search result."""
        return self._search_cache_ops.cache_search_results(videos, ttl_days)

    def find_in_search_cache_by_duration(self, duration: int, tolerance: int = 2) -> Optional[List[Dict[str, Any]]]:
        """Find cached videos by duration."""
        return self._search_cache_ops.find_by_duration(duration, tolerance)

    def find_in_search_cache(self, title: str, duration: int, tolerance: int = 2) -> Optional[Dict[str, Any]]:
        """Find cached video by title and duration."""
        return self._search_cache_ops.find_by_title_and_duration(title, duration, tolerance)

    def cleanup_search_cache(self) -> int:
        """Remove expired search cache entries."""
        return self._search_cache_ops.cleanup_expired()

    def get_search_cache_stats(self) -> Dict[str, int]:
        """Get search cache statistics."""
        return self._search_cache_ops.get_stats()

    # Logs Operations
    def get_rated_songs(self, page: int = 1, limit: int = 50, period: str = 'all', rating_filter: str = 'all') -> Dict[str, Any]:
        """Get paginated list of rated songs with filters."""
        return self._logs_ops.get_rated_songs(page, limit, period, rating_filter)

    def get_match_history(self, page: int = 1, limit: int = 50, period: str = 'all') -> Dict[str, Any]:
        """Get paginated list of YouTube matches."""
        return self._logs_ops.get_match_history(page, limit, period)

    def get_match_details(self, yt_video_id: str) -> Dict[str, Any]:
        """Get full match details for a single video."""
        return self._logs_ops.get_match_details(yt_video_id)

    def get_recently_added(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Get the most recently added videos/songs."""
        return self._logs_ops.get_recently_added(limit)


# Singleton instance management
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Return singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


# Export main classes and functions
__all__ = ['Database', 'get_database', 'DEFAULT_DB_PATH']