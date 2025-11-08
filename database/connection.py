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

from logger import logger

# v4.0.9: Suppress Python 3.12 timestamp converter deprecation warning globally
# This affects all timestamp operations, not just connection creation
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*timestamp converter.*")

DEFAULT_DB_PATH = Path(os.getenv('YTT_DB_PATH', '/config/youtube_thumbs/ratings.db'))


class DatabaseConnection:
    """Manages SQLite connection and schema."""

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
            completed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_queue_status_priority ON queue(status, priority, requested_at);
        CREATE INDEX IF NOT EXISTS idx_queue_type ON queue(type);
    """


    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
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

                    # v4.0.46: Migrate existing search_results_cache to include all video fields
                    self._migrate_search_cache_columns()

                    # v4.0.48: Cleanup orphaned video_ratings_new table from failed v4.0.47 migration
                    self._cleanup_orphaned_migration_table()

                    # v4.0.48: Remove deprecated columns from video_ratings (improved migration)
                    # TODO: REMOVE THIS CALL IN v4.0.49 (after migration completes)
                    self._remove_deprecated_video_ratings_columns()

            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to initialize SQLite schema: {exc}")
                raise

    def _migrate_search_cache_columns(self) -> None:
        """Add missing columns to search_results_cache table for existing databases."""
        try:
            # Check if yt_description column exists
            cursor = self._conn.execute("PRAGMA table_info(search_results_cache)")
            columns = {row[1] for row in cursor.fetchall()}

            # Add missing columns if they don't exist
            new_columns = {
                'yt_description': 'TEXT',
                'yt_published_at': 'TEXT',
                'yt_category_id': 'TEXT',
                'yt_live_broadcast': 'TEXT',
                'yt_location': 'TEXT',
                'yt_recording_date': 'TEXT'
            }

            for col_name, col_type in new_columns.items():
                if col_name not in columns:
                    logger.info(f"Adding column {col_name} to search_results_cache")
                    self._conn.execute(f"ALTER TABLE search_results_cache ADD COLUMN {col_name} {col_type}")

            self._conn.commit()

        except Exception as e:
            logger.warning(f"Failed to migrate search_results_cache columns: {e}")

    def _cleanup_orphaned_migration_table(self) -> None:
        """
        v4.0.48: Cleanup orphaned video_ratings_new table from failed v4.0.47 migration.
        This is a one-time cleanup, safe to remove in v4.0.49.
        """
        try:
            cursor = self._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='video_ratings_new'")
            if cursor.fetchone():
                logger.info("Cleaning up orphaned video_ratings_new table from failed migration...")
                self._conn.execute("DROP TABLE video_ratings_new")
                self._conn.commit()
                logger.info("✓ Removed orphaned video_ratings_new table")
        except Exception as e:
            logger.warning(f"Failed to cleanup orphaned table: {e}")

    def _remove_deprecated_video_ratings_columns(self) -> None:
        """
        v4.0.48: Remove 11 deprecated queue-tracking columns from video_ratings.
        Improved version with better error handling and transaction management.

        TODO: REMOVE THIS METHOD IN v4.0.49 (after user has migrated)

        Deprecated columns to remove:
        - yt_match_pending, yt_match_requested_at, yt_match_attempts,
          yt_match_last_attempt, yt_match_last_error, pending_reason
        - rating_queue_pending, rating_queue_requested_at, rating_queue_attempts,
          rating_queue_last_attempt, rating_queue_last_error
        """
        try:
            # Check if deprecated columns exist
            cursor = self._conn.execute("PRAGMA table_info(video_ratings)")
            columns = {row[1] for row in cursor.fetchall()}

            deprecated_columns = {
                'yt_match_pending', 'yt_match_requested_at', 'yt_match_attempts',
                'yt_match_last_attempt', 'yt_match_last_error', 'pending_reason',
                'rating_queue_pending', 'rating_queue_requested_at', 'rating_queue_attempts',
                'rating_queue_last_attempt', 'rating_queue_last_error'
            }

            # If no deprecated columns exist, migration already completed
            if not any(col in columns for col in deprecated_columns):
                logger.debug("Deprecated columns already removed from video_ratings")
                return

            logger.info("Removing 11 deprecated columns from video_ratings table...")

            # Use explicit transaction for safety
            self._conn.execute("BEGIN TRANSACTION")

            try:
                # Create new table with clean schema
                self._conn.execute("""
                    CREATE TABLE video_ratings_new (
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
                    )
                """)

                # Copy all data from old table to new table
                self._conn.execute("""
                    INSERT INTO video_ratings_new (
                        id, yt_video_id, ha_content_id, ha_title, ha_artist, ha_app_name,
                        yt_title, yt_channel, yt_channel_id, yt_description, yt_published_at,
                        yt_category_id, yt_live_broadcast, yt_location, yt_recording_date,
                        ha_duration, yt_duration, yt_url, rating, ha_content_hash,
                        date_added, date_last_played, play_count, rating_score, source
                    )
                    SELECT
                        id, yt_video_id, ha_content_id, ha_title, ha_artist, ha_app_name,
                        yt_title, yt_channel, yt_channel_id, yt_description, yt_published_at,
                        yt_category_id, yt_live_broadcast, yt_location, yt_recording_date,
                        ha_duration, yt_duration, yt_url, rating, ha_content_hash,
                        date_added, date_last_played, play_count, rating_score, source
                    FROM video_ratings
                """)

                # Verify row counts match
                cursor = self._conn.execute("SELECT COUNT(*) FROM video_ratings")
                old_count = cursor.fetchone()[0]
                cursor = self._conn.execute("SELECT COUNT(*) FROM video_ratings_new")
                new_count = cursor.fetchone()[0]

                if old_count != new_count:
                    raise Exception(f"Row count mismatch: old={old_count}, new={new_count}")

                # Drop old table
                self._conn.execute("DROP TABLE video_ratings")

                # Rename new table
                self._conn.execute("ALTER TABLE video_ratings_new RENAME TO video_ratings")

                # Recreate indexes
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_video_id ON video_ratings(yt_video_id)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_channel_id ON video_ratings(yt_channel_id)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_category_id ON video_ratings(yt_category_id)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_hash ON video_ratings(ha_content_hash)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_id ON video_ratings(ha_content_id)")

                # Commit transaction
                self._conn.execute("COMMIT")
                logger.info(f"✓ Successfully removed 11 deprecated columns from video_ratings ({old_count} rows preserved)")

            except Exception as e:
                # Rollback on any error
                self._conn.execute("ROLLBACK")
                raise Exception(f"Migration failed, rolled back: {e}")

        except Exception as e:
            logger.error(f"Failed to remove deprecated video_ratings columns: {e}")
            logger.warning("Database unchanged - will retry on next restart")
            # Clean up orphaned table if it exists
            try:
                self._conn.execute("DROP TABLE IF EXISTS video_ratings_new")
                self._conn.commit()
            except:
                pass

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