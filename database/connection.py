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

    # v1.58.0: Separated matching status from rating queue
    # YouTube matching status tracked in: yt_match_* columns
    # - yt_match_pending (1=pending match, 0=matched)
    # - yt_match_requested_at, yt_match_attempts, yt_match_last_attempt, yt_match_last_error
    # Rating queue (for quota blocking) tracked in: rating_queue_* columns
    # - rating_queue_pending (TEXT: 'like'/'dislike' or NULL)
    # - rating_queue_requested_at, rating_queue_attempts, rating_queue_last_attempt, rating_queue_last_error
    # Removed redundant pending_match column

    IMPORT_HISTORY_SCHEMA = """
        CREATE TABLE IF NOT EXISTS import_history (
            entry_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            yt_video_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_import_history_yt_video_id ON import_history(yt_video_id);
    """

    NOT_FOUND_SEARCHES_SCHEMA = """
        CREATE TABLE IF NOT EXISTS not_found_searches (
            search_hash TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            artist TEXT,
            duration INTEGER,
            search_query TEXT,
            last_attempted TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            attempt_count INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_not_found_searches_last_attempted ON not_found_searches(last_attempted);
    """

    API_USAGE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date TEXT NOT NULL,
            api_method TEXT NOT NULL,
            success INTEGER DEFAULT 1,
            quota_cost INTEGER DEFAULT 1,
            error_message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_api_usage_date ON api_usage(date);
        CREATE INDEX IF NOT EXISTS idx_api_usage_timestamp ON api_usage(timestamp);
        CREATE INDEX IF NOT EXISTS idx_api_usage_method ON api_usage(api_method);
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
                    # PENDING_RATINGS_SCHEMA removed in v1.50.0 - now using video_ratings columns
                    self._conn.executescript(self.IMPORT_HISTORY_SCHEMA)
                    self._conn.executescript(self.NOT_FOUND_SEARCHES_SCHEMA)
                    self._conn.executescript(self.API_USAGE_SCHEMA)
                    self._conn.executescript(self.STATS_CACHE_SCHEMA)

                    # Add ha_content_hash column if missing (for existing databases)
                    self._add_column_if_missing('video_ratings', 'ha_content_hash', 'TEXT')
                    # Create index for ha_content_hash after column is added
                    self._conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_hash ON video_ratings(ha_content_hash)"
                    )

                    # Add pending_reason column if missing (for existing databases)
                    self._add_column_if_missing('video_ratings', 'pending_reason', 'TEXT')

                    # Migrate ha_channel to ha_artist (for existing databases)
                    columns = self._table_columns('video_ratings')
                    if 'ha_channel' in columns and 'ha_artist' not in columns:
                        logger.info("Migrating ha_channel column to ha_artist")
                        # SQLite doesn't support RENAME COLUMN directly in all versions
                        # Add new column, copy data, drop old column
                        self._conn.execute("ALTER TABLE video_ratings ADD COLUMN ha_artist TEXT")
                        self._conn.execute("UPDATE video_ratings SET ha_artist = ha_channel")
                        # Note: Cannot drop column in SQLite easily, so we leave ha_channel empty
                        # New inserts will only use ha_artist

                    # Add ha_app_name column if missing (for existing databases)
                    self._add_column_if_missing('video_ratings', 'ha_app_name', 'TEXT')

                    # v1.50.0 Migration: Consolidate pending_ratings into video_ratings
                    self._migrate_to_unified_schema()

                    # v1.58.0 Migration: Rename yt_rating_* to yt_match_* and remove pending_match
                    self._migrate_to_match_columns()

                    # v1.58.1 Migration: Fix NULL yt_match_pending values
                    self._fix_match_pending_nulls()
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to initialize SQLite schema: {exc}")
                raise

    def _table_info(self, table: str) -> List[Dict[str, Any]]:
        # Validate table name to prevent SQL injection
        VALID_TABLES = {'video_ratings', 'import_history', 'not_found_searches', 'api_usage', 'stats_cache'}
        if table not in VALID_TABLES:
            raise ValueError(f"Invalid table name: {table}")

        cursor = self._conn.execute(f"PRAGMA table_info({table});")
        return [dict(row) for row in cursor.fetchall()]

    def _table_columns(self, table: str) -> List[str]:
        return [row['name'] for row in self._table_info(table)]

    def _add_column_if_missing(self, table: str, column: str, column_type: str) -> None:
        """Add a column to a table if it doesn't exist."""
        # Validate inputs to prevent SQL injection
        VALID_TABLES = {'video_ratings', 'import_history', 'not_found_searches', 'api_usage', 'stats_cache'}
        VALID_COLUMN_TYPES = {'TEXT', 'INTEGER', 'TIMESTAMP', 'REAL'}

        if table not in VALID_TABLES:
            raise ValueError(f"Invalid table name: {table}")
        if column_type.upper() not in VALID_COLUMN_TYPES:
            raise ValueError(f"Invalid column type: {column_type}")
        if not column.replace('_', '').isalnum():
            raise ValueError(f"Invalid column name: {column}")

        columns = self._table_columns(table)
        if column not in columns:
            logger.info(f"Adding missing column {column} to {table} table")
            with self._conn:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _column_allows_null(self, table: str, column: str) -> bool:
        """Check if a column allows NULL values by examining table schema."""
        table_info = self._table_info(table)
        for col_info in table_info:
            if col_info['name'] == column:
                # notnull is 0 if NULL allowed, 1 if NOT NULL
                return col_info['notnull'] == 0
        return True  # If column not found, assume it allows NULL

    def _migrate_to_unified_schema(self) -> None:
        """
        v1.50.0 Migration: Consolidate database schema
        1. Add ha_content_id column for pending video placeholders
        2. Add yt_rating_pending columns for rating queue with retry logic
        3. Migrate ha_hash:* IDs to ha_content_id and set yt_video_id to NULL
        4. Migrate pending_ratings table data to video_ratings columns
        5. Drop pending_ratings table
        """
        columns = self._table_columns('video_ratings')

        # Check if migration already completed
        if 'ha_content_id' in columns and 'yt_rating_pending' in columns:
            # Check if pending_ratings table still exists
            try:
                self._conn.execute("SELECT 1 FROM pending_ratings LIMIT 1")
                # Table exists, need to complete migration
                logger.info("Completing v1.50.0 migration (pending_ratings table cleanup)")
            except sqlite3.OperationalError:
                # Table doesn't exist, migration already done
                return

        logger.info("Starting v1.50.0 database schema migration")

        with self._conn:
            # Step 1: Add new columns to video_ratings
            self._add_column_if_missing('video_ratings', 'ha_content_id', 'TEXT')
            self._add_column_if_missing('video_ratings', 'yt_rating_pending', 'TEXT')
            self._add_column_if_missing('video_ratings', 'yt_rating_requested_at', 'TIMESTAMP')
            self._add_column_if_missing('video_ratings', 'yt_rating_attempts', 'INTEGER')
            self._add_column_if_missing('video_ratings', 'yt_rating_last_attempt', 'TIMESTAMP')
            self._add_column_if_missing('video_ratings', 'yt_rating_last_error', 'TEXT')

            # Step 2: Migrate ha_hash:* IDs to ha_content_id
            # Check if there are any ha_hash entries and if yt_video_id allows NULL
            cursor = self._conn.execute("SELECT COUNT(*) FROM video_ratings WHERE yt_video_id LIKE 'ha_hash:%'")
            ha_hash_count = cursor.fetchone()[0]

            if ha_hash_count > 0:
                logger.info(f"Found {ha_hash_count} ha_hash entries to migrate")

                # Check if yt_video_id allows NULL
                if self._column_allows_null('video_ratings', 'yt_video_id'):
                    # Column allows NULL, safe to migrate
                    cursor = self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET ha_content_id = yt_video_id,
                            yt_video_id = NULL
                        WHERE yt_video_id LIKE 'ha_hash:%'
                        """
                    )
                    logger.info(f"Migrated {cursor.rowcount} ha_hash IDs to ha_content_id column")
                else:
                    # Column has NOT NULL constraint - copy to ha_content_id but keep in yt_video_id
                    logger.warning("yt_video_id has NOT NULL constraint - copying ha_hash values to ha_content_id without removing from yt_video_id")
                    cursor = self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET ha_content_id = yt_video_id
                        WHERE yt_video_id LIKE 'ha_hash:%'
                        """
                    )
                    logger.info(f"Copied {cursor.rowcount} ha_hash IDs to ha_content_id column (kept in yt_video_id due to NOT NULL constraint)")
                    logger.warning("NOTE: ha_hash values remain in yt_video_id column - upgrade database schema to allow NULL if full migration is needed")

            # Step 3: Migrate pending_ratings data to video_ratings
            try:
                # Check if pending_ratings table exists
                cursor = self._conn.execute("SELECT COUNT(*) FROM pending_ratings")
                pending_count = cursor.fetchone()[0]

                if pending_count > 0:
                    logger.info(f"Migrating {pending_count} pending ratings to video_ratings")

                    # Migrate data
                    self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET yt_rating_pending = (
                                SELECT rating FROM pending_ratings
                                WHERE pending_ratings.yt_video_id = video_ratings.yt_video_id
                            ),
                            yt_rating_requested_at = (
                                SELECT requested_at FROM pending_ratings
                                WHERE pending_ratings.yt_video_id = video_ratings.yt_video_id
                            ),
                            yt_rating_attempts = (
                                SELECT attempts FROM pending_ratings
                                WHERE pending_ratings.yt_video_id = video_ratings.yt_video_id
                            ),
                            yt_rating_last_attempt = (
                                SELECT last_attempt FROM pending_ratings
                                WHERE pending_ratings.yt_video_id = video_ratings.yt_video_id
                            ),
                            yt_rating_last_error = (
                                SELECT last_error FROM pending_ratings
                                WHERE pending_ratings.yt_video_id = video_ratings.yt_video_id
                            )
                        WHERE yt_video_id IN (SELECT yt_video_id FROM pending_ratings)
                        """
                    )
                    logger.info("Successfully migrated pending ratings data")

                # Step 4: Drop pending_ratings table
                self._conn.execute("DROP TABLE IF EXISTS pending_ratings")
                logger.info("Dropped pending_ratings table")

            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    logger.info("pending_ratings table already dropped, skipping migration step")
                else:
                    raise

            # Step 5: Create index for ha_content_id (v1.50.0 column)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_id ON video_ratings(ha_content_id)"
            )
            logger.info("Created index on ha_content_id column")

        logger.info("Completed v1.50.0 database schema migration")

    def _migrate_to_match_columns(self) -> None:
        """
        v1.58.0 Migration: Separate matching status from rating queue
        1. Create yt_match_* columns for YouTube matching status
        2. Create rating_queue_* columns for like/dislike queue
        3. Migrate pending_match → yt_match_pending (0=matched, 1=pending)
        4. Migrate yt_rating_* → rating_queue_* (rating queue data)
        5. Leave old columns for backwards compatibility
        """
        columns = self._table_columns('video_ratings')

        # Check if migration already completed
        if 'yt_match_pending' in columns and 'rating_queue_pending' in columns:
            return

        logger.info("Starting v1.58.0 database schema migration (separate matching from rating queue)")

        with self._conn:
            # Add new match status columns
            self._add_column_if_missing('video_ratings', 'yt_match_pending', 'INTEGER')
            self._add_column_if_missing('video_ratings', 'yt_match_requested_at', 'TIMESTAMP')
            self._add_column_if_missing('video_ratings', 'yt_match_attempts', 'INTEGER')
            self._add_column_if_missing('video_ratings', 'yt_match_last_attempt', 'TIMESTAMP')
            self._add_column_if_missing('video_ratings', 'yt_match_last_error', 'TEXT')

            # Add new rating queue columns
            self._add_column_if_missing('video_ratings', 'rating_queue_pending', 'TEXT')
            self._add_column_if_missing('video_ratings', 'rating_queue_requested_at', 'TIMESTAMP')
            self._add_column_if_missing('video_ratings', 'rating_queue_attempts', 'INTEGER')
            self._add_column_if_missing('video_ratings', 'rating_queue_last_attempt', 'TIMESTAMP')
            self._add_column_if_missing('video_ratings', 'rating_queue_last_error', 'TEXT')

            # Migrate matching status from pending_match
            # Set yt_match_pending based on whether video has been matched to YouTube
            self._conn.execute(
                """
                UPDATE video_ratings
                SET yt_match_pending = CASE
                    WHEN yt_video_id IS NOT NULL THEN 0
                    WHEN yt_video_id IS NULL THEN 1
                    ELSE 1
                END
                WHERE yt_match_pending IS NULL
                """
            )
            logger.info("Set yt_match_pending based on yt_video_id status")

            # Migrate rating queue from yt_rating_*
            if 'yt_rating_pending' in columns:
                self._conn.execute(
                    """
                    UPDATE video_ratings
                    SET rating_queue_pending = yt_rating_pending,
                        rating_queue_requested_at = yt_rating_requested_at,
                        rating_queue_attempts = COALESCE(yt_rating_attempts, 0),
                        rating_queue_last_attempt = yt_rating_last_attempt,
                        rating_queue_last_error = yt_rating_last_error
                    WHERE rating_queue_pending IS NULL AND yt_rating_pending IS NOT NULL
                    """
                )
                logger.info("Migrated yt_rating_* → rating_queue_*")

            # Note: SQLite doesn't support DROP COLUMN easily before version 3.35.0
            # We'll leave the old columns in place but stop using them
            logger.warning("Old columns (yt_rating_*, pending_match) left in place for backwards compatibility")
            logger.warning("These columns are no longer used and can be manually dropped if needed")

        logger.info("Completed v1.58.0 database schema migration")

    def _fix_match_pending_nulls(self) -> None:
        """
        v1.58.1 Migration: Fix NULL yt_match_pending values from incomplete v1.58.0 migration.
        Sets yt_match_pending based on whether video has been matched to YouTube.
        """
        columns = self._table_columns('video_ratings')

        if 'yt_match_pending' not in columns:
            # Column doesn't exist, nothing to fix
            return

        with self._conn:
            # Check if there are NULL values that need fixing
            cursor = self._conn.execute("SELECT COUNT(*) FROM video_ratings WHERE yt_match_pending IS NULL")
            null_count = cursor.fetchone()[0]

            if null_count == 0:
                # No NULL values, migration already completed
                return

            logger.info(f"v1.58.1 Migration: Fixing {null_count} NULL yt_match_pending values")

            # Set yt_match_pending based on whether video has yt_video_id
            self._conn.execute(
                """
                UPDATE video_ratings
                SET yt_match_pending = CASE
                    WHEN yt_video_id IS NOT NULL THEN 0
                    WHEN yt_video_id IS NULL THEN 1
                    ELSE 1
                END
                WHERE yt_match_pending IS NULL
                """
            )

            logger.info("Completed v1.58.1 migration - yt_match_pending values fixed")

    def _normalize_existing_timestamps(self) -> None:
        """Convert legacy ISO8601 timestamps with 'T' separator to sqlite friendly format."""
        # Hardcoded column names - safe from SQL injection
        columns = ('date_added', 'date_last_played')
        updates = []
        with self._lock:
            try:
                with self._conn:
                    for column in columns:
                        # nosec B608 - column names are hardcoded literals, not user input
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