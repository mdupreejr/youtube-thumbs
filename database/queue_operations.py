"""
Unified queue operations for YouTube API tasks.
All searches and ratings flow through this single queue.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import sqlite3
import threading
import json


class QueueOperations:
    """Handles unified queue operations for searches and ratings."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    # ========================================================================
    # UNIFIED QUEUE OPERATIONS (NEW)
    # ========================================================================

    def enqueue(
        self,
        item_type: str,
        payload: Dict[str, Any],
        priority: int = 2
    ) -> int:
        """
        Add an item to the unified queue.

        Args:
            item_type: 'search' or 'rating'
            payload: Dictionary containing all data needed to process the item
            priority: Lower number = higher priority (ratings=1, searches=2)

        Returns:
            Queue item ID
        """
        if item_type not in ('search', 'rating'):
            raise ValueError(f"Invalid queue item type: {item_type}")

        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO queue (type, priority, status, payload, requested_at)
                VALUES (?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                """,
                (item_type, priority, json.dumps(payload))
            )
            self._conn.commit()
            return cursor.lastrowid

    def claim_next(self) -> Optional[Dict[str, Any]]:
        """
        Atomically claim the next pending queue item.
        Returns highest priority (lowest number) pending item.

        Returns:
            Queue item dict or None if queue is empty
        """
        with self._lock:
            # Get next item ordered by priority (asc), then requested_at (asc)
            cursor = self._conn.execute(
                """
                SELECT * FROM queue
                WHERE status = 'pending'
                ORDER BY priority ASC, requested_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()

            if not row:
                return None

            item = dict(row)

            # Mark as processing (prevents other workers from claiming it)
            self._conn.execute(
                """
                UPDATE queue
                SET status = 'processing',
                    attempts = attempts + 1,
                    last_attempt = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item['id'],)
            )
            self._conn.commit()

            # Parse JSON payload
            item['payload'] = json.loads(item['payload'])
            return item

    def mark_completed(self, queue_id: int) -> None:
        """Mark a queue item as completed."""
        with self._lock:
            self._conn.execute(
                """
                UPDATE queue
                SET status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    last_error = NULL
                WHERE id = ?
                """,
                (queue_id,)
            )
            self._conn.commit()

    def mark_failed(self, queue_id: int, error: str) -> None:
        """
        Mark a queue item as failed and reset to pending for retry.

        Args:
            queue_id: Queue item ID
            error: Error message
        """
        with self._lock:
            self._conn.execute(
                """
                UPDATE queue
                SET status = 'pending',
                    last_error = ?
                WHERE id = ?
                """,
                (error, queue_id)
            )
            self._conn.commit()

    def list_pending(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all pending queue items.

        Args:
            limit: Maximum number of items to return

        Returns:
            List of queue items
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM queue
                WHERE status = 'pending'
                ORDER BY priority ASC, requested_at ASC
                LIMIT ?
                """,
                (limit,)
            )
            items = []
            for row in cursor.fetchall():
                item = dict(row)
                item['payload'] = json.loads(item['payload'])
                items.append(item)
            return items

    def enqueue_search(
        self,
        ha_media: Dict[str, Any],
        callback_rating: Optional[str] = None
    ) -> int:
        """
        Enqueue a search operation (convenience method).

        Args:
            ha_media: Home Assistant media info
            callback_rating: Optional rating to apply after search succeeds

        Returns:
            Queue item ID
        """
        payload = {
            'ha_title': ha_media.get('title'),
            'ha_artist': ha_media.get('artist'),
            'ha_album': ha_media.get('album'),
            'ha_content_id': ha_media.get('content_id'),
            'ha_duration': ha_media.get('duration'),
            'ha_app_name': ha_media.get('app_name'),
            'callback_rating': callback_rating
        }
        return self.enqueue('search', payload, priority=2)

    def enqueue_rating(
        self,
        yt_video_id: str,
        rating: str
    ) -> int:
        """
        Enqueue a rating operation (convenience method).

        Args:
            yt_video_id: YouTube video ID
            rating: 'like' or 'dislike'

        Returns:
            Queue item ID
        """
        payload = {
            'yt_video_id': yt_video_id,
            'rating': rating
        }
        return self.enqueue('rating', payload, priority=1)

    def clear_completed(self, days: int = 7) -> int:
        """
        Clean up completed queue items older than N days.

        Args:
            days: Remove completed items older than this many days

        Returns:
            Number of items deleted
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                DELETE FROM queue
                WHERE status = 'completed'
                  AND completed_at < datetime('now', ? || ' days')
                """,
                (f'-{days}',)
            )
            self._conn.commit()
            return cursor.rowcount

    # ========================================================================
    # LEGACY QUEUE STATISTICS (Will be updated to use unified queue)
    # ========================================================================

    def get_queue_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive queue statistics.

        Returns:
            Dictionary with queue counts, processing rates, and health metrics
        """
        with self._lock:
            stats = {}

            # Rating queue statistics
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_pending,
                    SUM(CASE WHEN rating_queue_attempts = 0 THEN 1 ELSE 0 END) as never_attempted,
                    SUM(CASE WHEN rating_queue_attempts > 0 THEN 1 ELSE 0 END) as retry_pending,
                    MAX(rating_queue_attempts) as max_attempts,
                    AVG(rating_queue_attempts) as avg_attempts
                FROM video_ratings
                WHERE rating_queue_pending IS NOT NULL
            """)
            rating_queue = dict(cursor.fetchone())

            # Search queue statistics
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    MAX(attempts) as max_attempts,
                    AVG(attempts) as avg_attempts
                FROM search_queue
            """)
            search_queue = dict(cursor.fetchone())

            # Recent processing activity (last 24 hours)
            cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')

            # Rating queue processed in last 24h
            cursor = self._conn.execute("""
                SELECT COUNT(*) as count
                FROM video_ratings
                WHERE rating_queue_last_attempt >= ?
            """, (cutoff_24h,))
            ratings_processed_24h = cursor.fetchone()['count']

            # Search queue processed in last 24h
            cursor = self._conn.execute("""
                SELECT COUNT(*) as count
                FROM search_queue
                WHERE last_attempt >= ?
            """, (cutoff_24h,))
            searches_processed_24h = cursor.fetchone()['count']

            # Success rates (last 24h)
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN rating_queue_last_error IS NULL THEN 1 ELSE 0 END) as successful
                FROM video_ratings
                WHERE rating_queue_last_attempt >= ?
                  AND rating_queue_last_attempt IS NOT NULL
            """, (cutoff_24h,))
            row = cursor.fetchone()
            rating_success_rate = 0
            if row['total'] > 0:
                rating_success_rate = (row['successful'] / row['total']) * 100

            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful
                FROM search_queue
                WHERE last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff_24h,))
            row = cursor.fetchone()
            search_success_rate = 0
            if row['total'] > 0:
                search_success_rate = (row['successful'] / row['total']) * 100

            # Get last activity timestamps
            cursor = self._conn.execute("""
                SELECT MAX(rating_queue_last_attempt) as last_rating_attempt
                FROM video_ratings
                WHERE rating_queue_last_attempt IS NOT NULL
            """)
            last_rating = cursor.fetchone()['last_rating_attempt']

            cursor = self._conn.execute("""
                SELECT MAX(last_attempt) as last_search_attempt
                FROM search_queue
                WHERE last_attempt IS NOT NULL
            """)
            last_search = cursor.fetchone()['last_search_attempt']

            return {
                'rating_queue': {
                    'pending': rating_queue['total_pending'] or 0,
                    'never_attempted': rating_queue['never_attempted'] or 0,
                    'retry_pending': rating_queue['retry_pending'] or 0,
                    'max_attempts': rating_queue['max_attempts'] or 0,
                    'avg_attempts': round(rating_queue['avg_attempts'] or 0, 1),
                    'processed_24h': ratings_processed_24h,
                    'success_rate_24h': round(rating_success_rate, 1),
                    'last_activity': last_rating
                },
                'search_queue': {
                    'total': search_queue['total'] or 0,
                    'pending': search_queue['pending'] or 0,
                    'processing': search_queue['processing'] or 0,
                    'completed': search_queue['completed'] or 0,
                    'failed': search_queue['failed'] or 0,
                    'max_attempts': search_queue['max_attempts'] or 0,
                    'avg_attempts': round(search_queue['avg_attempts'] or 0, 1),
                    'processed_24h': searches_processed_24h,
                    'success_rate_24h': round(search_success_rate, 1),
                    'last_activity': last_search
                },
                'worker_health': {
                    'last_rating_activity': last_rating,
                    'last_search_activity': last_search,
                    'is_active': self._is_worker_active(last_rating, last_search)
                }
            }

    def _is_worker_active(self, last_rating: str, last_search: str) -> bool:
        """
        Determine if queue worker is active based on recent activity.

        Worker processes 1 item per minute, so if no activity in 5 minutes
        and there are pending items, worker may be stuck or stopped.
        """
        threshold = datetime.utcnow() - timedelta(minutes=5)
        threshold_str = threshold.strftime('%Y-%m-%d %H:%M:%S')

        last_activity = None
        if last_rating and last_search:
            last_activity = max(last_rating, last_search)
        elif last_rating:
            last_activity = last_rating
        elif last_search:
            last_activity = last_search

        return last_activity >= threshold_str if last_activity else False

    def get_recent_queue_activity(self, limit: int = 50) -> Dict[str, List[Dict]]:
        """
        Get recent queue processing activity.

        Args:
            limit: Maximum number of items to return per queue

        Returns:
            Dictionary with recent rating and search activity
        """
        with self._lock:
            # Recent rating queue activity
            cursor = self._conn.execute("""
                SELECT
                    yt_video_id,
                    ha_title,
                    ha_artist,
                    rating_queue_pending as requested_rating,
                    rating_queue_requested_at as requested_at,
                    rating_queue_attempts as attempts,
                    rating_queue_last_attempt as last_attempt,
                    rating_queue_last_error as error,
                    CASE
                        WHEN rating_queue_last_error IS NULL AND rating_queue_last_attempt IS NOT NULL THEN 'success'
                        WHEN rating_queue_last_error IS NOT NULL THEN 'failed'
                        ELSE 'pending'
                    END as status
                FROM video_ratings
                WHERE rating_queue_requested_at IS NOT NULL
                ORDER BY rating_queue_requested_at DESC
                LIMIT ?
            """, (limit,))
            recent_ratings = [dict(row) for row in cursor.fetchall()]

            # Recent search queue activity
            cursor = self._conn.execute("""
                SELECT
                    id,
                    ha_title,
                    ha_artist,
                    status,
                    requested_at,
                    attempts,
                    last_attempt,
                    error_message,
                    callback_rating,
                    completed_video_id
                FROM search_queue
                ORDER BY requested_at DESC
                LIMIT ?
            """, (limit,))
            recent_searches = [dict(row) for row in cursor.fetchall()]

            return {
                'recent_ratings': recent_ratings,
                'recent_searches': recent_searches
            }

    def get_queue_errors(self, limit: int = 50) -> Dict[str, List[Dict]]:
        """
        Get recent queue errors for troubleshooting.

        Args:
            limit: Maximum number of errors to return per queue

        Returns:
            Dictionary with recent rating and search errors
        """
        with self._lock:
            # Rating queue errors
            cursor = self._conn.execute("""
                SELECT
                    yt_video_id,
                    ha_title,
                    ha_artist,
                    rating_queue_pending as requested_rating,
                    rating_queue_attempts as attempts,
                    rating_queue_last_attempt as last_attempt,
                    rating_queue_last_error as error
                FROM video_ratings
                WHERE rating_queue_last_error IS NOT NULL
                ORDER BY rating_queue_last_attempt DESC
                LIMIT ?
            """, (limit,))
            rating_errors = [dict(row) for row in cursor.fetchall()]

            # Search queue errors
            cursor = self._conn.execute("""
                SELECT
                    id,
                    ha_title,
                    ha_artist,
                    attempts,
                    last_attempt,
                    error_message
                FROM search_queue
                WHERE status = 'failed'
                  AND error_message IS NOT NULL
                ORDER BY last_attempt DESC
                LIMIT ?
            """, (limit,))
            search_errors = [dict(row) for row in cursor.fetchall()]

            return {
                'rating_errors': rating_errors,
                'search_errors': search_errors
            }

    def get_queue_performance_metrics(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get queue performance metrics over time.

        Args:
            hours: Number of hours to analyze

        Returns:
            Dictionary with performance metrics
        """
        with self._lock:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

            # Rating queue performance
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN rating_queue_last_error IS NULL THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN rating_queue_last_error IS NOT NULL THEN 1 ELSE 0 END) as failed,
                    AVG(rating_queue_attempts) as avg_attempts
                FROM video_ratings
                WHERE rating_queue_last_attempt >= ?
            """, (cutoff,))
            rating_metrics = dict(cursor.fetchone())

            # Search queue performance
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(attempts) as avg_attempts
                FROM search_queue
                WHERE last_attempt >= ?
            """, (cutoff,))
            search_metrics = dict(cursor.fetchone())

            return {
                'period_hours': hours,
                'rating_queue': {
                    'total_attempts': rating_metrics['total_attempts'] or 0,
                    'successful': rating_metrics['successful'] or 0,
                    'failed': rating_metrics['failed'] or 0,
                    'avg_attempts': round(rating_metrics['avg_attempts'] or 0, 1),
                    'success_rate': round((rating_metrics['successful'] / rating_metrics['total_attempts'] * 100) if rating_metrics['total_attempts'] > 0 else 0, 1)
                },
                'search_queue': {
                    'total_attempts': search_metrics['total_attempts'] or 0,
                    'successful': search_metrics['successful'] or 0,
                    'failed': search_metrics['failed'] or 0,
                    'avg_attempts': round(search_metrics['avg_attempts'] or 0, 1),
                    'success_rate': round((search_metrics['successful'] / search_metrics['total_attempts'] * 100) if search_metrics['total_attempts'] > 0 else 0, 1)
                }
            }
