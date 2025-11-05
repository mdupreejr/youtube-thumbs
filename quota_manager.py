"""
Centralized YouTube API Quota Manager

Single process that manages all YouTube API calls and quota status.
- All API requests go through this manager
- Checks hourly for quota restoration (not 12-hour blind cooldown)
- Automatically resumes processing when quota available
- Better user feedback and control
"""

import time
import threading
from datetime import datetime, timezone
from typing import Optional, Callable, Any, Tuple
from logger import logger


class QuotaManager:
    """
    Centralized manager for all YouTube API calls with intelligent quota handling.

    Features:
    - Single point of control for all API requests
    - Hourly quota restoration checks
    - Automatic resume when quota available
    - Queue management for pending operations
    """

    def __init__(self, check_interval_seconds: int = 3600):
        """
        Initialize the quota manager.

        Args:
            check_interval_seconds: How often to check for quota restoration (default: 3600 = 1 hour)
        """
        self._lock = threading.Lock()
        self._quota_exceeded = False
        self._quota_exceeded_at: Optional[datetime] = None
        self._last_check_time: Optional[datetime] = None
        self._check_interval = check_interval_seconds

        # Statistics
        self._total_calls = 0
        self._blocked_calls = 0
        self._successful_calls = 0
        self._failed_calls = 0

        # Background checker thread
        self._checker_thread: Optional[threading.Thread] = None
        self._stop_checker = threading.Event()

        logger.info(f"QuotaManager initialized with {check_interval_seconds}s check interval")

    def start_checker(self, youtube_api_instance):
        """
        Start the background thread that checks for quota restoration.

        Args:
            youtube_api_instance: The YouTube API instance to use for test calls
        """
        if self._checker_thread and self._checker_thread.is_alive():
            logger.warning("Quota checker thread already running")
            return

        self._stop_checker.clear()
        self._checker_thread = threading.Thread(
            target=self._quota_check_loop,
            args=(youtube_api_instance,),
            daemon=True,
            name="QuotaChecker"
        )
        self._checker_thread.start()
        logger.info("Quota checker thread started")

    def stop_checker(self):
        """Stop the background quota checker thread."""
        if self._checker_thread and self._checker_thread.is_alive():
            logger.info("Stopping quota checker thread...")
            self._stop_checker.set()
            self._checker_thread.join(timeout=5)
            logger.info("Quota checker thread stopped")

    def _quota_check_loop(self, youtube_api):
        """
        Background loop that periodically checks if quota is restored.

        Args:
            youtube_api: YouTube API instance for making test calls
        """
        while not self._stop_checker.is_set():
            try:
                # Only check if we're currently in quota exceeded state
                if self._quota_exceeded:
                    now = datetime.now(timezone.utc)

                    # Check if it's time for another check
                    if self._last_check_time is None or \
                       (now - self._last_check_time).total_seconds() >= self._check_interval:

                        logger.info("Quota checker: Testing if YouTube quota is restored...")
                        self._last_check_time = now

                        # Try a minimal API call to test quota
                        if self._test_quota_restored(youtube_api):
                            logger.info("✅ Quota restored! Resuming API operations")
                            with self._lock:
                                self._quota_exceeded = False
                                self._quota_exceeded_at = None
                        else:
                            logger.info(f"❌ Quota still exceeded. Will retry in {self._check_interval}s")

                # Sleep for a short time before next iteration
                self._stop_checker.wait(timeout=60)  # Check every minute if we should stop

            except Exception as e:
                logger.error(f"Error in quota check loop: {e}")
                self._stop_checker.wait(timeout=300)  # Wait 5 minutes on error

    def _test_quota_restored(self, youtube_api) -> bool:
        """
        Test if quota is restored by making a minimal API call.

        Args:
            youtube_api: YouTube API instance

        Returns:
            True if quota is available, False if still exceeded
        """
        try:
            # Try a minimal quota cost operation (1 unit)
            # Use videos().list() with a known video ID
            request = youtube_api.youtube.videos().list(
                part='id',
                id='dQw4w9WgXcQ',  # Rick Astley - known to exist
                maxResults=1
            )
            request.execute()

            # If we got here, quota is available
            logger.info("Test API call succeeded - quota is available")
            return True

        except Exception as e:
            error_str = str(e).lower()

            # Check if it's still a quota error
            if 'quota' in error_str or 'exceeded' in error_str:
                logger.info("Test API call failed - quota still exceeded")
                return False

            # Some other error - assume quota is available but something else is wrong
            logger.warning(f"Test API call failed with non-quota error: {e}")
            return True  # Don't block on non-quota errors

    def mark_quota_exceeded(self):
        """Mark that quota has been exceeded."""
        with self._lock:
            if not self._quota_exceeded:
                self._quota_exceeded = True
                self._quota_exceeded_at = datetime.now(timezone.utc)
                logger.warning(f"⚠️  YouTube quota exceeded at {self._quota_exceeded_at}")

    def is_quota_exceeded(self) -> bool:
        """Check if quota is currently exceeded."""
        with self._lock:
            return self._quota_exceeded

    def get_status(self) -> dict:
        """Get current quota status."""
        with self._lock:
            now = datetime.now(timezone.utc)

            status = {
                'quota_exceeded': self._quota_exceeded,
                'total_calls': self._total_calls,
                'blocked_calls': self._blocked_calls,
                'successful_calls': self._successful_calls,
                'failed_calls': self._failed_calls,
            }

            if self._quota_exceeded and self._quota_exceeded_at:
                elapsed = (now - self._quota_exceeded_at).total_seconds()
                status['exceeded_at'] = self._quota_exceeded_at.isoformat()
                status['elapsed_seconds'] = int(elapsed)
                status['next_check_in'] = self._get_next_check_seconds()

            return status

    def _get_next_check_seconds(self) -> int:
        """Get seconds until next quota check."""
        if not self._last_check_time:
            return 0

        now = datetime.now(timezone.utc)
        elapsed = (now - self._last_check_time).total_seconds()
        remaining = max(0, self._check_interval - elapsed)
        return int(remaining)

    def execute_api_call(
        self,
        operation_name: str,
        api_function: Callable,
        *args,
        **kwargs
    ) -> Tuple[bool, Any]:
        """
        Execute a YouTube API call through the quota manager.

        Args:
            operation_name: Name of the operation (for logging)
            api_function: The API function to call
            *args, **kwargs: Arguments to pass to the API function

        Returns:
            Tuple of (success: bool, result: Any)
            - (True, result) if call succeeded
            - (False, None) if quota exceeded
            - (False, error) if call failed for other reason
        """
        with self._lock:
            self._total_calls += 1

        # Check if quota is exceeded
        if self.is_quota_exceeded():
            with self._lock:
                self._blocked_calls += 1
            logger.info(f"Quota exceeded; skipping {operation_name}")
            return (False, None)

        # Execute the API call
        try:
            result = api_function(*args, **kwargs)
            with self._lock:
                self._successful_calls += 1
            return (True, result)

        except Exception as e:
            with self._lock:
                self._failed_calls += 1

            error_str = str(e).lower()

            # Check if it's a quota error
            if 'quota' in error_str or 'exceeded' in error_str:
                logger.error(f"Quota exceeded during {operation_name}: {e}")
                self.mark_quota_exceeded()
                return (False, None)

            # Some other error
            logger.error(f"API call {operation_name} failed: {e}")
            raise  # Re-raise non-quota errors


# Global instance
_quota_manager: Optional[QuotaManager] = None


def get_quota_manager() -> QuotaManager:
    """Get the global quota manager instance."""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager(check_interval_seconds=3600)  # Check every hour
    return _quota_manager


def reset_quota_manager():
    """Reset the global quota manager (for testing)."""
    global _quota_manager
    if _quota_manager:
        _quota_manager.stop_checker()
    _quota_manager = None
