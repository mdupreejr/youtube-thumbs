"""
Database connection and schema management.
"""
import os
import re
import sqlite3
import threading
import warnings
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

# v4.0.9: Suppress Python 3.12 timestamp converter deprecation warning globally
# This affects all timestamp operations, not just connection creation
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*timestamp converter.*")

DEFAULT_DB_PATH = Path(os.getenv('YTT_DB_PATH', '/config/youtube_thumbs/ratings.db'))


class DatabaseConnection:
    """Manages SQLite connection and schema."""

    # Compiled regex for timestamp validation (compile once, use many times)
    _TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')

    VIDEO_RATINGS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS video_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            yt_video_id TEXT NOT NULL UNIQUE,
            ha_content_id TEXT,
            ha_title TEXT NOT NULL,
            ha_artist TEXT,
            ha_app_name TEXT,
            yt_title TEXT NOT NULL,
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
            yt_url TEXT NOT NULL,
            rating TEXT DEFAULT 'none',
            ha_content_hash TEXT,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_last_played TIMESTAMP,
            play_count INTEGER DEFAULT 1,
            rating_score INTEGER DEFAULT 0,
            source TEXT DEFAULT 'ha_live'
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
            yt_description TEXT,
            yt_published_at TEXT,
            yt_category_id TEXT,
            yt_live_broadcast TEXT,
            yt_location TEXT,
            yt_recording_date TEXT,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_search_cache_duration ON search_results_cache(yt_duration);
        CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_results_cache(expires_at);
        CREATE INDEX IF NOT EXISTS idx_search_cache_title ON search_results_cache(yt_title);
    """

    UNIFIED_QUEUE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('search', 'rating')),
            priority INTEGER NOT NULL DEFAULT 2,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
            payload TEXT NOT NULL,
            requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            attempts INTEGER DEFAULT 0,
            last_attempt TIMESTAMP,
            last_error TEXT,
            completed_at TIMESTAMP,
            api_response_data TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_queue_status_priority ON queue(status, priority, requested_at);
        CREATE INDEX IF NOT EXISTS idx_queue_type ON queue(type);
        CREATE INDEX IF NOT EXISTS idx_queue_type_status ON queue(type, status);
        CREATE INDEX IF NOT EXISTS idx_queue_type_status_last_attempt ON queue(type, status, last_attempt DESC);
        CREATE INDEX IF NOT EXISTS idx_queue_requested_at ON queue(requested_at DESC);
    """


    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        # SECURITY: Validate and normalize the database path to prevent path injection
        # Only allow database files in specific safe directories
        allowed_base_paths = [
            Path('/config/youtube_thumbs'),
            Path('/data'),
            Path('/share/youtube_thumbs'),
        ]

        # Resolve to absolute path and normalize to prevent directory traversal
        resolved_path = Path(os.path.abspath(db_path)).resolve()

        # Check if the resolved path is within one of the allowed directories
        is_safe_path = any(
            str(resolved_path).startswith(str(base_path.resolve()))
            for base_path in allowed_base_paths
        )

        if not is_safe_path:
            logger.warning(
                f"Database path {resolved_path} is not in allowed directories. "
                f"Using default path {DEFAULT_DB_PATH}"
            )
            resolved_path = DEFAULT_DB_PATH.resolve()

        self.db_path = resolved_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # v4.0.9: Timestamp warnings now suppressed globally at module level (line 17)
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
                    self._conn.executescript(self.UNIFIED_QUEUE_SCHEMA)

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
            cleaned = ts.replace('T', ' ').replace('Z', '').strip()[:19]
            if cleaned and DatabaseConnection._TIMESTAMP_PATTERN.match(cleaned):
                return cleaned
            if cleaned:  # Only log if we had a string but it was invalid
                logger.warning("Invalid timestamp format: %s", cleaned)
        return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    @property
    def connection(self):
        """Get the database connection."""
        return self._conn

    @property
    def lock(self):
        """Get the thread lock."""
        return self._lock