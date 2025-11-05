"""
Video-related database operations.
"""
import sqlite3
from typing import Dict, Any, Optional, List

from logger import logger
from video_helpers import get_content_hash
from error_handler import log_and_suppress


class VideoOperations:
    """Handles video-related database operations."""

    def __init__(self, db_connection):
        self.db = db_connection
        self._conn = db_connection.connection
        self._lock = db_connection.lock
        self._timestamp = db_connection.timestamp

    def upsert_video(self, video: Dict[str, Any], date_added: Optional[str] = None) -> None:
        """
        Insert or update metadata for a video.

        Args:
            video: Dict with keys yt_video_id, ha_title, yt_title, yt_channel, ha_artist,
                   ha_app_name, ha_duration, yt_duration, yt_url, rating (optional).
            date_added: Optional override timestamp for initial insert (used by migration).
        """
        ha_title = video.get('ha_title') or video.get('yt_title') or 'Unknown Title'
        yt_title = video.get('yt_title')
        yt_channel = video.get('yt_channel')

        # Calculate content hash for duplicate detection
        ha_artist = video.get('ha_artist')
        ha_content_hash = get_content_hash(ha_title, video.get('ha_duration'), ha_artist)

        payload = {
            'yt_video_id': video.get('yt_video_id'),
            'ha_content_id': video.get('ha_content_id'),
            'ha_title': ha_title,
            'ha_artist': video.get('ha_artist'),
            'ha_app_name': video.get('ha_app_name'),
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
            'ha_content_hash': ha_content_hash,
            'yt_match_pending': 0 if video.get('yt_match_pending') == 0 else 1,
            'yt_match_requested_at': self._timestamp(video.get('yt_match_requested_at')),
            'yt_match_attempts': video.get('yt_match_attempts', 0),
            'yt_match_last_attempt': self._timestamp(video.get('yt_match_last_attempt')),
            'yt_match_last_error': video.get('yt_match_last_error'),
            'pending_reason': video.get('pending_reason'),
            'source': video.get('source') or 'ha_live',
            'date_added': self._timestamp(date_added) if date_added else self._timestamp(''),
        }

        # Skip upsert if ha_title is None (NOT NULL constraint in schema)
        # Also require at least one identifier (yt_video_id or ha_content_id)
        if not payload['ha_title']:
            logger.error(
                "Cannot upsert video: ha_title is required (NOT NULL constraint)"
            )
            return

        if payload['yt_video_id'] is None and payload['ha_content_id'] is None:
            logger.error(
                "Cannot upsert video: both yt_video_id and ha_content_id are None | Title: '%s'",
                ha_title
            )
            return

        # For pending videos (yt_video_id is None), use ha_content_id to check for duplicates
        if payload['yt_video_id'] is None:
            # Check if a record with this ha_content_id already exists
            with self._lock:
                try:
                    cursor = self._conn.execute(
                        "SELECT id FROM video_ratings WHERE ha_content_id = ? LIMIT 1",
                        (payload['ha_content_id'],)
                    )
                    existing = cursor.fetchone()

                    with self._conn:
                        if existing:
                            # Update existing pending record
                            self._conn.execute(
                                """
                                UPDATE video_ratings SET
                                    ha_title=?, ha_artist=?, ha_app_name=?, ha_duration=?,
                                    ha_content_hash=?, yt_match_pending=?, pending_reason=?,
                                    source=?, yt_match_requested_at=?, yt_match_attempts=?,
                                    yt_match_last_attempt=?, yt_match_last_error=?
                                WHERE ha_content_id=?
                                """,
                                (
                                    payload['ha_title'], payload['ha_artist'], payload['ha_app_name'],
                                    payload['ha_duration'], payload['ha_content_hash'],
                                    payload['yt_match_pending'], payload['pending_reason'],
                                    payload['source'], payload['yt_match_requested_at'],
                                    payload['yt_match_attempts'], payload['yt_match_last_attempt'],
                                    payload['yt_match_last_error'], payload['ha_content_id']
                                )
                            )
                        else:
                            # Insert new pending record (without yt_video_id to avoid NOT NULL constraint)
                            self._conn.execute(
                                """
                                INSERT INTO video_ratings (
                                    ha_content_id, ha_title, ha_artist, ha_app_name, ha_duration,
                                    rating, ha_content_hash, date_added, date_last_played,
                                    play_count, rating_score, yt_match_pending, pending_reason, source,
                                    yt_match_requested_at, yt_match_attempts, yt_match_last_attempt,
                                    yt_match_last_error
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    payload['ha_content_id'], payload['ha_title'], payload['ha_artist'],
                                    payload['ha_app_name'], payload['ha_duration'], payload['rating'],
                                    payload['ha_content_hash'], payload['date_added'], payload['date_added'],
                                    payload['yt_match_pending'], payload['pending_reason'],
                                    payload['source'], payload['yt_match_requested_at'],
                                    payload['yt_match_attempts'], payload['yt_match_last_attempt'],
                                    payload['yt_match_last_error']
                                )
                            )
                except sqlite3.DatabaseError as exc:
                    log_and_suppress(
                        exc,
                        f"Failed to upsert pending video (ha_content_id: {payload.get('ha_content_id', 'unknown')})",
                        level="error"
                    )
            return

        # Normal upsert for videos with yt_video_id
        upsert_sql = """
        INSERT INTO video_ratings (
            yt_video_id, ha_content_id, ha_title, ha_artist, ha_app_name, yt_title, yt_channel, yt_channel_id,
            yt_description, yt_published_at, yt_category_id, yt_live_broadcast,
            yt_location, yt_recording_date,
            ha_duration, yt_duration, yt_url, rating, ha_content_hash, date_added, date_last_played,
            play_count, rating_score, yt_match_pending, pending_reason, source,
            yt_match_requested_at, yt_match_attempts, yt_match_last_attempt, yt_match_last_error
        )
        VALUES (
            :yt_video_id, :ha_content_id, :ha_title, :ha_artist, :ha_app_name, :yt_title, :yt_channel, :yt_channel_id,
            :yt_description, :yt_published_at, :yt_category_id, :yt_live_broadcast,
            :yt_location, :yt_recording_date,
            :ha_duration, :yt_duration, :yt_url, :rating, :ha_content_hash, :date_added, :date_added,
            0, 0, :yt_match_pending, :pending_reason, :source,
            :yt_match_requested_at, :yt_match_attempts, :yt_match_last_attempt, :yt_match_last_error
        )
        ON CONFLICT(yt_video_id) DO UPDATE SET
            ha_content_id=excluded.ha_content_id,
            ha_title=excluded.ha_title,
            ha_artist=excluded.ha_artist,
            ha_app_name=excluded.ha_app_name,
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
            ha_content_hash=excluded.ha_content_hash,
            yt_match_pending=excluded.yt_match_pending,
            yt_match_requested_at=excluded.yt_match_requested_at,
            yt_match_attempts=excluded.yt_match_attempts,
            yt_match_last_attempt=excluded.yt_match_last_attempt,
            yt_match_last_error=excluded.yt_match_last_error,
            pending_reason=excluded.pending_reason,
            source=excluded.source;
        """
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(upsert_sql, payload)
            except sqlite3.DatabaseError as exc:
                # Critical operation - should not fail silently
                log_and_suppress(
                    exc,
                    f"Failed to upsert video {video.get('yt_video_id', 'unknown')}",
                    level="error"
                )

    def record_play(self, yt_video_id: str, timestamp: Optional[str] = None) -> None:
        """Increment play counter and update last played timestamp."""
        ts = self._timestamp(timestamp) if timestamp else self._timestamp('')
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
                                date_added, date_last_played, play_count, rating_score, yt_match_pending
                            )
                            VALUES (?, 'Unknown', 'Unknown', 'none', ?, ?, 1, 0, 0)
                            """,
                            (yt_video_id, ts, ts),
                        )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    f"Failed to record play for {yt_video_id}",
                    level="error"
                )

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
        ts = self._timestamp(timestamp) if timestamp else self._timestamp('')

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

                        # Calculate score change
                        # If rating the same thing again, add to the score (+1 for like, -1 for dislike)
                        # If changing rating, calculate delta from old to new
                        if rating == old_rating:
                            # Same rating - increment score in same direction
                            score_delta = 1 if rating == 'like' else (-1 if rating == 'dislike' else 0)
                        else:
                            # Rating changed - calculate transition delta
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
                                date_added, play_count, rating_score, yt_match_pending
                            )
                            VALUES (?, 'Unknown', 'Unknown', ?, ?, 1, ?, 0)
                            """,
                            (yt_video_id, rating, ts, initial_score),
                        )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    f"Failed to record rating for {yt_video_id}",
                    level="error"
                )

    def get_video(self, yt_video_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM video_ratings WHERE yt_video_id = ?",
                (yt_video_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def find_by_title_and_duration(self, title: str, duration: int) -> Optional[Dict[str, Any]]:
        """
        Return the most recent video whose HA title matches and whose duration aligns.
        Duration must be provided (always available from HA).
        """
        if not title:
            return None

        query = """
            SELECT * FROM video_ratings
            WHERE ha_title = ?
              AND yt_match_pending = 0
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

    def find_by_content_hash(self, title: str, duration: Optional[int], artist: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Find a video by its content hash (title + duration + artist).
        This allows finding duplicates even if title/artist formatting differs slightly.
        """
        if not title:
            return None

        content_hash = get_content_hash(title, duration, artist)

        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM video_ratings
                WHERE ha_content_hash = ? AND yt_match_pending = 0
                ORDER BY date_last_played DESC, date_added DESC
                LIMIT 1
                """,
                (content_hash,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def find_cached_video_combined(self, title: str, duration: int, artist: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Optimized cache lookup combining content hash and title+duration in a single query.
        Tries content hash first (more flexible), falls back to exact title+duration match.

        Args:
            title: Video title
            duration: Video duration in seconds
            artist: Optional artist/channel name

        Returns:
            Cached video dict if found, None otherwise
        """
        if not title:
            return None

        content_hash = get_content_hash(title, duration, artist)

        # Single query with OR condition combining both lookup strategies
        query = """
            SELECT * FROM video_ratings
            WHERE yt_match_pending = 0
              AND (
                  ha_content_hash = ?
                  OR (
                      ha_title = ?
                      AND (
                          (ha_duration IS NOT NULL AND ha_duration = ?)
                          OR (ha_duration IS NULL AND yt_duration IS NOT NULL AND yt_duration = ?)
                      )
                  )
              )
            ORDER BY
                CASE WHEN ha_content_hash = ? THEN 0 ELSE 1 END,
                date_last_played DESC,
                date_added DESC
            LIMIT 1
        """

        with self._lock:
            cur = self._conn.execute(query, (content_hash, title, duration, duration, content_hash))
            row = cur.fetchone()

        return dict(row) if row else None

    def get_pending_videos(self, limit: int = 50, reason_filter: Optional[str] = None) -> List[Dict]:
        """
        Get pending videos for retry after quota recovery.

        Args:
            limit: Maximum number of pending videos to return
            reason_filter: Optional filter by pending_reason (e.g., 'quota_exceeded')

        Returns:
            List of pending video records
        """
        query = """
            SELECT * FROM video_ratings
            WHERE yt_match_pending = 1
        """
        params = []

        if reason_filter:
            query += " AND pending_reason = ?"
            params.append(reason_filter)

        query += " ORDER BY date_added ASC LIMIT ?"
        params.append(limit)

        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def resolve_pending_video(self, ha_content_id: str, youtube_data: Dict[str, Any]) -> None:
        """
        Update pending video with YouTube data and mark as resolved.
        If the yt_video_id already exists (duplicate), removes the pending entry instead.

        Args:
            ha_content_id: The placeholder ID (ha_hash:*)
            youtube_data: YouTube video data to populate
        """
        yt_video_id = youtube_data.get('yt_video_id')

        with self._lock:
            try:
                # Check if this yt_video_id already exists
                cursor = self._conn.execute(
                    "SELECT COUNT(*) as count FROM video_ratings WHERE yt_video_id = ?",
                    (yt_video_id,)
                )
                existing_count = cursor.fetchone()['count']

                if existing_count > 0:
                    # Video already exists - this pending entry is a duplicate
                    # Delete it instead of trying to update (which would violate UNIQUE constraint)
                    with self._conn:
                        self._conn.execute(
                            "DELETE FROM video_ratings WHERE ha_content_id = ? AND yt_match_pending = 1",
                            (ha_content_id,)
                        )
                    from logger import logger
                    logger.info(
                        f"Removed duplicate pending entry {ha_content_id} - video {yt_video_id} already exists"
                    )
                else:
                    # Normal case - update the pending entry with YouTube data
                    with self._conn:
                        self._conn.execute(
                            """
                            UPDATE video_ratings
                            SET yt_video_id = ?,
                                yt_title = ?,
                                yt_channel = ?,
                                yt_channel_id = ?,
                                yt_description = ?,
                                yt_published_at = ?,
                                yt_category_id = ?,
                                yt_live_broadcast = ?,
                                yt_location = ?,
                                yt_recording_date = ?,
                                yt_duration = ?,
                                yt_url = ?,
                                yt_match_pending = 0,
                                pending_reason = NULL
                            WHERE ha_content_id = ? AND yt_match_pending = 1
                            """,
                            (
                                yt_video_id,
                                youtube_data.get('title'),
                                youtube_data.get('channel'),
                                youtube_data.get('channel_id'),
                                youtube_data.get('description'),
                                self._timestamp(youtube_data.get('published_at')),
                                youtube_data.get('category_id'),
                                youtube_data.get('live_broadcast'),
                                youtube_data.get('location'),
                                self._timestamp(youtube_data.get('recording_date')),
                                youtube_data.get('duration'),
                                youtube_data.get('url'),
                                ha_content_id
                            )
                        )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    f"Failed to resolve pending video {ha_content_id}",
                    level="error"
                )

    def mark_pending_not_found(self, ha_content_id: str) -> None:
        """
        Mark pending video as not found (no YouTube match exists).
        Updates pending_reason to 'not_found' but keeps yt_match_pending=1.

        Args:
            ha_content_id: The placeholder ID (ha_hash:*)
        """
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        """
                        UPDATE video_ratings
                        SET pending_reason = 'not_found'
                        WHERE ha_content_id = ? AND yt_match_pending = 1
                        """,
                        (ha_content_id,)
                    )
            except sqlite3.DatabaseError as exc:
                log_and_suppress(
                    exc,
                    f"Failed to mark pending video as not found {ha_content_id}",
                    level="error"
                )