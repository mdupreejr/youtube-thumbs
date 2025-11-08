"""
Unified queue operations for YouTube API tasks.
All searches and ratings flow through this single queue.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import sqlite3
import threading
import json
from logger import logger


class QueueOperations:
    """Handles unified queue operations for searches and ratings."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    def _hydrate_queue_item(self, row: sqlite3.Row) -> Dict[str, Any]:
        """
        Convert queue row to dict with parsed payload (DRY helper).
        Centralizes JSON parsing and error handling.

        Args:
            row: SQLite row from queue table

        Returns:
            Dictionary with parsed payload
        """
        item = dict(row)
        try:
            item['payload'] = json.loads(item['payload'])
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Invalid JSON in queue item {item.get('id')}: {e}")
            item['payload'] = {}
        return item

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

            # Parse JSON payload using helper
            item = self._hydrate_queue_item(row)
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
        Mark a queue item as failed.

        v4.0.9: CRITICAL FIX - Changed status to 'failed' (was incorrectly 'pending').
        The old behavior caused quota-exceeded items to retry immediately every 60s,
        burning through the entire daily quota in minutes!

        Failed items should actually be marked as failed, not retried automatically.
        Manual intervention or explicit retry logic is needed for failed items.

        Args:
            queue_id: Queue item ID
            error: Error message
        """
        with self._lock:
            self._conn.execute(
                """
                UPDATE queue
                SET status = 'failed',
                    last_error = ?
                WHERE id = ?
                """,
                (error, queue_id)
            )
            self._conn.commit()

    def reset_stale_processing_items(self) -> int:
        """
        Reset queue items stuck in 'processing' status back to 'pending'.
        This recovers from worker crashes/restarts.

        v4.0.9: Added crash recovery - items stuck in 'processing' will be retried.
        This is safe because all queue operations are idempotent:
        - Ratings: get_video_rating checks current state before changing
        - Searches: duplicate searches just update existing video_ratings entry

        Returns:
            Number of items reset
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE queue
                SET status = 'pending',
                    last_error = 'Reset from processing (worker crash recovery)'
                WHERE status = 'processing'
                """
            )
            self._conn.commit()
            count = cursor.rowcount
            return count

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
                items.append(self._hydrate_queue_item(row))
            return items

    def list_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get completed and failed queue items (history).

        Args:
            limit: Maximum number of items to return

        Returns:
            List of queue items with status 'completed' or 'failed'
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM queue
                WHERE status IN ('completed', 'failed')
                ORDER BY completed_at DESC, last_attempt DESC
                LIMIT ?
                """,
                (limit,)
            )
            items = []
            for row in cursor.fetchall():
                items.append(self._hydrate_queue_item(row))
            return items

    def list_failed(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get failed queue items.

        Args:
            limit: Maximum number of items to return

        Returns:
            List of failed queue items
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM queue
                WHERE status = 'failed'
                ORDER BY last_attempt DESC
                LIMIT ?
                """,
                (limit,)
            )
            items = []
            for row in cursor.fetchall():
                items.append(self._hydrate_queue_item(row))
            return items

    def get_item_by_id(self, queue_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific queue item by ID.

        Args:
            queue_id: Queue item ID

        Returns:
            Queue item dict or None if not found
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT * FROM queue WHERE id = ?
                """,
                (queue_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._hydrate_queue_item(row)
            return None

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
    # UNIFIED QUEUE STATISTICS
    # ========================================================================

    def get_queue_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive queue statistics from the unified queue.

        Returns:
            Dictionary with queue counts, processing rates, and health metrics
        """
        with self._lock:
            stats = {}

            # Overall queue statistics
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    MAX(attempts) as max_attempts,
                    AVG(attempts) as avg_attempts
                FROM queue
            """)
            overall_queue = dict(cursor.fetchone())

            # Rating queue statistics
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_pending,
                    SUM(CASE WHEN attempts = 0 THEN 1 ELSE 0 END) as never_attempted,
                    SUM(CASE WHEN attempts > 0 THEN 1 ELSE 0 END) as retry_pending,
                    MAX(attempts) as max_attempts,
                    AVG(attempts) as avg_attempts
                FROM queue
                WHERE type = 'rating' AND status = 'pending'
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
                FROM queue
                WHERE type = 'search'
            """)
            search_queue = dict(cursor.fetchone())

            # Recent processing activity (last 24 hours)
            cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')

            # Rating queue processed in last 24h
            cursor = self._conn.execute("""
                SELECT COUNT(*) as count
                FROM queue
                WHERE type = 'rating' 
                  AND last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff_24h,))
            ratings_processed_24h = cursor.fetchone()['count']

            # Search queue processed in last 24h
            cursor = self._conn.execute("""
                SELECT COUNT(*) as count
                FROM queue
                WHERE type = 'search'
                  AND last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff_24h,))
            searches_processed_24h = cursor.fetchone()['count']

            # Success rates (last 24h)
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful
                FROM queue
                WHERE type = 'rating'
                  AND last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff_24h,))
            row = cursor.fetchone()
            rating_success_rate = 0
            if row['total'] > 0:
                rating_success_rate = (row['successful'] / row['total']) * 100

            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful
                FROM queue
                WHERE type = 'search'
                  AND last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff_24h,))
            row = cursor.fetchone()
            search_success_rate = 0
            if row['total'] > 0:
                search_success_rate = (row['successful'] / row['total']) * 100

            # Get last activity timestamps
            cursor = self._conn.execute("""
                SELECT MAX(last_attempt) as last_rating_attempt
                FROM queue
                WHERE type = 'rating' AND last_attempt IS NOT NULL
            """)
            last_rating = cursor.fetchone()['last_rating_attempt']

            cursor = self._conn.execute("""
                SELECT MAX(last_attempt) as last_search_attempt
                FROM queue
                WHERE type = 'search' AND last_attempt IS NOT NULL
            """)
            last_search = cursor.fetchone()['last_search_attempt']

            return {
                'overall_queue': {
                    'total': overall_queue['total'] or 0,
                    'pending': overall_queue['pending'] or 0,
                    'processing': overall_queue['processing'] or 0,
                    'completed': overall_queue['completed'] or 0,
                    'failed': overall_queue['failed'] or 0,
                    'max_attempts': overall_queue['max_attempts'] or 0,
                    'avg_attempts': round(overall_queue['avg_attempts'] or 0, 1)
                },
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
        OPTIMIZED: Uses LEFT JOIN to avoid N+1 query problem.

        Args:
            limit: Maximum number of items to return per queue

        Returns:
            Dictionary with recent rating and search activity
        """
        with self._lock:
            # Recent rating queue activity - OPTIMIZED with LEFT JOIN (1 query instead of N+1)
            cursor = self._conn.execute("""
                SELECT
                    q.*,
                    v.ha_title AS video_ha_title,
                    v.ha_artist AS video_ha_artist
                FROM queue q
                LEFT JOIN video_ratings v ON json_extract(q.payload, '$.yt_video_id') = v.yt_video_id
                WHERE q.type = 'rating'
                ORDER BY q.requested_at DESC
                LIMIT ?
            """, (limit,))

            recent_ratings = []
            for row in cursor.fetchall():
                item = dict(row)
                payload = json.loads(item['payload'])

                recent_ratings.append({
                    'yt_video_id': payload.get('yt_video_id'),
                    'ha_title': item.get('video_ha_title') or 'Unknown',
                    'ha_artist': item.get('video_ha_artist') or 'Unknown',
                    'requested_rating': payload.get('rating'),
                    'requested_at': item['requested_at'],
                    'attempts': item['attempts'],
                    'last_attempt': item['last_attempt'],
                    'error': item['last_error'],
                    'status': item['status'],
                    'queue_id': item['id']
                })

            # Recent search queue activity - use helper for JSON parsing
            cursor = self._conn.execute("""
                SELECT *
                FROM queue
                WHERE type = 'search'
                ORDER BY requested_at DESC
                LIMIT ?
            """, (limit,))

            recent_searches = []
            for row in cursor.fetchall():
                item = self._hydrate_queue_item(row)
                payload = item['payload']

                recent_searches.append({
                    'id': item['id'],
                    'ha_title': payload.get('ha_title', 'Unknown'),
                    'ha_artist': payload.get('ha_artist', 'Unknown'),
                    'status': item['status'],
                    'requested_at': item['requested_at'],
                    'attempts': item['attempts'],
                    'last_attempt': item['last_attempt'],
                    'error_message': item['last_error'],
                    'callback_rating': payload.get('callback_rating'),
                    'completed_video_id': None  # Would need additional lookup
                })

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
            # Rating queue errors - OPTIMIZED with LEFT JOIN to avoid N+1 query
            cursor = self._conn.execute("""
                SELECT
                    q.*,
                    v.ha_title AS video_ha_title,
                    v.ha_artist AS video_ha_artist
                FROM queue q
                LEFT JOIN video_ratings v ON json_extract(q.payload, '$.yt_video_id') = v.yt_video_id
                WHERE q.type = 'rating'
                  AND q.status = 'failed'
                  AND q.last_error IS NOT NULL
                ORDER BY q.last_attempt DESC
                LIMIT ?
            """, (limit,))
            rating_errors = []
            for row in cursor.fetchall():
                item = dict(row)
                payload = json.loads(item['payload'])

                rating_errors.append({
                    'yt_video_id': payload.get('yt_video_id'),
                    'ha_title': item.get('video_ha_title') or 'Unknown',
                    'ha_artist': item.get('video_ha_artist') or 'Unknown',
                    'requested_rating': payload.get('rating'),
                    'attempts': item['attempts'],
                    'last_attempt': item['last_attempt'],
                    'error': item['last_error'],
                    'queue_id': item['id']
                })

            # Search queue errors - use helper for JSON parsing
            cursor = self._conn.execute("""
                SELECT *
                FROM queue
                WHERE type = 'search'
                  AND status = 'failed'
                  AND last_error IS NOT NULL
                ORDER BY last_attempt DESC
                LIMIT ?
            """, (limit,))
            search_errors = []
            for row in cursor.fetchall():
                item = self._hydrate_queue_item(row)
                payload = item['payload']

                search_errors.append({
                    'id': item['id'],
                    'ha_title': payload.get('ha_title', 'Unknown'),
                    'ha_artist': payload.get('ha_artist', 'Unknown'),
                    'attempts': item['attempts'],
                    'last_attempt': item['last_attempt'],
                    'error_message': item['last_error'],
                    'queue_id': item['id']
                })

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

            # Rating queue performance from unified queue
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(attempts) as avg_attempts
                FROM queue
                WHERE type = 'rating'
                  AND last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff,))
            rating_metrics = dict(cursor.fetchone())

            # Search queue performance from unified queue
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(attempts) as avg_attempts
                FROM queue
                WHERE type = 'search'
                  AND last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff,))
            search_metrics = dict(cursor.fetchone())

            # Overall queue metrics
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    AVG(attempts) as avg_attempts
                FROM queue
                WHERE last_attempt >= ?
                  AND last_attempt IS NOT NULL
            """, (cutoff,))
            overall_metrics = dict(cursor.fetchone())

            return {
                'period_hours': hours,
                'overall': {
                    'total_attempts': overall_metrics['total_attempts'] or 0,
                    'successful': overall_metrics['successful'] or 0,
                    'failed': overall_metrics['failed'] or 0,
                    'avg_attempts': round(overall_metrics['avg_attempts'] or 0, 1),
                    'success_rate': round((overall_metrics['successful'] / overall_metrics['total_attempts'] * 100) if overall_metrics['total_attempts'] > 0 else 0, 1)
                },
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
