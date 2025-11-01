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

    # v1.64.0: Removed NOT_FOUND_SEARCHES_SCHEMA - now using video_ratings table

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
                    # Create all tables
                    self._conn.executescript(self.VIDEO_RATINGS_SCHEMA)
                    self._conn.executescript(self.IMPORT_HISTORY_SCHEMA)
                    # v1.64.0: Removed not_found_searches table - now using video_ratings

                    # v1.64.6: Migrate video_ratings table to remove NOT NULL from yt_video_id
                    self._migrate_video_ratings_nullable_id()

                    # v1.64.6: Clean up old ha_hash entries in yt_video_id column
                    self._migrate_ha_hash_entries()

                    # Migrate api_usage table if needed
                    self._migrate_api_usage_table()

                    # v1.64.3: Drop deprecated not_found_searches table if it exists
                    self._drop_not_found_searches_table()

                    self._conn.executescript(self.API_USAGE_SCHEMA)
                    self._conn.executescript(self.STATS_CACHE_SCHEMA)

                    # Ensure all required columns exist (handles both new and existing DBs)
                    self._add_column_if_missing('video_ratings', 'ha_content_hash', 'TEXT')
                    self._add_column_if_missing('video_ratings', 'pending_reason', 'TEXT')
                    self._add_column_if_missing('video_ratings', 'ha_app_name', 'TEXT')
                    self._add_column_if_missing('video_ratings', 'source', 'TEXT')
                    self._add_column_if_missing('video_ratings', 'ha_content_id', 'TEXT')

                    # Ensure matching status columns exist
                    self._add_column_if_missing('video_ratings', 'yt_match_pending', 'INTEGER')
                    self._add_column_if_missing('video_ratings', 'yt_match_requested_at', 'TIMESTAMP')
                    self._add_column_if_missing('video_ratings', 'yt_match_attempts', 'INTEGER')
                    self._add_column_if_missing('video_ratings', 'yt_match_last_attempt', 'TIMESTAMP')
                    self._add_column_if_missing('video_ratings', 'yt_match_last_error', 'TEXT')

                    # Ensure rating queue columns exist
                    self._add_column_if_missing('video_ratings', 'rating_queue_pending', 'TEXT')
                    self._add_column_if_missing('video_ratings', 'rating_queue_requested_at', 'TIMESTAMP')
                    self._add_column_if_missing('video_ratings', 'rating_queue_attempts', 'INTEGER')
                    self._add_column_if_missing('video_ratings', 'rating_queue_last_attempt', 'TIMESTAMP')
                    self._add_column_if_missing('video_ratings', 'rating_queue_last_error', 'TEXT')

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

    def _migrate_api_usage_table(self) -> None:
        """
        Migrate api_usage table from old schema to new hourly schema.
        Old schema: timestamp, date, api_method, success, quota_cost, error_message
        New schema: date, hour_00 through hour_23
        """
        try:
            # Check if api_usage table exists and has old schema
            cursor = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='api_usage'"
            )
            if not cursor.fetchone():
                # Table doesn't exist yet, nothing to migrate
                return

            # Check if table has old schema (has 'timestamp' column)
            cursor = self._conn.execute("PRAGMA table_info(api_usage)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'timestamp' not in columns:
                # Already using new schema or empty table
                return

            logger.info("Migrating api_usage table to new hourly schema")

            # Start transaction for migration
            self._conn.execute("BEGIN TRANSACTION")

            try:
                # Create temporary table with aggregated hourly data
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_usage_new (
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
                    )
                """)

                # Migrate data: aggregate by date and hour using a single query per date
                # Get all distinct dates
                cursor = self._conn.execute("SELECT DISTINCT date FROM api_usage ORDER BY date")
                dates = [row[0] for row in cursor.fetchall()]

                for date in dates:
                    # Use aggregated query to get all hourly counts at once
                    cursor = self._conn.execute(
                        """
                        SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
                        FROM api_usage
                        WHERE date = ?
                        GROUP BY hour
                        """,
                        (date,)
                    )

                    # Build hourly counts dictionary from query results
                    hourly_counts = {f"hour_{int(row[0]):02d}": row[1] for row in cursor.fetchall()}

                    # Fill in zeros for missing hours
                    for h in range(24):
                        if f"hour_{h:02d}" not in hourly_counts:
                            hourly_counts[f"hour_{h:02d}"] = 0

                    # Insert aggregated data into new table
                    columns_str = "date, " + ", ".join([f"hour_{h:02d}" for h in range(24)])
                    values_str = "?, " + ", ".join(["?" for _ in range(24)])
                    values = [date] + [hourly_counts[f"hour_{h:02d}"] for h in range(24)]

                    self._conn.execute(
                        f"INSERT INTO api_usage_new ({columns_str}) VALUES ({values_str})",
                        values
                    )

                # Drop old table and rename new one
                self._conn.execute("DROP TABLE api_usage")
                self._conn.execute("ALTER TABLE api_usage_new RENAME TO api_usage")

                # Commit the transaction
                self._conn.execute("COMMIT")

                logger.info(f"Successfully migrated {len(dates)} days of API usage data to hourly schema")

            except Exception as exc:
                # Rollback on any error
                self._conn.execute("ROLLBACK")
                logger.error(f"Failed to migrate api_usage table: {exc}")
                # Clean up temporary table
                try:
                    self._conn.execute("DROP TABLE IF EXISTS api_usage_new")
                except sqlite3.DatabaseError:
                    # Ignore errors during cleanup; table may not exist
                    pass
                raise

        except sqlite3.DatabaseError as exc:
            logger.error(f"Failed to migrate api_usage table: {exc}")
            raise

    def _migrate_video_ratings_nullable_id(self) -> None:
        """
        Migrate video_ratings table to allow NULL in yt_video_id column.
        Older schemas had NOT NULL constraint which prevents pending videos.
        """
        try:
            # Check if video_ratings table exists
            cursor = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='video_ratings'"
            )
            if not cursor.fetchone():
                # Table doesn't exist yet, will be created with correct schema
                return

            # Check if yt_video_id has NOT NULL constraint
            cursor = self._conn.execute("PRAGMA table_info(video_ratings)")
            columns = {row[1]: row for row in cursor.fetchall()}

            # Column info format: (cid, name, type, notnull, dflt_value, pk)
            if 'yt_video_id' not in columns:
                # Column doesn't exist, nothing to migrate
                return

            yt_video_id_notnull = columns['yt_video_id'][3]  # notnull flag
            if yt_video_id_notnull == 0:
                # Already nullable, nothing to do
                return

            logger.info("Migrating video_ratings table to allow NULL in yt_video_id column")

            # Begin transaction for migration
            self._conn.execute("BEGIN TRANSACTION")

            try:
                # Create new table with correct schema (without NOT NULL on yt_video_id)
                self._conn.executescript("""
                    CREATE TABLE video_ratings_new (
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
                """)

                # Copy all data from old table to new table
                # Handle NULL ha_title by setting default value
                self._conn.execute("""
                    INSERT INTO video_ratings_new
                    SELECT
                        id,
                        yt_video_id,
                        ha_content_id,
                        COALESCE(ha_title, 'Unknown Title') as ha_title,
                        ha_artist,
                        ha_app_name,
                        yt_title,
                        yt_channel,
                        yt_channel_id,
                        yt_description,
                        yt_published_at,
                        yt_category_id,
                        yt_live_broadcast,
                        yt_location,
                        yt_recording_date,
                        ha_duration,
                        yt_duration,
                        yt_url,
                        rating,
                        ha_content_hash,
                        date_added,
                        date_last_played,
                        play_count,
                        rating_score,
                        pending_reason,
                        source,
                        yt_match_pending,
                        yt_match_requested_at,
                        yt_match_attempts,
                        yt_match_last_attempt,
                        yt_match_last_error,
                        rating_queue_pending,
                        rating_queue_requested_at,
                        rating_queue_attempts,
                        rating_queue_last_attempt,
                        rating_queue_last_error
                    FROM video_ratings
                """)

                # Drop old table
                self._conn.execute("DROP TABLE video_ratings")

                # Rename new table to original name
                self._conn.execute("ALTER TABLE video_ratings_new RENAME TO video_ratings")

                # Recreate indexes
                self._conn.executescript("""
                    CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_video_id ON video_ratings(yt_video_id);
                    CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title);
                    CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_channel_id ON video_ratings(yt_channel_id);
                    CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_category_id ON video_ratings(yt_category_id);
                    CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_hash ON video_ratings(ha_content_hash);
                    CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_id ON video_ratings(ha_content_id);
                """)

                # Commit the transaction
                self._conn.execute("COMMIT")

                logger.info("Successfully migrated video_ratings table to allow NULL in yt_video_id")

            except Exception as exc:
                # Rollback on any error
                self._conn.execute("ROLLBACK")
                logger.error(f"Failed to migrate video_ratings table: {exc}")
                # Clean up temporary table
                try:
                    self._conn.execute("DROP TABLE IF EXISTS video_ratings_new")
                except sqlite3.DatabaseError:
                    pass
                raise

        except sqlite3.DatabaseError as exc:
            logger.error(f"Failed to check/migrate video_ratings table: {exc}")
            raise

    def _migrate_ha_hash_entries(self) -> None:
        """
        Migrate old pending videos that have ha_hash: IDs in yt_video_id column.
        These should be moved to ha_content_id column with yt_video_id set to NULL.
        """
        try:
            # Check if video_ratings table exists
            cursor = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='video_ratings'"
            )
            if not cursor.fetchone():
                return

            # Find all rows with ha_hash: in yt_video_id
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT COUNT(*) FROM video_ratings WHERE yt_video_id LIKE 'ha_hash:%'"
                )
                count = cursor.fetchone()[0]

                if count == 0:
                    # No old entries to migrate
                    return

                logger.info(f"Migrating {count} old ha_hash entries from yt_video_id to ha_content_id")

                with self._conn:
                    # Move ha_hash IDs from yt_video_id to ha_content_id, set yt_video_id to NULL
                    self._conn.execute("""
                        UPDATE video_ratings
                        SET ha_content_id = yt_video_id,
                            yt_video_id = NULL,
                            yt_match_pending = 1
                        WHERE yt_video_id LIKE 'ha_hash:%'
                    """)

                logger.info(f"Successfully migrated {count} ha_hash entries")

        except sqlite3.DatabaseError as exc:
            logger.error(f"Failed to migrate ha_hash entries: {exc}")
            # Don't raise - this is a non-critical cleanup operation

    def _drop_not_found_searches_table(self) -> None:
        """
        Drop the deprecated not_found_searches table if it exists.
        v1.64.0: This functionality has been consolidated into video_ratings table
        using pending_reason='not_found' column.
        """
        try:
            # Check if not_found_searches table exists
            cursor = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='not_found_searches'"
            )
            if not cursor.fetchone():
                # Table doesn't exist, nothing to do
                return

            logger.info("Dropping deprecated not_found_searches table (data consolidated into video_ratings)")

            # Drop the table - data should already be migrated to video_ratings
            with self._conn:
                self._conn.execute("DROP TABLE IF EXISTS not_found_searches")

            logger.info("Successfully dropped not_found_searches table")

        except sqlite3.DatabaseError as exc:
            logger.error(f"Failed to drop not_found_searches table: {exc}")
            # Don't raise - this is a non-critical cleanup operation

    def _table_info(self, table: str) -> List[Dict[str, Any]]:
        # Validate table name to prevent SQL injection
        VALID_TABLES = {'video_ratings', 'import_history', 'api_usage', 'stats_cache'}
        if table not in VALID_TABLES:
            raise ValueError(f"Invalid table name: {table}")

        cursor = self._conn.execute(f"PRAGMA table_info({table});")
        return [dict(row) for row in cursor.fetchall()]

    def _table_columns(self, table: str) -> List[str]:
        return [row['name'] for row in self._table_info(table)]

    def _add_column_if_missing(self, table: str, column: str, column_type: str) -> None:
        """Add a column to a table if it doesn't exist."""
        # Validate inputs to prevent SQL injection
        VALID_TABLES = {'video_ratings', 'import_history', 'api_usage', 'stats_cache'}
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