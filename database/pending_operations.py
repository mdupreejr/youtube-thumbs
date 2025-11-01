"""
Pending queue database operations.
"""
import hashlib
import sqlite3
from typing import Dict, Any, Optional, List

from logger import logger
from error_handler import log_and_suppress


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
        digest = hashlib.sha1(normalized.encode('utf-8'), usedforsecurity=False).hexdigest()[:16]
        return f"ha_hash:{digest}"

    def upsert_pending_media(self, media: Dict[str, Any], reason: str = 'quota_exceeded') -> str:
        """
        Persist Home Assistant metadata when YouTube lookups are unavailable.

        Args:
            media: Media information from Home Assistant
            reason: Why this video is pending (default: 'quota_exceeded')
                   - 'quota_exceeded': YouTube API quota blocked
                   - 'not_found': Video not found on YouTube
                   - 'search_failed': YouTube search failed
        """
        title = media.get('title') or 'Unknown Title'
        artist = media.get('artist', 'Unknown')
        app_name = media.get('app_name', 'YouTube')
        duration = media.get('duration')
        pending_id = self._pending_video_id(title, artist, duration)

        payload = {
            'yt_video_id': None,  # v1.50.0: yt_video_id is NULL for pending videos
            'ha_content_id': pending_id,  # v1.50.0: Use ha_content_id for placeholder
            'ha_title': title,
            'ha_artist': artist,
            'ha_app_name': app_name,
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
            'yt_match_pending': 1,
            'pending_reason': reason,
            'source': 'ha_live',
        }
        self.video_ops.upsert_video(payload)
        return pending_id

    def enqueue_rating(self, yt_video_id: str, rating: str) -> None:
        """
        v1.58.0: Queue a rating using rating_queue_* columns.
        Used when YouTube API quota is blocked.
        """
        timestamp = self._timestamp('')
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET rating_queue_pending = ?,
                            rating_queue_requested_at = ?,
                            rating_queue_attempts = 0,
                            rating_queue_last_error = NULL,
                            rating_queue_last_attempt = NULL
                        WHERE yt_video_id = ?
                        """,
                        (rating, timestamp, yt_video_id),
                    )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    "Failed to enqueue rating for %s",
                    yt_video_id,
                    level="error"
                )

    def list_pending_ratings(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        v1.58.0: Query pending ratings from rating_queue_* columns.
        Returns videos where rating_queue_pending IS NOT NULL.
        """
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT yt_video_id,
                       rating_queue_pending as rating,
                       rating_queue_requested_at as requested_at,
                       rating_queue_attempts as attempts,
                       rating_queue_last_error as last_error
                FROM video_ratings
                WHERE rating_queue_pending IS NOT NULL
                ORDER BY rating_queue_requested_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def mark_pending_rating(self, yt_video_id: str, success: bool, error: Optional[str] = None) -> None:
        """
        v1.58.0: Clear or update rating queue columns in video_ratings table.
        On success: NULL out all rating_queue_* columns
        On failure: Increment attempts, record error
        """
        with self._lock:
            try:
                with self._conn:
                    if success:
                        # Clear pending rating columns
                        self._conn.execute(
                            """
                            UPDATE video_ratings
                            SET rating_queue_pending = NULL,
                                rating_queue_requested_at = NULL,
                                rating_queue_attempts = 0,
                                rating_queue_last_error = NULL,
                                rating_queue_last_attempt = NULL
                            WHERE yt_video_id = ?
                            """,
                            (yt_video_id,)
                        )
                    else:
                        # Increment retry counter and record error
                        self._conn.execute(
                            """
                            UPDATE video_ratings
                            SET rating_queue_attempts = rating_queue_attempts + 1,
                                rating_queue_last_error = ?,
                                rating_queue_last_attempt = ?
                            WHERE yt_video_id = ?
                            """,
                            (error, self._timestamp(''), yt_video_id),
                        )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    "Failed to update pending rating for %s",
                    yt_video_id,
                    level="error"
                )