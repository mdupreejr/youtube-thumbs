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
        schema_sql = """
        CREATE TABLE IF NOT EXISTS video_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT UNIQUE NOT NULL,
            ha_title TEXT NOT NULL,
            yt_title TEXT NOT NULL,
            channel TEXT,
            ha_duration INTEGER,
            yt_duration INTEGER,
            youtube_url TEXT,
            rating TEXT DEFAULT 'none',
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_updated TIMESTAMP,
            date_played TIMESTAMP,
            play_count INTEGER DEFAULT 1,
            rating_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_video_ratings_video_id ON video_ratings(video_id);
        CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title);
        """
        with self._lock:
            try:
                with self._conn:
                    self._conn.executescript(schema_sql)
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to initialize SQLite schema: {exc}")
                raise

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

    def upsert_video(self, video: Dict[str, Any], date_added: Optional[str] = None) -> None:
        """
        Insert or update metadata for a video.

        Args:
            video: Dict with keys video_id, ha_title, yt_title, channel, ha_duration,
                   yt_duration, youtube_url, rating (optional).
            date_added: Optional override timestamp for initial insert (used by migration).
        """
        ha_title = video.get('ha_title') or video.get('yt_title') or 'Unknown Title'
        yt_title = video.get('yt_title') or ha_title

        payload = {
            'video_id': video['video_id'],
            'ha_title': ha_title,
            'yt_title': yt_title,
            'channel': video.get('channel'),
            'ha_duration': video.get('ha_duration'),
            'yt_duration': video.get('yt_duration'),
            'youtube_url': video.get('youtube_url'),
            'rating': video.get('rating', 'none') or 'none',
            'date_added': self._timestamp(date_added),
        }

        upsert_sql = """
        INSERT INTO video_ratings (
            video_id, ha_title, yt_title, channel, ha_duration, yt_duration,
            youtube_url, rating, date_added, play_count, rating_count
        )
        VALUES (
            :video_id, :ha_title, :yt_title, :channel, :ha_duration, :yt_duration,
            :youtube_url, :rating, :date_added, 0, 0
        )
        ON CONFLICT(video_id) DO UPDATE SET
            ha_title=excluded.ha_title,
            yt_title=excluded.yt_title,
            channel=excluded.channel,
            ha_duration=excluded.ha_duration,
            yt_duration=excluded.yt_duration,
            youtube_url=excluded.youtube_url;
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
                            date_played = ?
                        WHERE video_id = ?
                        """,
                        (ts, video_id),
                    )
                    if cur.rowcount == 0:
                        self._conn.execute(
                            """
                            INSERT INTO video_ratings (
                                video_id, ha_title, yt_title, rating,
                                date_added, date_played, play_count, rating_count
                            )
                            VALUES (?, 'Unknown', 'Unknown', 'none', ?, ?, 1, 0)
                            """,
                            (video_id, ts, ts),
                        )
            except sqlite3.DatabaseError as exc:
                logger.error(f"Failed to record play for {video_id}: {exc}")

    def record_rating(self, video_id: str, rating: str, timestamp: Optional[str] = None) -> None:
        """Update rating metadata and increment rating counter."""
        ts = self._timestamp(timestamp)
        normalized_rating = rating or 'none'
        with self._lock:
            try:
                with self._conn:
                    cur = self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET rating = ?,
                            rating_count = COALESCE(rating_count, 0) + 1,
                            date_updated = ?
                        WHERE video_id = ?
                        """,
                        (normalized_rating, ts, video_id),
                    )
                    if cur.rowcount == 0:
                        self._conn.execute(
                            """
                            INSERT INTO video_ratings (
                                video_id, ha_title, yt_title, rating,
                                date_added, date_updated, play_count, rating_count
                            )
                            VALUES (?, 'Unknown', 'Unknown', ?, ?, ?, 1, 1)
                            """,
                            (video_id, normalized_rating, ts, ts),
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
                WHERE lower(ha_title) = ? OR lower(yt_title) = ?
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
                WHERE ha_title = ?
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


_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Return singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
