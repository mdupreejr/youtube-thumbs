"""
Background task to periodically refresh statistics cache.
Ensures stats_cache table is populated with fresh data.
"""
import threading
import time
from datetime import datetime
from logger import logger


class StatsRefresher:
    """Periodically refreshes statistics cache in background."""

    def __init__(self, db, interval_seconds=3600):
        """
        Initialize stats refresher.

        Args:
            db: Database instance
            interval_seconds: How often to refresh stats (default: 1 hour)
        """
        self.db = db
        self.interval_seconds = interval_seconds
        self._thread = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self):
        """Start the background stats refresh thread."""
        if self._running:
            logger.warning("Stats refresher already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()
        logger.info(f"Stats refresher started (interval: {self.interval_seconds}s)")

    def stop(self):
        """Stop the background stats refresh thread."""
        if not self._running:
            return

        logger.info("Stopping stats refresher...")
        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        logger.info("Stats refresher stopped")

    def _refresh_loop(self):
        """Main loop that periodically refreshes stats."""
        # Do initial refresh immediately
        self._refresh_all_stats()

        while self._running:
            # Wait for interval or stop event
            if self._stop_event.wait(timeout=self.interval_seconds):
                break

            if self._running:
                self._refresh_all_stats()

    def _refresh_all_stats(self):
        """Refresh all statistics and store in cache."""
        try:
            logger.info("Refreshing statistics cache...")
            start_time = time.time()

            # Get all stats (these will be cached by the database layer)
            stats_to_refresh = [
                ('stats_summary', lambda: self.db.get_stats_summary(), 300),  # 5 min TTL
                ('most_played_10', lambda: self.db.get_most_played(10), 600),  # 10 min TTL
                ('top_channels_10', lambda: self.db.get_top_channels(10), 600),
                ('rating_distribution', lambda: self.db.get_ratings_breakdown(), 300),
                ('top_rated_10', lambda: self.db.get_top_rated(10), 600),
                ('recent_activity_20', lambda: self.db.get_recent_activity(20), 60),  # 1 min TTL
                ('category_breakdown', lambda: self.db.get_category_breakdown(), 3600),  # 1 hour TTL
                ('api_usage_7d', lambda: self.db.get_api_usage_stats(7), 3600),
            ]

            refreshed_count = 0
            for cache_key, stats_func, ttl in stats_to_refresh:
                try:
                    data = stats_func()
                    if data is not None:
                        self.db.set_cached_stats(cache_key, data, ttl_seconds=ttl)
                        refreshed_count += 1
                except Exception as e:
                    logger.error(f"Failed to refresh stat '{cache_key}': {e}")

            elapsed = time.time() - start_time
            logger.info(f"Statistics cache refreshed: {refreshed_count} stats in {elapsed:.2f}s")

        except Exception as e:
            logger.error(f"Error in stats refresh loop: {e}")
