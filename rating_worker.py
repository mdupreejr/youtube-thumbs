"""
Background worker for processing rating queue.

This module provides a dedicated thread that continuously processes
queued YouTube ratings, ensuring reliable submission without blocking
user-facing operations.
"""
import threading
import time
from typing import Optional
from logger import logger, rating_logger


class RatingWorker:
    """
    Background worker that processes search and rating queues automatically.

    All YouTube API operations go through this worker, which:
    - Processes searches first, then ratings
    - Handles one operation per cycle
    - Uses smart sleep intervals:
      * 1 hour when quota blocked
      * 30 seconds after processing an item
      * 60 seconds when queue is empty
    - Retries failures automatically
    - Runs continuously in background thread
    """

    def __init__(self, db, youtube_api_getter, quota_guard, search_wrapper, poll_interval: int = 60):
        """
        Initialize the rating worker.

        Args:
            db: Database instance
            youtube_api_getter: Function that returns YouTube API instance
            quota_guard: Quota manager instance
            search_wrapper: Function to perform YouTube searches
            poll_interval: Base seconds between checks (overridden by smart sleep)
        """
        self.db = db
        self.youtube_api_getter = youtube_api_getter
        self.quota_guard = quota_guard
        self.search_wrapper = search_wrapper
        self.poll_interval = poll_interval

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        logger.info(f"RatingWorker initialized (base poll interval: {poll_interval}s, smart sleep enabled)")

    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            logger.warning("RatingWorker already running")
            return

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="RatingWorker",
            daemon=True
        )
        self._thread.start()
        logger.info("RatingWorker started")

    def stop(self) -> None:
        """Stop the background worker thread."""
        if not self._running:
            return

        logger.info("Stopping RatingWorker...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._running = False
        logger.info("RatingWorker stopped")

    def is_running(self) -> bool:
        """Check if worker is running."""
        return self._running and self._thread and self._thread.is_alive()

    def _worker_loop(self) -> None:
        """Main worker loop with smart sleep intervals."""
        logger.info("RatingWorker loop started (smart sleep: 1h blocked / 30s processed / 60s empty)")

        while not self._stop_event.is_set():
            try:
                status = self._process_next_item()

                # Smart sleep based on status
                if status == 'blocked':
                    sleep_time = 3600  # 1 hour when quota blocked
                    logger.debug("RatingWorker: Quota blocked, sleeping 1 hour")
                elif status == 'success':
                    sleep_time = 30  # 30 seconds after processing
                    logger.debug("RatingWorker: Item processed, sleeping 30 seconds")
                else:  # 'empty'
                    sleep_time = 60  # 60 seconds when queue empty
                    logger.debug("RatingWorker: Queue empty, sleeping 60 seconds")

            except Exception as e:
                logger.error(f"RatingWorker error in processing loop: {e}")
                sleep_time = 60  # Sleep 60s on error, then retry

            # Sleep in small increments to allow quick shutdown
            for _ in range(sleep_time):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        logger.info("RatingWorker loop exited")

    def _process_next_item(self) -> str:
        """
        Process next batch of items from queues (searches first, then ratings).
        Processes up to 5 searches and 5 ratings per cycle for better throughput.

        Returns:
            'blocked': Quota blocked
            'success': Item(s) processed
            'empty': No items in queue
        """
        # Check quota first - don't waste time querying DB if blocked
        if self.quota_guard.is_blocked():
            return 'blocked'

        items_processed = 0
        BATCH_SIZE = 5

        # Priority 1: Process searches (need video_id before we can rate)
        # Process up to BATCH_SIZE searches per cycle
        for _ in range(BATCH_SIZE):
            # Use atomic claim to prevent race conditions
            search_job = self.db.claim_pending_search()
            if not search_job:
                break  # No more searches

            logger.info(f"RatingWorker: Processing search for '{search_job['ha_title']}'")
            self._process_search(search_job)
            items_processed += 1

            # Small delay between items to avoid hammering API
            time.sleep(2)

        # Priority 2: Process ratings
        # Process up to BATCH_SIZE ratings per cycle
        yt_api = None
        for _ in range(BATCH_SIZE):
            pending_ratings = self.db.list_pending_ratings(limit=1)
            if not pending_ratings:
                break  # No more ratings

            # Get YouTube API instance once (reuse for all ratings in batch)
            if not yt_api:
                try:
                    yt_api = self.youtube_api_getter()
                    if not yt_api:
                        logger.error("RatingWorker: YouTube API not available")
                        break
                except Exception as e:
                    logger.error(f"RatingWorker: Failed to get YouTube API: {e}")
                    break

            logger.info(f"RatingWorker: Processing rating for video {pending_ratings[0]['yt_video_id']}")
            self._process_single_rating(yt_api, pending_ratings[0])
            items_processed += 1

            # Small delay between items
            time.sleep(2)

        # Return status based on what was processed
        if items_processed > 0:
            logger.info(f"RatingWorker: Processed {items_processed} items this cycle")
            return 'success'

        # Nothing to process
        return 'empty'

    def _process_search(self, job) -> None:
        """Process a single search request."""
        search_id = job['id']
        ha_media = {
            'title': job['ha_title'],
            'artist': job['ha_artist'],
            'album': job['ha_album'],
            'content_id': job['ha_content_id'],
            'duration': job['ha_duration'],
            'app_name': job['ha_app_name']
        }

        try:
            # Perform search using wrapper
            video = self.search_wrapper(ha_media)

            if video and video.get('id'):
                # Search succeeded
                video_id = video['id']
                logger.info(f"RatingWorker: Search found video {video_id} for '{job['ha_title']}'")

                # Atomically mark search complete and enqueue callback rating (if present)
                # Both operations in single transaction to prevent data loss on crash
                callback_rating = job.get('callback_rating')
                self.db.mark_search_complete_with_callback(search_id, video_id, callback_rating)

                if callback_rating:
                    logger.info(f"RatingWorker: Enqueued {callback_rating} rating for {video_id}")

            else:
                # Search failed (no results)
                self.db.mark_search_failed(search_id, "No matching video found")
                logger.warning(f"RatingWorker: No video found for '{job['ha_title']}'")

        except Exception as e:
            # Search error
            self.db.mark_search_failed(search_id, str(e))
            logger.error(f"RatingWorker: Search failed for '{job['ha_title']}': {e}")

    def _process_single_rating(self, yt_api, job) -> None:
        """Process a single rating."""
        video_id = job['yt_video_id']
        rating = job['rating']

        logger.debug(f"RatingWorker: Processing single rating {video_id} as {rating}")

        try:
            success = yt_api.set_video_rating(video_id, rating)
            if success:
                self.db.record_rating(video_id, rating)
                self.db.mark_pending_rating(video_id, True)
                rating_logger.info(f"{rating.upper()} | WORKER-SYNCED | video {video_id}")
                logger.debug(f"RatingWorker: Successfully rated {video_id} as {rating}")
            else:
                self.db.mark_pending_rating(video_id, False, "YouTube API returned False")
                logger.warning(f"RatingWorker: YouTube API rejected rating for {video_id}")
        except Exception as e:
            self.db.mark_pending_rating(video_id, False, str(e))
            logger.error(f"RatingWorker: Failed to rate {video_id}: {e}")

    def get_status(self) -> dict:
        """Get worker status for health checks."""
        return {
            'running': self.is_running(),
            'poll_interval': self.poll_interval,
            'thread_alive': self._thread.is_alive() if self._thread else False
        }


# Global rating worker instance (initialized in app.py)
_rating_worker: Optional[RatingWorker] = None


def init_rating_worker(db, youtube_api_getter, quota_guard, search_wrapper, poll_interval: int = 60) -> RatingWorker:
    """
    Initialize the global rating worker.

    Args:
        db: Database instance
        youtube_api_getter: Function that returns YouTube API instance
        quota_guard: Quota manager instance
        search_wrapper: Function to perform YouTube searches
        poll_interval: Base seconds between checks (overridden by smart sleep)

    Returns:
        Initialized RatingWorker instance
    """
    global _rating_worker
    _rating_worker = RatingWorker(db, youtube_api_getter, quota_guard, search_wrapper, poll_interval)
    return _rating_worker


def get_rating_worker() -> Optional[RatingWorker]:
    """Get the global rating worker instance."""
    return _rating_worker
