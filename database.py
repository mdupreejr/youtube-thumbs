import hashlib
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from logger import logger

DEFAULT_DB_PATH = Path(os.getenv('YTT_DB_PATH', '/config/youtube_thumbs/ratings.db'))


class Database:
    """Lightweight SQLite wrapper for tracking video ratings and play history."""

    VIDEO_RATINGS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS video_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE NOT NULL,
            ha_title TEXT NOT NULL,
            ha_artist TEXT,
            yt_title TEXT,
            yt_artist TEXT,
            channel TEXT,
            ha_duration INTEGER,
            yt_duration INTEGER,
            youtube_url TEXT,
            rating TEXT DEFAULT 'none',
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_updated TIMESTAMP,
            date_played TIMESTAMP,
            play_count INTEGER DEFAULT 1,
            rating_count INTEGER DEFAULT 0,
            pending_match INTEGER DEFAULT 0,
            source TEXT DEFAULT 'ha_live'
        );
        CREATE INDEX IF NOT EXISTS idx_video_ratings_video_id ON video_ratings(video_id);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title);
    """

    PENDING_RATINGS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS pending_ratings (
            video_id TEXT PRIMARY KEY,
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
            video_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_import_history_video_id ON import_history(video_id);
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
                    self._add_column_if_missing('video_ratings', 'ha_artist', 'TEXT')
                    self._add_column_if_missing('video_ratings', 'yt_artist', 'TEXT')
                    self._add_column_if_missing('video_ratings', 'pending_match', 'INTEGER DEFAULT 0')
                    self._add_column_if_missing('video_ratings', 'source', "TEXT DEFAULT 'ha_live'")
                self._rebuild_video_ratings_schema_if_needed()
                self._cleanup_pending_metadata()
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to initialize SQLite schema: {exc}")
                raise

    def _table_info(self, table: str) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(f"PRAGMA table_info({table});")
        return [dict(row) for row in cursor.fetchall()]

    def _table_columns(self, table: str) -> List[str]:
        return [row['name'] for row in self._table_info(table)]

    def _add_column_if_missing(self, table: str, column: str, definition: str) -> None:
        cursor = self._conn.execute(f"PRAGMA table_info({table});")
        columns = {row['name'] for row in cursor.fetchall()}
        if column in columns:
            return
        try:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition};")
            logger.info("Added column %s.%s", table, column)
        except sqlite3.DatabaseError as exc:
            logger.error("Failed to add column %s.%s: %s", table, column, exc)

    def _rebuild_video_ratings_schema_if_needed(self) -> None:
        info = self._table_info('video_ratings')
        if not info:
            return

        has_yt_channel = any(column['name'] == 'yt_channel' for column in info)
        has_ha_channel = any(column['name'] == 'ha_channel' for column in info)
        yt_title_notnull = any(column['name'] == 'yt_title' and column.get('notnull') == 1 for column in info)

        has_source = any(column['name'] == 'source' for column in info)

        needs_rebuild = has_yt_channel or has_ha_channel or yt_title_notnull or not has_source
        if not needs_rebuild:
            return

        reasons = []
        if has_yt_channel:
            reasons.append('drop yt_channel')
        if has_ha_channel:
            reasons.append('drop ha_channel')
        if yt_title_notnull:
            reasons.append('allow NULL yt_title')
        if not has_source:
            reasons.append('add source column')

        logger.info("Rebuilding video_ratings schema (%s)", ', '.join(reasons))
        with self._lock:
            try:
                with self._conn:
                    # Get the actual columns that exist in the old table
                    old_columns = self._table_columns('video_ratings')

                    # Define the target columns we want to migrate
                    target_columns = [
                        'id', 'video_id', 'ha_title', 'ha_artist', 'yt_title', 'yt_artist',
                        'channel', 'ha_duration', 'yt_duration', 'youtube_url', 'rating',
                        'date_added', 'date_updated', 'date_played', 'play_count', 'rating_count',
                        'pending_match', 'source'
                    ]

                    # Only include columns that exist in the old table
                    # Exclude deprecated columns like yt_channel and ha_channel
                    columns_to_migrate = [col for col in target_columns if col in old_columns]

                    # For missing columns, we'll use defaults from the new schema
                    missing_columns = [col for col in target_columns if col not in old_columns]

                    self._conn.execute("ALTER TABLE video_ratings RENAME TO video_ratings_old;")
                    self._conn.executescript(self.VIDEO_RATINGS_SCHEMA)

                    if columns_to_migrate:
                        # Build the column list for migration
                        column_list_str = ', '.join(columns_to_migrate)

                        # Build the SELECT clause with defaults for missing columns
                        select_parts = []
                        for col in target_columns:
                            if col in columns_to_migrate:
                                select_parts.append(col)
                            elif col == 'source':
                                select_parts.append("'ha_live' as source")
                            elif col == 'pending_match':
                                select_parts.append("0 as pending_match")
                            else:
                                select_parts.append(f"NULL as {col}")

                        select_clause = ', '.join(select_parts)

                        self._conn.execute(
                            f"""
                            INSERT INTO video_ratings ({', '.join(target_columns)})
                            SELECT {select_clause}
                            FROM video_ratings_old;
                            """
                        )

                    self._conn.execute("DROP TABLE video_ratings_old;")
                    logger.info("Finished rebuilding video_ratings schema")
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to migrate video_ratings schema: %s", exc)
                raise

    def _cleanup_pending_metadata(self) -> None:
        """Normalize legacy rows that copied HA data into YT fields."""
        cleanup_statements = [
            (
                "UPDATE video_ratings SET channel = NULL "
                "WHERE pending_match = 1 OR lower(COALESCE(channel, '')) = 'youtube';"
            ),
            (
                "UPDATE video_ratings SET yt_artist = NULL "
                "WHERE pending_match = 1;"
            ),
            (
                "UPDATE video_ratings SET yt_duration = NULL "
                "WHERE pending_match = 1;"
            ),
            (
                "UPDATE video_ratings SET yt_title = NULL "
                "WHERE pending_match = 1;"
            ),
        ]
        with self._lock:
            try:
                with self._conn:
                    for statement in cleanup_statements:
                        self._conn.execute(statement)
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to cleanup pending metadata: %s", exc)

    @staticmethod
    def _timestamp(ts: Optional[str] = None) -> str:
        """
        Return timestamps in a format compatible with sqlite's built-in converters.
        sqlite3 expects 'YYYY-MM-DD HH:MM:SS' (space separator) for TIMESTAMP columns.
        """
        if ts:
            cleaned = ts.replace('T', ' ').replace('Z', '').strip()
            if cleaned:
                return cleaned
        return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    def _normalize_existing_timestamps(self) -> None:
        """Convert legacy ISO8601 timestamps with 'T' separator to sqlite friendly format."""
        columns = ('date_added', 'date_updated', 'date_played')
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
    def _pending_video_id(title: str, artist: Optional[str], duration: Optional[int]) -> str:
        """Generate a deterministic placeholder ID for HA snapshots."""
        parts = [title or '', artist or '', str(duration) if duration is not None else 'unknown']
        normalized = '|'.join(part.strip().lower() for part in parts)
        digest = hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:16]
        return f"ha_hash:{digest}"

    def upsert_video(self, video: Dict[str, Any], date_added: Optional[str] = None) -> None:
        """
        Insert or update metadata for a video.

        Args:
            video: Dict with keys video_id, ha_title, yt_title, channel, ha_artist,
                   yt_artist, ha_duration, yt_duration, youtube_url,
                   rating (optional).
            date_added: Optional override timestamp for initial insert (used by migration).
        """
        ha_title = video.get('ha_title') or video.get('yt_title') or 'Unknown Title'
        yt_title = video.get('yt_title')
        channel = video.get('channel')

        payload = {
            'video_id': video['video_id'],
            'ha_title': ha_title,
            'ha_artist': video.get('ha_artist'),
            'yt_title': yt_title,
            'yt_artist': video.get('yt_artist'),
            'channel': channel,
            'ha_duration': video.get('ha_duration'),
            'yt_duration': video.get('yt_duration'),
            'youtube_url': video.get('youtube_url'),
            'rating': video.get('rating', 'none') or 'none',
            'pending_match': 1 if video.get('pending_match') else 0,
            'source': video.get('source') or 'ha_live',
            'date_added': self._timestamp(date_added),
        }
        payload['date_updated'] = payload['date_added']

        upsert_sql = """
        INSERT INTO video_ratings (
            video_id, ha_title, ha_artist, yt_title, yt_artist, channel,
            ha_duration, yt_duration, youtube_url, rating, date_added, date_updated, play_count, rating_count, pending_match, source
        )
        VALUES (
            :video_id, :ha_title, :ha_artist, :yt_title, :yt_artist, :channel,
            :ha_duration, :yt_duration, :youtube_url, :rating, :date_added, :date_updated, 0, 0, :pending_match, :source
        )
        ON CONFLICT(video_id) DO UPDATE SET
            ha_title=excluded.ha_title,
            ha_artist=excluded.ha_artist,
            yt_title=excluded.yt_title,
            yt_artist=excluded.yt_artist,
            channel=excluded.channel,
            ha_duration=excluded.ha_duration,
            yt_duration=excluded.yt_duration,
            youtube_url=excluded.youtube_url,
            pending_match=excluded.pending_match,
            source=excluded.source;
        """
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(upsert_sql, payload)
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to upsert video {video['video_id']}: {exc}")

    def record_play(self, video_id: str, timestamp: Optional[str] = None) -> None:
        """Increment play counter and update last played timestamp."""
        ts = self._timestamp(timestamp)
        with self._lock:
            try:
                with self._conn:
                    cur = self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET play_count = COALESCE(play_count, 0) + 1,
                            date_played = ?,
                            date_updated = COALESCE(date_updated, ?)
                        WHERE video_id = ?
                        """,
                        (ts, ts, video_id),
                    )
                    if cur.rowcount == 0:
                        self._conn.execute(
                            """
                            INSERT INTO video_ratings (
                                video_id, ha_title, yt_title, rating,
                                date_added, date_updated, date_played, play_count, rating_count, pending_match
                            )
                            VALUES (?, 'Unknown', 'Unknown', 'none', ?, ?, ?, 1, 0, 0)
                            """,
                            (video_id, ts, ts, ts),
                        )
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to record play for {video_id}: {exc}")

    def record_rating(self, video_id: str, rating: str, timestamp: Optional[str] = None) -> None:
        """Update rating metadata and increment rating counter."""
        self._record_rating_internal(video_id, rating or 'none', timestamp, increment_counter=True)

    def record_rating_local(self, video_id: str, rating: str, timestamp: Optional[str] = None) -> None:
        """Update rating metadata without incrementing the rating counter."""
        self._record_rating_internal(video_id, rating or 'none', timestamp, increment_counter=False)

    def _record_rating_internal(
        self,
        video_id: str,
        rating: str,
        timestamp: Optional[str],
        increment_counter: bool,
    ) -> None:
        ts = self._timestamp(timestamp)
        counter_expr = "rating_count = COALESCE(rating_count, 0) + 1" if increment_counter else "rating_count = COALESCE(rating_count, 0)"
        default_count = 1 if increment_counter else 0
        with self._lock:
            try:
                with self._conn:
                    cur = self._conn.execute(
                        f"""
                        UPDATE video_ratings
                        SET rating = ?,
                            {counter_expr},
                            date_updated = ?
                        WHERE video_id = ?
                        """,
                        (rating, ts, video_id),
                    )
                    if cur.rowcount == 0:
                        self._conn.execute(
                            """
                            INSERT INTO video_ratings (
                                video_id, ha_title, yt_title, rating,
                                date_added, date_updated, play_count, rating_count, pending_match
                            )
                            VALUES (?, 'Unknown', 'Unknown', ?, ?, ?, 1, ?, 0)
                            """,
                            (video_id, rating, ts, ts, default_count),
                        )
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to record rating for {video_id}: {exc}")

    def get_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM video_ratings WHERE video_id = ?",
                (video_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def find_by_title(self, title: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return cached videos whose HA or YT title matches (case-insensitive)."""
        if not title:
            return []
        normalized = title.strip().lower()
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM video_ratings
                WHERE pending_match = 0 AND (lower(ha_title) = ? OR lower(yt_title) = ?)
                ORDER BY date_updated DESC, date_added DESC
                LIMIT ?
                """,
                (normalized, normalized, limit),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def find_by_exact_ha_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Return most recent video entry whose HA title exactly matches the provided string."""
        if not title:
            return None
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM video_ratings
                WHERE ha_title = ? AND pending_match = 0
                ORDER BY date_updated DESC, date_added DESC
                LIMIT 1
                """,
                (title,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def find_by_title_and_duration(self, title: str, duration: Optional[int]) -> Optional[Dict[str, Any]]:
        """
        Return the most recent video whose HA title matches and whose duration aligns.

        If duration is omitted, falls back to exact HA title lookup.
        """
        if not title:
            return None

        if duration is None:
            return self.find_by_exact_ha_title(title)

        query = """
            SELECT * FROM video_ratings
            WHERE ha_title = ?
              AND pending_match = 0
              AND (
                    (ha_duration IS NOT NULL AND ha_duration = ?)
                 OR (ha_duration IS NULL AND yt_duration IS NOT NULL AND yt_duration = ?)
              )
            ORDER BY date_updated DESC, date_added DESC
            LIMIT 1
        """
        with self._lock:
            cur = self._conn.execute(query, (title, duration, duration))
            row = cur.fetchone()
        return dict(row) if row else None

    def upsert_pending_media(self, media: Dict[str, Any]) -> str:
        """Persist Home Assistant metadata when YouTube lookups are unavailable."""
        title = media.get('title') or 'Unknown Title'
        artist = media.get('artist')
        duration = media.get('duration')
        pending_id = self._pending_video_id(title, artist, duration)

        payload = {
            'video_id': pending_id,
            'ha_title': title,
            'ha_artist': artist,
            'yt_title': None,
            'yt_artist': None,
            'channel': None,
            'ha_duration': duration,
            'yt_duration': None,
            'youtube_url': None,
            'rating': 'none',
            'pending_match': 1,
            'source': 'ha_live',
        }
        self.upsert_video(payload)
        return pending_id

    def enqueue_rating(self, video_id: str, rating: str) -> None:
        payload = (video_id, rating, self._timestamp())
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO pending_ratings (video_id, rating, requested_at, attempts, last_error, last_attempt)
                        VALUES (?, ?, ?, 0, NULL, NULL)
                        ON CONFLICT(video_id) DO UPDATE SET
                            rating=excluded.rating,
                            requested_at=excluded.requested_at,
                            attempts=0,
                            last_error=NULL,
                            last_attempt=NULL;
                        """,
                        payload,
                    )
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to enqueue rating for %s: %s", video_id, exc)

    def list_pending_ratings(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT video_id, rating, requested_at, attempts, last_error
                FROM pending_ratings
                ORDER BY requested_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def mark_pending_rating(self, video_id: str, success: bool, error: Optional[str] = None) -> None:
        with self._lock:
            try:
                with self._conn:
                    if success:
                        self._conn.execute("DELETE FROM pending_ratings WHERE video_id = ?", (video_id,))
                    else:
                        self._conn.execute(
                            """
                            UPDATE pending_ratings
                            SET attempts = attempts + 1,
                                last_error = ?,
                                last_attempt = ?
                            WHERE video_id = ?
                            """,
                            (error, self._timestamp(), video_id),
                        )
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to update pending rating for %s: %s", video_id, exc)

    def import_entry_exists(self, entry_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM import_history WHERE entry_id = ?",
                (entry_id,),
            )
            return cur.fetchone() is not None

    def log_import_entry(self, entry_id: str, source: str, video_id: str) -> None:
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO import_history (entry_id, source, video_id)
                        VALUES (?, ?, ?)
                        """,
                        (entry_id, source, video_id),
                    )
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to log import entry %s: %s", entry_id, exc)


_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Return singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
