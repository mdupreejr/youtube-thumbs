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

    def find_by_title(self, title, limit=5):
        return self._video_ops.find_by_title(title, limit)

    def find_by_exact_ha_title(self, title):
        return self._video_ops.find_by_exact_ha_title(title)

    def find_by_title_and_duration(self, title, duration):
        return self._video_ops.find_by_title_and_duration(title, duration)

    def find_by_content_hash(self, title, duration, channel=None):
        return self._video_ops.find_by_content_hash(title, duration, channel)

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