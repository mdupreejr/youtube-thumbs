"""
Pending queue database operations.

v4.0.0 DEPRECATION NOTICE:
==========================
This file contains LEGACY code from the old queue architecture and is DEPRECATED.

WHAT CHANGED IN v4.0.0:
-----------------------
1. Pending videos are NO LONGER stored in video_ratings table
   - Old: video_ratings with yt_match_pending=1, pending_reason, yt_match_attempts
   - New: Only matched videos (yt_video_id NOT NULL) are stored in video_ratings
   - Unmatched videos tracked exclusively in unified 'queue' table

2. Rating queue columns REMOVED from video_ratings table
   - Old: rating_queue_pending, rating_queue_requested_at, rating_queue_attempts, etc.
   - New: All ratings queued in unified 'queue' table (priority=1)

3. Search queue table REMOVED (search_queue)
   - Old: Separate search_queue table
   - New: Search operations in unified 'queue' table (priority=2)

MIGRATION PATH:
---------------
- Use database.enqueue_search() instead of pending_ops.enqueue_search()
- Use database.enqueue_rating() instead of pending_ops.enqueue_rating()
- Pending videos automatically migrate to queue on first access
- Old methods kept for backward compatibility but log deprecation warnings

This file will be removed in v5.0.0.
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
        v4.0.0: DEPRECATED - Pending videos are now tracked in queue table, not video_ratings.

        OLD BEHAVIOR (pre-v4.0.0):
        Persisted Home Assistant metadata in video_ratings with yt_match_pending=1
        when YouTube lookups were unavailable.

        NEW BEHAVIOR (v4.0.0+):
        Does nothing. Unmatched videos should be queued via database.enqueue_search()
        instead of being stored as pending entries in video_ratings.

        Args:
            media: Media information from Home Assistant (ignored)
            reason: Why this video is pending (ignored)

        Returns:
            None (previously returned pending_id)
        """
        logger.warning(
            "upsert_pending_media() called but is DEPRECATED in v4.0.0. "
            "Use database.enqueue_search() to queue video searches instead. "
            "Ignoring request for: %s",
            media.get('title', 'Unknown')
        )
        return None

    def enqueue_rating(self, yt_video_id: str, rating: str) -> None:
        """
        v4.0.0: DEPRECATED - Rating queue columns removed from video_ratings.

        OLD BEHAVIOR (pre-v4.0.0):
        Queued ratings using rating_queue_* columns in video_ratings table.

        NEW BEHAVIOR (v4.0.0+):
        Does nothing. Use database.enqueue_rating() which uses the unified queue table.

        Args:
            yt_video_id: YouTube video ID (ignored)
            rating: 'like' or 'dislike' (ignored)
        """
        logger.warning(
            "pending_ops.enqueue_rating() called but is DEPRECATED in v4.0.0. "
            "Use database.enqueue_rating() which uses unified queue table. "
            "Ignoring rating request for: %s",
            yt_video_id
        )

    def list_pending_ratings(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        v4.0.0: DEPRECATED - Rating queue columns removed from video_ratings.

        Returns empty list. Use database.get_queue_items(type='rating') instead.
        """
        logger.debug("list_pending_ratings() called but is DEPRECATED in v4.0.0 - returning empty list")
        return []

    def mark_pending_rating(self, yt_video_id: str, success: bool, error: Optional[str] = None) -> None:
        """
        v4.0.0: DEPRECATED - Rating queue columns removed from video_ratings.

        Does nothing. Queue operations now use database.mark_queue_item_completed/failed().
        """
        logger.debug(f"mark_pending_rating() called but is DEPRECATED in v4.0.0 - ignoring")

    def enqueue_search(self, media: Dict[str, Any], callback_rating: Optional[str] = None) -> int:
        """
        v4.0.0: DEPRECATED - search_queue table removed, use unified queue table.

        OLD BEHAVIOR (pre-v4.0.0):
        Queued searches in separate search_queue table.

        NEW BEHAVIOR (v4.0.0+):
        Does nothing. Use database.enqueue_search() which uses the unified queue table.

        Args:
            media: Media information from Home Assistant (ignored)
            callback_rating: Optional rating to apply after search (ignored)

        Returns:
            None (previously returned search queue ID)
        """
        logger.warning(
            "pending_ops.enqueue_search() called but is DEPRECATED in v4.0.0. "
            "Use database.enqueue_search() which uses unified queue table. "
            "Ignoring search request for: %s",
            media.get('title', 'Unknown')
        )
        return None

    def list_pending_searches(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        v4.0.0: DEPRECATED - search_queue table removed.
        Returns empty list. Use database.get_queue_items(type='search') instead.
        """
        logger.debug("list_pending_searches() called but is DEPRECATED in v4.0.0 - returning empty list")
        return []

    def claim_pending_search(self) -> Optional[Dict[str, Any]]:
        """
        v4.0.0: DEPRECATED - search_queue table removed.
        Returns None. Use database.claim_next_queue_item() instead.
        """
        logger.debug("claim_pending_search() called but is DEPRECATED in v4.0.0 - returning None")
        return None

    def mark_search_complete(self, search_id: int, found_video_id: str) -> None:
        """
        v4.0.0: DEPRECATED - search_queue table removed.
        Does nothing. Use database.mark_queue_item_completed() instead.
        """
        logger.debug(f"mark_search_complete() called but is DEPRECATED in v4.0.0 - ignoring")

    def mark_search_complete_with_callback(self, search_id: int, found_video_id: str, callback_rating: Optional[str] = None) -> None:
        """
        v4.0.0: DEPRECATED - search_queue table removed.
        Does nothing. Use database.mark_queue_item_completed() + database.enqueue_rating() instead.
        """
        logger.debug(f"mark_search_complete_with_callback() called but is DEPRECATED in v4.0.0 - ignoring")

    def mark_search_failed(self, search_id: int, error: str) -> None:
        """
        v4.0.0: DEPRECATED - search_queue table removed.
        Does nothing. Use database.mark_queue_item_failed() instead.
        """
        logger.debug(f"mark_search_failed() called but is DEPRECATED in v4.0.0 - ignoring")