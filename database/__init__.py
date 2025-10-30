"""
Database module for YouTube Thumbs addon.
Provides a unified interface for all database operations.
"""
from pathlib import Path
from typing import Optional, Dict, Any, List

from .connection import DatabaseConnection, DEFAULT_DB_PATH
from .video_operations import VideoOperations
from .pending_operations import PendingOperations
from .import_operations import ImportOperations
from .not_found_operations import NotFoundOperations
from .stats_operations import StatsOperations


class Database:
    """
    Unified database interface that combines all operations.
    Maintains backward compatibility with the original database.py.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        # Initialize connection
        self._connection = DatabaseConnection(db_path)

        # Initialize operation modules
        self._video_ops = VideoOperations(self._connection)
        self._pending_ops = PendingOperations(self._connection, self._video_ops)
        self._import_ops = ImportOperations(self._connection)
        self._not_found_ops = NotFoundOperations(self._connection)
        self._stats_ops = StatsOperations(self._connection)

        # Expose connection properties for backward compatibility
        self.db_path = db_path
        self._conn = self._connection.connection
        self._lock = self._connection.lock

    # Connection methods
    def _table_info(self, table: str):
        return self._connection._table_info(table)

    def _table_columns(self, table: str):
        return self._connection._table_columns(table)

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

    # Pending operations
    def upsert_pending_media(self, media):
        return self._pending_ops.upsert_pending_media(media)

    def enqueue_rating(self, yt_video_id, rating):
        return self._pending_ops.enqueue_rating(yt_video_id, rating)

    def list_pending_ratings(self, limit=10):
        return self._pending_ops.list_pending_ratings(limit)

    def mark_pending_rating(self, yt_video_id, success, error=None):
        return self._pending_ops.mark_pending_rating(yt_video_id, success, error)

    # Import operations
    def import_entry_exists(self, entry_id):
        return self._import_ops.import_entry_exists(entry_id)

    def log_import_entry(self, entry_id, source, yt_video_id):
        return self._import_ops.log_import_entry(entry_id, source, yt_video_id)

    # Not found cache operations
    def is_recently_not_found(self, title: str, artist: Optional[str] = None, duration: Optional[int] = None) -> bool:
        return self._not_found_ops.is_recently_not_found(title, artist, duration)

    def record_not_found(self, title: str, artist: Optional[str] = None, duration: Optional[int] = None, search_query: Optional[str] = None) -> bool:
        return self._not_found_ops.record_not_found(title, artist, duration, search_query)

    def cleanup_old_not_found(self, days: int = 2) -> int:
        return self._not_found_ops.cleanup_old_entries(days)

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