"""
Database connection and schema management.
"""
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from logger import logger

DEFAULT_DB_PATH = Path(os.getenv('YTT_DB_PATH', '/config/youtube_thumbs/ratings.db'))


class DatabaseConnection:
    """Manages SQLite connection and schema."""

    VIDEO_RATINGS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS video_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            yt_video_id TEXT UNIQUE NOT NULL,
            ha_title TEXT NOT NULL,
            ha_artist TEXT,
            yt_title TEXT,
            yt_channel TEXT,
            yt_channel_id TEXT,
            yt_description TEXT,
            yt_published_at TIMESTAMP,
            yt_category_id INTEGER,
            yt_live_broadcast TEXT,
            yt_location TEXT,
            yt_recording_date TIMESTAMP,
            ha_duration INTEGER,
            yt_duration INTEGER,
            yt_url TEXT,
            rating TEXT DEFAULT 'none',
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_last_played TIMESTAMP,
            play_count INTEGER DEFAULT 1,
            rating_score INTEGER DEFAULT 0,
            pending_match INTEGER DEFAULT 0,
            source TEXT DEFAULT 'ha_live'
        );
        CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_video_id ON video_ratings(yt_video_id);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_channel_id ON video_ratings(yt_channel_id);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_category_id ON video_ratings(yt_category_id);
    """

    PENDING_RATINGS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS pending_ratings (
            yt_video_id TEXT PRIMARY KEY,
            rating TEXT NOT NULL,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_attempt TIMESTAMP,
            attempts INTEGER DEFAULT 0,
            last_error TEXT
        );
    """

    IMPORT_HISTORY_SCHEMA = """
        CREATE TABLE IF NOT EXISTS import_history (
            entry_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            yt_video_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_import_history_yt_video_id ON import_history(yt_video_id);
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

        self._configure()
        self._ensure_schema()
        self._normalize_existing_timestamps()

    def _configure(self) -> None:
        """Set SQLite pragmas for durability and concurrency."""
        try:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
        except sqlite3.DatabaseError as exc:
            logger.error(f"Failed to configure SQLite database: {exc}")

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            try:
                with self._conn:
                    self._conn.executescript(self.VIDEO_RATINGS_SCHEMA)
                    self._conn.executescript(self.PENDING_RATINGS_SCHEMA)
                    self._conn.executescript(self.IMPORT_HISTORY_SCHEMA)
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to initialize SQLite schema: {exc}")
                raise

    def _table_info(self, table: str) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(f"PRAGMA table_info({table});")
        return [dict(row) for row in cursor.fetchall()]

    def _table_columns(self, table: str) -> List[str]:
        return [row['name'] for row in self._table_info(table)]

    def _normalize_existing_timestamps(self) -> None:
        """Convert legacy ISO8601 timestamps with 'T' separator to sqlite friendly format."""
        columns = ('date_added', 'date_last_played')
        updates = []
        with self._lock:
            try:
                with self._conn:
                    for column in columns:
                        cursor = self._conn.execute(
                            f"""
                            UPDATE video_ratings
                            SET {column} = REPLACE({column}, 'T', ' ')
                            WHERE {column} LIKE '%T%';
                            """
                        )
                        if cursor.rowcount:
                            updates.append((column, cursor.rowcount))
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to normalize timestamp format: {exc}")
                return

        for column, count in updates:
            logger.info("Normalized %s timestamp values (%s rows)", column, count)

    @staticmethod
    def timestamp(ts: str = None) -> str:
        """
        Return timestamps in a format compatible with sqlite's built-in converters.
        sqlite3 expects 'YYYY-MM-DD HH:MM:SS' (space separator) for TIMESTAMP columns.
        Returns None if ts is None (for optional timestamp fields).
        """
        if ts is None:
            return None
        if ts:
            cleaned = ts.replace('T', ' ').replace('Z', '').strip()
            if cleaned:
                return cleaned[:19]  # Truncate to 'YYYY-MM-DD HH:MM:SS'
        return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    @property
    def connection(self):
        """Get the database connection."""
        return self._conn

    @property
    def lock(self):
        """Get the thread lock."""
        return self._lock