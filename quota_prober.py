"""
Background thread that periodically checks if YouTube quota is restored during cooldown.
"""
import threading
import time
from typing import Any, Callable, Optional, Dict

from logger import logger


class QuotaProber:
    """Background worker that probes YouTube API during cooldown to detect quota restoration."""

    def __init__(
        self,
        quota_guard: Any,
        probe_func: Callable[[], bool],
        check_interval: int = 300,  # Check every 5 minutes if probe is needed
        enabled: bool = True,
        db: Optional[Any] = None,
        search_wrapper: Optional[Callable] = None,
        retry_enabled: bool = True,
        retry_batch_size: int = 50,
        metrics_tracker: Optional[Any] = None,
    ) -> None:
        """
        Initialize quota prober.

        Args:
            quota_guard: QuotaGuard instance
            probe_func: Function that tests if YouTube API is accessible (returns bool)
            check_interval: How often to check if we should probe (seconds)
            enabled: Whether prober is enabled
            db: Database instance for pending video retry (v1.51.0)
            search_wrapper: Function to search YouTube for pending videos (v1.51.0)
            retry_enabled: Whether to retry pending videos after quota recovery (v1.51.0)
            retry_batch_size: Max pending videos to retry per recovery (v1.51.0)
            metrics_tracker: MetricsTracker instance for recording stats (v1.51.0)
        """
        self.quota_guard = quota_guard
        self.probe_func = probe_func
        self.check_interval = check_interval
        self.enabled = enabled
        self.db = db
        self.search_wrapper = search_wrapper
        self.retry_enabled = retry_enabled
        self.retry_batch_size = retry_batch_size
        self.metrics_tracker = metrics_tracker
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="quota-prober", daemon=True)

    def start(self) -> None:
        """Start the quota prober thread."""
        if not self.enabled:
            logger.info("Quota prober disabled via configuration")
            return

        if self._thread.is_alive():
            logger.debug("Quota prober thread already running")
            return

        # If thread died, create a new one
        if self._thread.ident is not None:
            logger.warning("Quota prober thread died, creating new thread")
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="quota-prober", daemon=True)

        logger.info("Starting quota prober thread (check interval: %ss)", self.check_interval)
        self._thread.start()

    def stop(self) -> None:
        """Stop the quota prober thread."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Quota prober stopped")

    def is_healthy(self) -> bool:
        """Check if the quota prober thread is healthy."""
        if not self.enabled:
            return True
        return self._thread.is_alive()

    def ensure_running(self) -> None:
        """Ensure the quota prober is running, restart if needed."""
        if not self.enabled:
            return
        if not self.is_healthy():
            logger.warning("Quota prober thread not healthy, attempting restart")
            self.start()

    def _retry_pending_videos(self) -> None:
        """
        v1.51.0: Retry pending videos that failed due to quota exhaustion.
        Called automatically after successful quota recovery probe.
        """
        if not self.retry_enabled:
            logger.debug("Pending video retry disabled via configuration")
            return

        if not self.db or not self.search_wrapper:
            logger.warning("Pending video retry enabled but db or search_wrapper not provided")
            return

        try:
            # Get pending videos that failed due to quota (1 at a time for safety)
            pending = self.db.get_pending_videos(
                limit=1,
                reason_filter='quota_exceeded'
            )

            if not pending:
                logger.info("No pending videos to retry after quota recovery")
                return

            estimated_minutes = (len(pending) - 1) * 60 / 60  # 60 seconds between each, except first
            logger.info("Found %d pending video(s) to retry after quota recovery (estimated time: %.1f minutes)",
                       len(pending), estimated_minutes)

            success_count = 0
            not_found_count = 0
            error_count = 0

            for idx, video in enumerate(pending):
                # Rate limit: Add 60 second delay between retries (except first one)
                if idx > 0:
                    logger.info("Waiting 60 seconds before next retry to avoid quota exhaustion...")
                    time.sleep(60)

                ha_content_id = video.get('ha_content_id')
                ha_title = video.get('ha_title', 'Unknown')
                ha_duration = video.get('ha_duration')
                ha_artist = video.get('ha_artist')

                try:
                    logger.info("Retrying match for: %s (duration: %s) [%d/%d]", ha_title[:50], ha_duration, idx + 1, len(pending))

                    # Search YouTube for this video
                    result = self.search_wrapper(ha_title, ha_duration, ha_artist)

                    if result:
                        # Found a match - resolve the pending video
                        youtube_data = {
                            'yt_video_id': result.get('yt_video_id'),
                            'title': result.get('title'),
                            'channel': result.get('channel'),
                            'channel_id': result.get('channel_id'),
                            'description': result.get('description'),
                            'published_at': result.get('published_at'),
                            'category_id': result.get('category_id'),
                            'live_broadcast': result.get('live_broadcast'),
                            'location': result.get('location'),
                            'recording_date': result.get('recording_date'),
                            'duration': result.get('duration'),
                            'url': result.get('url'),
                        }
                        self.db.resolve_pending_video(ha_content_id, youtube_data)
                        logger.info("✓ Successfully matched: %s → %s", ha_title[:50], result.get('yt_video_id'))
                        success_count += 1
                    else:
                        # No match found - mark as not found
                        self.db.mark_pending_not_found(ha_content_id)
                        # Also add to not_found cache to prevent future searches
                        self.db.record_not_found(ha_title, ha_artist, ha_duration, search_query=ha_title)
                        logger.info("✗ No match found for: %s", ha_title[:50])
                        not_found_count += 1

                except Exception as exc:
                    logger.error("Failed to retry pending video %s: %s", ha_content_id, exc)
                    error_count += 1

            logger.info(
                "Pending video retry complete: %d matched, %d not found, %d errors",
                success_count, not_found_count, error_count
            )

            # Record metrics
            if self.metrics_tracker:
                self.metrics_tracker.record_pending_retry(
                    total=len(pending),
                    matched=success_count,
                    not_found=not_found_count,
                    errors=error_count
                )

        except Exception as exc:
            logger.error("Failed to retry pending videos: %s", exc, exc_info=True)

    def _run(self) -> None:
        """Main loop that periodically checks if we should probe for quota restoration."""
        while not self._stop_event.is_set():
            try:
                # Check if we should probe (QuotaGuard handles timing internally)
                if self.quota_guard.should_probe_for_recovery():
                    logger.info("Quota prober: Time to check if YouTube quota is restored")
                    quota_restored = self.quota_guard.attempt_recovery_probe(self.probe_func)

                    if quota_restored:
                        logger.info("Quota restored! Starting automatic retry of pending videos...")
                        self._retry_pending_videos()

            except Exception as exc:
                logger.error("Quota prober encountered an error: %s", exc, exc_info=True)

            # Wait before next check
            self._stop_event.wait(self.check_interval)

        logger.info("Quota prober thread exiting")
