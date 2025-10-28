"""
Import history database operations.
"""
import sqlite3
from typing import Dict, Any

from logger import logger


class ImportOperations:
    """Handles import history tracking operations."""

    def __init__(self, db_connection):
        self.db = db_connection
        self._conn = db_connection.connection
        self._lock = db_connection.lock

    def import_entry_exists(self, entry_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM import_history WHERE entry_id = ?",
                (entry_id,),
            )
            return cur.fetchone() is not None

    def log_import_entry(self, entry_id: str, source: str, yt_video_id: str) -> None:
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO import_history (entry_id, source, yt_video_id)
                        VALUES (?, ?, ?)
                        """,
                        (entry_id, source, yt_video_id),
                    )
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to log import entry %s: %s", entry_id, exc)