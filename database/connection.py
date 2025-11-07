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
            completed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_queue_status_priority ON queue(status, priority, requested_at);
        CREATE INDEX IF NOT EXISTS idx_queue_type ON queue(type);
    """

    # Legacy table schemas - kept for migration purposes, will be removed in future version
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
                    self._conn.executescript(self.UNIFIED_QUEUE_SCHEMA)
                    self._conn.executescript(self.SEARCH_QUEUE_SCHEMA)  # Legacy - for migration

                    # Create indexes
                    self._conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_hash ON video_ratings(ha_content_hash)"
                    )
                    self._conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_id ON video_ratings(ha_content_id)"
                    )

                    # Run migration to unified queue if needed
                    self._migrate_to_unified_queue()

            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to initialize SQLite schema: {exc}")
                raise

    def _migrate_to_unified_queue(self) -> None:
        """
        Migrate data from legacy queue tables to unified queue table.
        This is a one-time migration that moves:
        1. search_queue entries -> queue table with type='search'
        2. video_ratings entries with rating_queue_pending -> queue table with type='rating'
        """
        import json

        try:
            # Check if migration has already been done by looking for a migration marker
            cursor = self._conn.execute(
                "SELECT COUNT(*) as count FROM queue"
            )
            queue_count = cursor.fetchone()['count']

            # Only migrate if queue is empty (first run or clean database)
            if queue_count > 0:
                logger.debug("Unified queue already has data, skipping migration")
                return

            # Migrate search_queue to unified queue
            cursor = self._conn.execute(
                "SELECT COUNT(*) as count FROM search_queue WHERE status = 'pending'"
            )
            search_count = cursor.fetchone()['count']

            if search_count > 0:
                logger.info(f"Migrating {search_count} search queue entries to unified queue...")
                cursor = self._conn.execute(
                    """
                    SELECT * FROM search_queue WHERE status = 'pending'
                    ORDER BY requested_at ASC
                    """
                )
                for row in cursor.fetchall():
                    search_data = dict(row)
                    payload = {
                        'ha_title': search_data['ha_title'],
                        'ha_artist': search_data['ha_artist'],
                        'ha_album': search_data['ha_album'],
                        'ha_content_id': search_data['ha_content_id'],
                        'ha_duration': search_data['ha_duration'],
                        'ha_app_name': search_data['ha_app_name'],
                        'callback_rating': search_data.get('callback_rating')
                    }
                    self._conn.execute(
                        """
                        INSERT INTO queue (type, priority, status, payload, requested_at, attempts, last_attempt, last_error)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ('search', 2, 'pending', json.dumps(payload),
                         search_data['requested_at'], search_data['attempts'],
                         search_data['last_attempt'], search_data['last_error'])
                    )
                logger.info(f"✓ Migrated {search_count} search entries")

            # Migrate rating queue from video_ratings to unified queue
            cursor = self._conn.execute(
                "SELECT COUNT(*) as count FROM video_ratings WHERE rating_queue_pending IS NOT NULL"
            )
            rating_count = cursor.fetchone()['count']

            if rating_count > 0:
                logger.info(f"Migrating {rating_count} rating queue entries to unified queue...")
                cursor = self._conn.execute(
                    """
                    SELECT yt_video_id, rating_queue_pending, rating_queue_requested_at,
                           rating_queue_attempts, rating_queue_last_attempt, rating_queue_last_error
                    FROM video_ratings
                    WHERE rating_queue_pending IS NOT NULL
                    ORDER BY rating_queue_requested_at ASC
                    """
                )
                for row in cursor.fetchall():
                    rating_data = dict(row)
                    payload = {
                        'yt_video_id': rating_data['yt_video_id'],
                        'rating': rating_data['rating_queue_pending']
                    }
                    self._conn.execute(
                        """
                        INSERT INTO queue (type, priority, status, payload, requested_at, attempts, last_attempt, last_error)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        ('rating', 1, 'pending', json.dumps(payload),
                         rating_data['rating_queue_requested_at'], rating_data['rating_queue_attempts'],
                         rating_data['rating_queue_last_attempt'], rating_data['rating_queue_last_error'])
                    )
                logger.info(f"✓ Migrated {rating_count} rating entries")

            self._conn.commit()

            if search_count > 0 or rating_count > 0:
                logger.info(f"Migration complete: {search_count} searches + {rating_count} ratings = {search_count + rating_count} total queue items")

        except Exception as e:
            logger.error(f"Error during queue migration: {e}")
            # Don't fail startup on migration errors
            import traceback
            logger.error(traceback.format_exc())

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