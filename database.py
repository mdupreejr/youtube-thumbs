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

    @staticmethod
    def _timestamp(ts: Optional[str] = None) -> Optional[str]:
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
            video: Dict with keys yt_video_id, ha_title, yt_title, yt_channel, ha_artist,
                   ha_duration, yt_duration, yt_url,
                   rating (optional).
            date_added: Optional override timestamp for initial insert (used by migration).
        """
        ha_title = video.get('ha_title') or video.get('yt_title') or 'Unknown Title'
        yt_title = video.get('yt_title')
        yt_channel = video.get('yt_channel')

        payload = {
            'yt_video_id': video['yt_video_id'],
            'ha_title': ha_title,
            'ha_artist': video.get('ha_artist'),
            'yt_title': yt_title,
            'yt_channel': yt_channel,
            'yt_channel_id': video.get('yt_channel_id'),
            'yt_description': video.get('yt_description'),
            'yt_published_at': self._timestamp(video.get('yt_published_at')),
            'yt_category_id': video.get('yt_category_id'),
            'yt_live_broadcast': video.get('yt_live_broadcast'),
            'yt_location': video.get('yt_location'),
            'yt_recording_date': self._timestamp(video.get('yt_recording_date')),
            'ha_duration': video.get('ha_duration'),
            'yt_duration': video.get('yt_duration'),
            'yt_url': video.get('yt_url'),
            'rating': video.get('rating', 'none') or 'none',
            'pending_match': 1 if video.get('pending_match') else 0,
            'source': video.get('source') or 'ha_live',
            'date_added': self._timestamp(date_added),
        }

        upsert_sql = """
        INSERT INTO video_ratings (
            yt_video_id, ha_title, ha_artist, yt_title, yt_channel, yt_channel_id,
            yt_description, yt_published_at, yt_category_id, yt_live_broadcast,
            yt_location, yt_recording_date,
            ha_duration, yt_duration, yt_url, rating, date_added,
            play_count, rating_score, pending_match, source
        )
        VALUES (
            :yt_video_id, :ha_title, :ha_artist, :yt_title, :yt_channel, :yt_channel_id,
            :yt_description, :yt_published_at, :yt_category_id, :yt_live_broadcast,
            :yt_location, :yt_recording_date,
            :ha_duration, :yt_duration, :yt_url, :rating, :date_added,
            0, 0, :pending_match, :source
        )
        ON CONFLICT(yt_video_id) DO UPDATE SET
            ha_title=excluded.ha_title,
            ha_artist=excluded.ha_artist,
            yt_title=excluded.yt_title,
            yt_channel=excluded.yt_channel,
            yt_channel_id=excluded.yt_channel_id,
            yt_description=excluded.yt_description,
            yt_published_at=excluded.yt_published_at,
            yt_category_id=excluded.yt_category_id,
            yt_live_broadcast=excluded.yt_live_broadcast,
            yt_location=excluded.yt_location,
            yt_recording_date=excluded.yt_recording_date,
            ha_duration=excluded.ha_duration,
            yt_duration=excluded.yt_duration,
            yt_url=excluded.yt_url,
            pending_match=excluded.pending_match,
            source=excluded.source;
        """
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(upsert_sql, payload)
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to upsert video {video['yt_video_id']}: {exc}")

    def record_play(self, yt_video_id: str, timestamp: Optional[str] = None) -> None:
        """Increment play counter and update last played timestamp."""
        ts = self._timestamp(timestamp)
        with self._lock:
            try:
                with self._conn:
                    cur = self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET play_count = COALESCE(play_count, 0) + 1,
                            date_last_played = ?
                        WHERE yt_video_id = ?
                        """,
                        (ts, yt_video_id),
                    )
                    if cur.rowcount == 0:
                        self._conn.execute(
                            """
                            INSERT INTO video_ratings (
                                yt_video_id, ha_title, yt_title, rating,
                                date_added, date_last_played, play_count, rating_score, pending_match
                            )
                            VALUES (?, 'Unknown', 'Unknown', 'none', ?, ?, 1, 0, 0)
                            """,
                            (yt_video_id, ts, ts),
                        )
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to record play for {yt_video_id}: {exc}")

    def record_rating(self, yt_video_id: str, rating: str, timestamp: Optional[str] = None) -> None:
        """Update rating metadata and increment rating counter."""
        self._record_rating_internal(yt_video_id, rating or 'none', timestamp, increment_counter=True)

    def record_rating_local(self, yt_video_id: str, rating: str, timestamp: Optional[str] = None) -> None:
        """Update rating metadata without incrementing the rating counter."""
        self._record_rating_internal(yt_video_id, rating or 'none', timestamp, increment_counter=False)

    def _record_rating_internal(
        self,
        yt_video_id: str,
        rating: str,
        timestamp: Optional[str],
        increment_counter: bool,
    ) -> None:
        ts = self._timestamp(timestamp)

        with self._lock:
            try:
                with self._conn:
                    # Get current rating to calculate proper score delta
                    cur = self._conn.execute(
                        "SELECT rating, rating_score FROM video_ratings WHERE yt_video_id = ?",
                        (yt_video_id,)
                    )
                    current = cur.fetchone()

                    if current:
                        old_rating = current['rating'] or 'none'
                        current_score = current['rating_score'] or 0

                        # Calculate score change based on transition
                        old_value = 1 if old_rating == 'like' else (-1 if old_rating == 'dislike' else 0)
                        new_value = 1 if rating == 'like' else (-1 if rating == 'dislike' else 0)
                        score_delta = new_value - old_value

                        if increment_counter and score_delta != 0:
                            self._conn.execute(
                                """
                                UPDATE video_ratings
                                SET rating = ?,
                                    rating_score = COALESCE(rating_score, 0) + ?
                                WHERE yt_video_id = ?
                                """,
                                (rating, score_delta, yt_video_id),
                            )
                        else:
                            self._conn.execute(
                                """
                                UPDATE video_ratings
                                SET rating = ?
                                WHERE yt_video_id = ?
                                """,
                                (rating, yt_video_id),
                            )
                    else:
                        # New video - set initial score based on rating
                        initial_score = 1 if rating == 'like' else (-1 if rating == 'dislike' else 0)
                        initial_score = initial_score if increment_counter else 0

                        self._conn.execute(
                            """
                            INSERT INTO video_ratings (
                                yt_video_id, ha_title, yt_title, rating,
                                date_added, play_count, rating_score, pending_match
                            )
                            VALUES (?, 'Unknown', 'Unknown', ?, ?, 1, ?, 0)
                            """,
                            (yt_video_id, rating, ts, initial_score),
                        )
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to record rating for {yt_video_id}: {exc}")

    def get_video(self, yt_video_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM video_ratings WHERE yt_video_id = ?",
                (yt_video_id,),
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
                ORDER BY date_last_played DESC, date_added DESC
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
                ORDER BY date_last_played DESC, date_added DESC
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
            ORDER BY date_last_played DESC, date_added DESC
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
            'yt_video_id': pending_id,
            'ha_title': title,
            'ha_artist': artist,
            'yt_title': None,
            'yt_channel': None,
            'yt_channel_id': None,
            'yt_description': None,
            'yt_published_at': None,
            'yt_category_id': None,
            'yt_live_broadcast': None,
            'yt_location': None,
            'yt_recording_date': None,
            'ha_duration': duration,
            'yt_duration': None,
            'yt_url': None,
            'rating': 'none',
            'pending_match': 1,
            'source': 'ha_live',
        }
        self.upsert_video(payload)
        return pending_id

    def enqueue_rating(self, yt_video_id: str, rating: str) -> None:
        payload = (yt_video_id, rating, self._timestamp())
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO pending_ratings (yt_video_id, rating, requested_at, attempts, last_error, last_attempt)
                        VALUES (?, ?, ?, 0, NULL, NULL)
                        ON CONFLICT(yt_video_id) DO UPDATE SET
                            rating=excluded.rating,
                            requested_at=excluded.requested_at,
                            attempts=0,
                            last_error=NULL,
                            last_attempt=NULL;
                        """,
                        payload,
                    )
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to enqueue rating for %s: %s", yt_video_id, exc)

    def list_pending_ratings(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT yt_video_id, rating, requested_at, attempts, last_error
                FROM pending_ratings
                ORDER BY requested_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def mark_pending_rating(self, yt_video_id: str, success: bool, error: Optional[str] = None) -> None:
        with self._lock:
            try:
                with self._conn:
                    if success:
                        self._conn.execute("DELETE FROM pending_ratings WHERE yt_video_id = ?", (yt_video_id,))
                    else:
                        self._conn.execute(
                            """
                            UPDATE pending_ratings
                            SET attempts = attempts + 1,
                                last_error = ?,
                                last_attempt = ?
                            WHERE yt_video_id = ?
                            """,
                            (error, self._timestamp(), yt_video_id),
                        )
            except sqlite3.DatabaseError as exc:
                logger.error("Failed to update pending rating for %s: %s", yt_video_id, exc)

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


_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Return singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
