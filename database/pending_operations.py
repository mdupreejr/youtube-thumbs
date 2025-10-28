"""
Pending queue database operations.
"""
import hashlib
import sqlite3
from typing import Dict, Any, Optional, List

from logger import logger


class PendingOperations:
    """Handles pending media and ratings queue operations."""

    def __init__(self, db_connection, video_ops):
        self.db = db_connection
        self.video_ops = video_ops
        self._conn = db_connection.connection
        self._lock = db_connection.lock
        self._timestamp = db_connection.timestamp

    @staticmethod
    def _pending_video_id(title: str, artist: Optional[str], duration: Optional[int]) -> str:
        """Generate a deterministic placeholder ID for HA snapshots."""
        parts = [title or '', artist or '', str(duration) if duration is not None else 'unknown']
        normalized = '|'.join(part.strip().lower() for part in parts)
        digest = hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:16]
        return f"ha_hash:{digest}"

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
        self.video_ops.upsert_video(payload)
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