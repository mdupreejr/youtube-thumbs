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
        # VALIDATION: Reject garbage data before it gets into the database
        # Home Assistant API never returns 'Unknown' or empty strings
        title = media.get('title')
        artist = media.get('artist')

        if not title or title in ('Unknown', 'Unknown Title', ''):
            from logger import logger
            logger.warning(
                "Rejecting pending media with invalid title '%s' - HA API never returns 'Unknown'",
                title
            )
            return None

        # Clean up artist - if it's 'Unknown' or empty, treat as None (no artist)
        if artist in ('Unknown', '', None):
            artist = None

        app_name = media.get('app_name', 'YouTube')
        duration = media.get('duration')
        pending_id = self._pending_video_id(title, artist, duration)

        payload = {
            'yt_video_id': None,
            'ha_content_id': pending_id,
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

        Raises:
            ValueError: If rating is invalid
            Exception: If too many pending ratings (>100 globally)
        """
        # SECURITY: Validate inputs before database operation
        if rating not in ['like', 'dislike']:
            raise ValueError(f"Invalid rating type: {rating}")

        # SECURITY: Prevent queue flooding by limiting pending ratings
        MAX_PENDING_RATINGS = 100

        timestamp = self._timestamp('')
        with self._lock:
            try:
                # Check pending count before allowing new entry
                cur = self._conn.execute(
                    "SELECT COUNT(*) as count FROM video_ratings WHERE rating_queue_pending IS NOT NULL"
                )
                pending_count = cur.fetchone()['count']

                if pending_count >= MAX_PENDING_RATINGS:
                    logger.warning(f"Rating queue full ({pending_count} pending), rejecting new rating")
                    raise Exception("Rating queue is full. Please try again later.")

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

    def enqueue_search(self, media: Dict[str, Any], callback_rating: Optional[str] = None) -> int:
        """
        Queue a video search request for background processing.

        Args:
            media: Media information from Home Assistant
            callback_rating: Optional rating to apply after search completes ('like' or 'dislike')

        Returns:
            Search queue ID

        Raises:
            Exception: If queue is full (>1000 pending searches)
        """
        # SECURITY: Prevent queue flooding by limiting pending searches
        MAX_PENDING_SEARCHES = 1000

        timestamp = self._timestamp('')
        with self._lock:
            try:
                # Check pending count before allowing new entry
                cur = self._conn.execute(
                    "SELECT COUNT(*) as count FROM search_queue WHERE status = 'pending'"
                )
                pending_count = cur.fetchone()['count']

                if pending_count >= MAX_PENDING_SEARCHES:
                    logger.warning(f"Search queue full ({pending_count} pending), rejecting new search")
                    raise Exception("Search queue is full. Please try again later.")

                with self._conn:
                    cur = self._conn.execute(
                        """
                        INSERT INTO search_queue (
                            ha_title, ha_artist, ha_album, ha_content_id,
                            ha_duration, ha_app_name, status, requested_at,
                            callback_rating
                        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                        """,
                        (
                            media.get('title'),
                            media.get('artist'),
                            media.get('album'),
                            media.get('content_id'),
                            media.get('duration'),
                            media.get('app_name', 'YouTube'),
                            timestamp,
                            callback_rating
                        ),
                    )
                    return cur.lastrowid
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    "Failed to enqueue search for %s",
                    media.get('title'),
                    level="error"
                )
                return None

    def list_pending_searches(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Query pending search requests from search_queue.
        Returns searches where status='pending'.
        """
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, ha_title, ha_artist, ha_album, ha_content_id,
                       ha_duration, ha_app_name, status, requested_at,
                       attempts, last_error, callback_rating
                FROM search_queue
                WHERE status = 'pending'
                ORDER BY requested_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def claim_pending_search(self) -> Optional[Dict[str, Any]]:
        """
        Atomically claim next pending search for processing.
        Marks search as 'processing' to prevent duplicate processing.

        Returns:
            Search job dict or None if no pending searches
        """
        with self._lock:
            try:
                with self._conn:
                    # Atomic: select and update in one operation
                    cur = self._conn.execute(
                        """
                        UPDATE search_queue
                        SET status = 'processing',
                            last_attempt = ?
                        WHERE id = (
                            SELECT id FROM search_queue
                            WHERE status = 'pending'
                            ORDER BY requested_at ASC
                            LIMIT 1
                        )
                        RETURNING id, ha_title, ha_artist, ha_album, ha_content_id,
                                  ha_duration, ha_app_name, requested_at,
                                  attempts, last_error, callback_rating
                        """,
                        (self._timestamp(''),)
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    "Failed to claim pending search",
                    level="error"
                )
                return None

    def mark_search_complete(self, search_id: int, found_video_id: str) -> None:
        """
        Mark search as complete and record the found video ID.

        Args:
            search_id: Search queue ID
            found_video_id: The YouTube video ID that was found
        """
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        UPDATE search_queue
                        SET status = 'completed',
                            found_video_id = ?,
                            last_attempt = ?
                        WHERE id = ?
                        """,
                        (found_video_id, self._timestamp(''), search_id),
                    )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    "Failed to mark search complete for ID %s",
                    search_id,
                    level="error"
                )

    def mark_search_complete_with_callback(self, search_id: int, found_video_id: str, callback_rating: Optional[str] = None) -> None:
        """
        Atomically mark search as complete and optionally enqueue callback rating.
        Both operations happen in single transaction to prevent data loss.

        Args:
            search_id: Search queue ID
            found_video_id: The YouTube video ID that was found
            callback_rating: Optional rating to enqueue ('like' or 'dislike')
        """
        timestamp = self._timestamp('')
        with self._lock:
            try:
                with self._conn:
                    # Mark search complete
                    self._conn.execute(
                        """
                        UPDATE search_queue
                        SET status = 'completed',
                            found_video_id = ?,
                            last_attempt = ?
                        WHERE id = ?
                        """,
                        (found_video_id, timestamp, search_id),
                    )

                    # If callback rating specified, enqueue it in same transaction
                    if callback_rating:
                        # Validate rating
                        if callback_rating not in ['like', 'dislike']:
                            raise ValueError(f"Invalid callback rating: {callback_rating}")

                        # Check rating queue limit (same as enqueue_rating)
                        cur = self._conn.execute(
                            "SELECT COUNT(*) as count FROM video_ratings WHERE rating_queue_pending IS NOT NULL"
                        )
                        pending_count = cur.fetchone()['count']
                        if pending_count >= 100:  # MAX_PENDING_RATINGS
                            logger.warning(f"Rating queue full, cannot enqueue callback rating for {found_video_id}")
                            # Don't fail the search complete, just skip rating
                            return

                        # Enqueue the rating
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
                            (callback_rating, timestamp, found_video_id),
                        )

            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    "Failed to complete search with callback for ID %s",
                    search_id,
                    level="error"
                )

    def mark_search_failed(self, search_id: int, error: str) -> None:
        """
        Increment search attempts and record error.

        Args:
            search_id: Search queue ID
            error: Error message
        """
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        UPDATE search_queue
                        SET attempts = attempts + 1,
                            last_error = ?,
                            last_attempt = ?
                        WHERE id = ?
                        """,
                        (error, self._timestamp(''), search_id),
                    )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    "Failed to mark search failed for ID %s",
                    search_id,
                    level="error"
                )