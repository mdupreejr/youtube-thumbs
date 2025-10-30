"""
Background thread that periodically checks if YouTube quota is restored during cooldown.
"""
import threading
import time
from typing import Any, Callable

from logger import logger


class QuotaProber:
    """Background worker that probes YouTube API during cooldown to detect quota restoration."""

    def __init__(
        self,
        quota_guard: Any,
        probe_func: Callable[[], bool],
        check_interval: int = 300,  # Check every 5 minutes if probe is needed
        enabled: bool = True,
    ) -> None:
        """
        Initialize quota prober.

        Args:
            quota_guard: QuotaGuard instance
            probe_func: Function that tests if YouTube API is accessible (returns bool)
            check_interval: How often to check if we should probe (seconds)
            enabled: Whether prober is enabled
        """
        self.quota_guard = quota_guard
        self.probe_func = probe_func
        self.check_interval = check_interval
        self.enabled = enabled
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

    def _run(self) -> None:
        """Main loop that periodically checks if we should probe for quota restoration."""
        while not self._stop_event.is_set():
            try:
                # Check if we should probe (QuotaGuard handles timing internally)
                if self.quota_guard.should_probe_for_recovery():
                    logger.info("Quota prober: Time to check if YouTube quota is restored")
                    self.quota_guard.attempt_recovery_probe(self.probe_func)
            except Exception as exc:
                logger.error("Quota prober encountered an error: %s", exc, exc_info=True)

            # Wait before next check
            self._stop_event.wait(self.check_interval)

        logger.info("Quota prober thread exiting")
