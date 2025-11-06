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
    Background worker that processes the rating queue automatically.

    All YouTube rating submissions go through this worker, which:
    - Checks quota availability
    - Processes ratings in batch (up to 20 at a time)
    - Retries failures automatically
    - Runs continuously in background thread
    """

    def __init__(self, db, youtube_api_getter, quota_guard, poll_interval: int = 3600):
        """
        Initialize the rating worker.

        Args:
            db: Database instance
            youtube_api_getter: Function that returns YouTube API instance
            quota_guard: Quota manager instance
            poll_interval: Seconds between queue checks (default: 3600 = 1 hour)
        """
        self.db = db
        self.youtube_api_getter = youtube_api_getter
        self.quota_guard = quota_guard
        self.poll_interval = poll_interval

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        logger.info(f"RatingWorker initialized (poll interval: {poll_interval}s)")

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
        """Main worker loop that runs continuously."""
        logger.info("RatingWorker loop started")

        while not self._stop_event.is_set():
            try:
                self._process_queue_batch()
            except Exception as e:
                logger.error(f"RatingWorker error in processing loop: {e}")
                # Continue running despite errors

            # Sleep in small increments to allow quick shutdown
            for _ in range(self.poll_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        logger.info("RatingWorker loop exited")

    def _process_queue_batch(self) -> None:
        """Process a batch of pending ratings from the queue."""
        # Check quota first - don't waste time querying DB if blocked
        if self.quota_guard.is_blocked():
            logger.debug("RatingWorker: Quota blocked, skipping queue processing")
            return

        # Get pending ratings from queue
        pending_jobs = self.db.list_pending_ratings(limit=20)
        if not pending_jobs:
            logger.debug("RatingWorker: No pending ratings in queue")
            return

        logger.info(f"RatingWorker: Processing {len(pending_jobs)} pending ratings")

        # Get YouTube API instance
        try:
            yt_api = self.youtube_api_getter()
            if not yt_api:
                logger.error("RatingWorker: YouTube API not available")
                return
        except Exception as e:
            logger.error(f"RatingWorker: Failed to get YouTube API: {e}")
            return

        # Process ratings in batch if multiple, single if one
        if len(pending_jobs) > 1:
            self._process_batch_ratings(yt_api, pending_jobs)
        else:
            self._process_single_rating(yt_api, pending_jobs[0])

    def _process_batch_ratings(self, yt_api, pending_jobs) -> None:
        """Process multiple ratings using batch API."""
        logger.info(f"RatingWorker: Batch processing {len(pending_jobs)} ratings")

        # Prepare batch: list of (video_id, rating) tuples
        ratings_to_process = [
            (job['yt_video_id'], job['rating'])
            for job in pending_jobs
        ]

        try:
            # Call batch API
            results = yt_api.batch_set_ratings(ratings_to_process)

            # Update database based on results
            for video_id, rating in ratings_to_process:
                success = results.get(video_id, False)
                if success:
                    self.db.record_rating(video_id, rating)
                    self.db.mark_pending_rating(video_id, True)
                    rating_logger.info(f"{rating.upper()} | WORKER-SYNCED | video {video_id}")
                    logger.debug(f"RatingWorker: Successfully rated {video_id} as {rating}")
                else:
                    self.db.mark_pending_rating(video_id, False, "Batch rating failed")
                    logger.warning(f"RatingWorker: Failed to rate {video_id}")

        except Exception as e:
            logger.error(f"RatingWorker: Batch processing failed: {e}")
            # Mark all as failed
            for job in pending_jobs:
                self.db.mark_pending_rating(job['yt_video_id'], False, str(e))

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


def init_rating_worker(db, youtube_api_getter, quota_guard, poll_interval: int = 60) -> RatingWorker:
    """
    Initialize the global rating worker.

    Args:
        db: Database instance
        youtube_api_getter: Function that returns YouTube API instance
        quota_guard: Quota manager instance
        poll_interval: Seconds between queue checks

    Returns:
        Initialized RatingWorker instance
    """
    global _rating_worker
    _rating_worker = RatingWorker(db, youtube_api_getter, quota_guard, poll_interval)
    return _rating_worker


def get_rating_worker() -> Optional[RatingWorker]:
    """Get the global rating worker instance."""
    return _rating_worker
