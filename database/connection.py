"""
Database connection and schema management.
"""
import os
import re
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
            yt_video_id TEXT UNIQUE,
            ha_content_id TEXT,
            ha_title TEXT NOT NULL,
            ha_artist TEXT,
            ha_app_name TEXT,
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
            ha_content_hash TEXT,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_last_played TIMESTAMP,
            play_count INTEGER DEFAULT 1,
            rating_score INTEGER DEFAULT 0,
            pending_reason TEXT,
            source TEXT DEFAULT 'ha_live',
            yt_match_pending INTEGER DEFAULT 1,
            yt_match_requested_at TIMESTAMP,
            yt_match_attempts INTEGER DEFAULT 0,
            yt_match_last_attempt TIMESTAMP,
            yt_match_last_error TEXT,
            rating_queue_pending TEXT,
            rating_queue_requested_at TIMESTAMP,
            rating_queue_attempts INTEGER DEFAULT 0,
            rating_queue_last_attempt TIMESTAMP,
            rating_queue_last_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_video_id ON video_ratings(yt_video_id);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_channel_id ON video_ratings(yt_channel_id);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_category_id ON video_ratings(yt_category_id);
    """

    API_USAGE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS api_usage (
            date TEXT PRIMARY KEY,
            hour_00 INTEGER DEFAULT 0,
            hour_01 INTEGER DEFAULT 0,
            hour_02 INTEGER DEFAULT 0,
            hour_03 INTEGER DEFAULT 0,
            hour_04 INTEGER DEFAULT 0,
            hour_05 INTEGER DEFAULT 0,
            hour_06 INTEGER DEFAULT 0,
            hour_07 INTEGER DEFAULT 0,
            hour_08 INTEGER DEFAULT 0,
            hour_09 INTEGER DEFAULT 0,
            hour_10 INTEGER DEFAULT 0,
            hour_11 INTEGER DEFAULT 0,
            hour_12 INTEGER DEFAULT 0,
            hour_13 INTEGER DEFAULT 0,
            hour_14 INTEGER DEFAULT 0,
            hour_15 INTEGER DEFAULT 0,
            hour_16 INTEGER DEFAULT 0,
            hour_17 INTEGER DEFAULT 0,
            hour_18 INTEGER DEFAULT 0,
            hour_19 INTEGER DEFAULT 0,
            hour_20 INTEGER DEFAULT 0,
            hour_21 INTEGER DEFAULT 0,
            hour_22 INTEGER DEFAULT 0,
            hour_23 INTEGER DEFAULT 0
        );
    """

    API_CALL_LOG_SCHEMA = """
        CREATE TABLE IF NOT EXISTS api_call_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            api_method TEXT NOT NULL,
            operation_type TEXT,
            query_params TEXT,
            quota_cost INTEGER DEFAULT 1,
            success BOOLEAN DEFAULT 1,
            error_message TEXT,
            results_count INTEGER,
            context TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_api_call_log_timestamp ON api_call_log(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_api_call_log_method ON api_call_log(api_method);
        CREATE INDEX IF NOT EXISTS idx_api_call_log_success ON api_call_log(success);
    """

    STATS_CACHE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS stats_cache (
            cache_key TEXT PRIMARY KEY,
            cache_data TEXT NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_stats_cache_expires ON stats_cache(expires_at);
    """

    SEARCH_RESULTS_CACHE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS search_results_cache (
            yt_video_id TEXT PRIMARY KEY,
            yt_title TEXT NOT NULL,
            yt_channel TEXT,
            yt_channel_id TEXT,
            yt_duration INTEGER,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_search_cache_duration ON search_results_cache(yt_duration);
        CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_results_cache(expires_at);
        CREATE INDEX IF NOT EXISTS idx_search_cache_title ON search_results_cache(yt_title);
    """

    SEARCH_QUEUE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS search_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ha_title TEXT NOT NULL,
            ha_artist TEXT,
            ha_album TEXT,
            ha_content_id TEXT,
            ha_duration INTEGER,
            ha_app_name TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            attempts INTEGER DEFAULT 0,
            last_attempt TIMESTAMP,
            last_error TEXT,
            found_video_id TEXT,
            callback_rating TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_search_queue_status ON search_queue(status, requested_at);
        CREATE INDEX IF NOT EXISTS idx_search_queue_content_id ON search_queue(ha_content_id);
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

    def _configure(self) -> None:
        """Set SQLite pragmas for durability and concurrency."""
        # SECURITY: Use lock for all database operations to prevent race conditions
        with self._lock:
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
                    # Create all tables
                    self._conn.executescript(self.VIDEO_RATINGS_SCHEMA)
                    self._conn.executescript(self.API_USAGE_SCHEMA)
                    self._conn.executescript(self.API_CALL_LOG_SCHEMA)
                    self._conn.executescript(self.STATS_CACHE_SCHEMA)
                    self._conn.executescript(self.SEARCH_RESULTS_CACHE_SCHEMA)
                    self._conn.executescript(self.SEARCH_QUEUE_SCHEMA)

                    # Create indexes
                    self._conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_hash ON video_ratings(ha_content_hash)"
                    )
                    self._conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_id ON video_ratings(ha_content_id)"
                    )

            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to initialize SQLite schema: {exc}")
                raise

    @staticmethod
    def timestamp(ts = None) -> str:
        """
        Return timestamps in a format compatible with sqlite's built-in converters.
        sqlite3 expects 'YYYY-MM-DD HH:MM:SS' (space separator) for TIMESTAMP columns.
        All timestamps are stored in UTC for consistency and compatibility.
        Returns None if ts is None (for optional timestamp fields).

        Args:
            ts: Can be None, a string (ISO8601 or sqlite format), or a datetime object
        """
        if ts is None:
            return None

        # If it's a datetime object, convert to string format
        if isinstance(ts, datetime):
            return ts.strftime('%Y-%m-%d %H:%M:%S')

        # Handle string input
        if ts:
            cleaned = ts.replace('T', ' ').replace('Z', '').strip()
            if cleaned:
                # Validate format matches YYYY-MM-DD HH:MM:SS
                if not re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', cleaned[:19]):
                    logger.warning("Invalid timestamp format: %s", cleaned[:19])
                    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                return cleaned[:19]
        return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    @property
    def connection(self):
        """Get the database connection."""
        return self._conn

    @property
    def lock(self):
        """Get the thread lock."""
        return self._lock