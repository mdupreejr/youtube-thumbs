"""
Background worker for processing rating queue.

This module provides a dedicated thread that continuously processes
queued YouTube ratings, ensuring reliable submission without blocking
user-facing operations.
"""
import threading
import time
from typing import Optional, Tuple
from logger import logger, rating_logger


class RatingWorker:
    """
    Background worker that processes search and rating queues automatically.

    All YouTube API operations go through this worker, which:
    - Processes ratings first (lightweight), then searches (heavier quota usage)
    - Batch processing: up to 5 ratings + 5 searches per cycle
    - Uses smart sleep intervals:
      * 1 hour when quota blocked
      * 30 seconds after processing an item
      * 60 seconds when queue is empty
    - Retries failures automatically
    - Runs continuously in background thread
    - Includes health monitoring and auto-restart:
      * Checks health every 5 minutes
      * Monitors thread liveness and heartbeat
      * Auto-restarts if worker becomes unresponsive
      * Heartbeat timeout: 2 hours (allows for quota blocked sleep)
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
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        # Health check tracking
        self._last_heartbeat = time.time()
        self._last_activity = time.time()
        self._health_check_interval = 300  # Check every 5 minutes
        self._heartbeat_timeout = 7200  # 2 hours (allows for quota blocked sleep)
        self._lock = threading.Lock()

        logger.info(f"RatingWorker initialized (base poll interval: {poll_interval}s, smart sleep enabled)")

    def start(self) -> None:
        """Start the background worker thread and health monitor."""
        if self._running:
            logger.warning("RatingWorker already running")
            return

        self._stop_event.clear()
        self._running = True

        # Start worker thread
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="RatingWorker",
            daemon=True
        )
        self._thread.start()

        # Start health monitor thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="RatingWorkerMonitor",
            daemon=True
        )
        self._monitor_thread.start()

        logger.info("RatingWorker and health monitor started")

    def stop(self) -> None:
        """Stop the background worker thread and health monitor."""
        if not self._running:
            return

        logger.info("Stopping RatingWorker and health monitor...")
        self._stop_event.set()

        # Stop worker thread
        if self._thread:
            self._thread.join(timeout=5)

        # Stop monitor thread
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)

        self._running = False
        logger.info("RatingWorker and health monitor stopped")

    def is_running(self) -> bool:
        """Check if worker is running."""
        return self._running and self._thread and self._thread.is_alive()

    def _worker_loop(self) -> None:
        """Main worker loop with smart sleep intervals."""
        logger.info("RatingWorker loop started (smart sleep: 1h blocked / 30s processed / 60s empty)")

        while not self._stop_event.is_set():
            try:
                # Update heartbeat at start of each cycle
                with self._lock:
                    self._last_heartbeat = time.time()

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
        Process next batch of items from queues (ratings first, then searches).
        Ratings are lightweight, searches use more quota, so prioritize ratings.
        Processes up to 5 ratings and 5 searches per cycle for better throughput.

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

        # Priority 1: Process ratings (lightweight API calls)
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

        # Priority 2: Process searches (heavier API calls, only after ratings done)
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

        # Return status based on what was processed
        if items_processed > 0:
            # Update activity timestamp when items are processed
            with self._lock:
                self._last_activity = time.time()
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

    def _monitor_loop(self) -> None:
        """Monitor worker health and auto-restart if needed."""
        logger.info(f"RatingWorker health monitor started (check interval: {self._health_check_interval}s)")

        while not self._stop_event.is_set():
            try:
                # Wait for health check interval
                time.sleep(self._health_check_interval)

                # Skip if stopping
                if self._stop_event.is_set():
                    break

                # Check worker health
                is_healthy, reason = self._check_health()

                if not is_healthy:
                    logger.error(f"RatingWorker health check failed: {reason}")
                    self._restart_worker()
                else:
                    logger.debug("RatingWorker health check passed")

            except Exception as e:
                logger.error(f"Error in RatingWorker health monitor: {e}")
                time.sleep(60)  # Sleep on error before retry

        logger.info("RatingWorker health monitor exited")

    def _check_health(self) -> Tuple[bool, str]:
        """
        Check if worker is healthy.

        Returns:
            (is_healthy: bool, reason: str)
        """
        # Check if worker thread is alive
        if not self._thread or not self._thread.is_alive():
            return False, "Worker thread is not alive"

        # Check if heartbeat is recent (within timeout)
        with self._lock:
            time_since_heartbeat = time.time() - self._last_heartbeat

        if time_since_heartbeat > self._heartbeat_timeout:
            return False, f"No heartbeat for {int(time_since_heartbeat)}s (timeout: {self._heartbeat_timeout}s)"

        return True, "OK"

    def _restart_worker(self) -> None:
        """Restart the worker thread after failure."""
        logger.warning("Attempting to restart RatingWorker...")

        try:
            # Stop the old worker thread (but not the monitor)
            if self._thread:
                self._stop_event.set()
                self._thread.join(timeout=5)

            # Clear stop event and restart
            self._stop_event.clear()

            # Reset timestamps
            with self._lock:
                self._last_heartbeat = time.time()
                self._last_activity = time.time()

            # Create new worker thread
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="RatingWorker",
                daemon=True
            )
            self._thread.start()

            logger.info("RatingWorker successfully restarted")

        except Exception as e:
            logger.error(f"Failed to restart RatingWorker: {e}")

    def get_status(self) -> dict:
        """Get worker status for health checks."""
        with self._lock:
            last_heartbeat = self._last_heartbeat
            last_activity = self._last_activity

        current_time = time.time()
        is_healthy, health_reason = self._check_health()

        return {
            'running': self.is_running(),
            'poll_interval': self.poll_interval,
            'thread_alive': self._thread.is_alive() if self._thread else False,
            'monitor_alive': self._monitor_thread.is_alive() if self._monitor_thread else False,
            'healthy': is_healthy,
            'health_reason': health_reason,
            'seconds_since_heartbeat': int(current_time - last_heartbeat),
            'seconds_since_activity': int(current_time - last_activity),
            'heartbeat_timeout': self._heartbeat_timeout
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
