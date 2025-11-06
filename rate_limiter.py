import time
import threading
from collections import deque
from typing import Tuple, Dict, Any
import os
from logger import logger

class RateLimiter:
    """Thread-safe rate limiter to prevent API abuse."""

    def __init__(self) -> None:
        self.per_minute = self._get_limit('RATE_LIMIT_PER_MINUTE', 10)
        self.per_hour = self._get_limit('RATE_LIMIT_PER_HOUR', 100)
        self.per_day = self._get_limit('RATE_LIMIT_PER_DAY', 500)

        # Dedicated queues per window to keep operations O(1)
        self.minute_requests = deque()
        self.hour_requests = deque()
        self.day_requests = deque()

        # Thread lock to protect deque access from multiple Flask threads
        self._lock = threading.Lock()
    
    @staticmethod
    def _get_limit(env_name: str, default: int) -> int:
        """Read an integer limit from env vars, falling back on blanks/errors."""
        raw_value = os.getenv(env_name)
        if not raw_value or not raw_value.strip():
            return default
        try:
            return int(raw_value.strip())
        except ValueError:
            logger.warning(
                "Invalid value '%s' for %s; using default %s",
                raw_value,
                env_name,
                default,
            )
            return default

    @staticmethod
    def _prune(queue: deque, time_window: int, current_time: float) -> None:
        """Remove timestamps older than the provided window."""
        while queue and current_time - queue[0] > time_window:
            queue.popleft()

    @staticmethod
    def _retry_after(queue: deque, time_window: int, current_time: float) -> int:
        """Estimate seconds until the current window has capacity again."""
        if not queue:
            return time_window
        oldest = queue[0]
        remaining = int(time_window - (current_time - oldest))
        return max(remaining, 1)
    
    def _counts(self, current_time: float) -> Tuple[int, int, int]:
        """Return counts for each rate limit window."""
        self._prune(self.minute_requests, 60, current_time)
        self._prune(self.hour_requests, 3600, current_time)
        self._prune(self.day_requests, 86400, current_time)
        return (
            len(self.minute_requests),
            len(self.hour_requests),
            len(self.day_requests),
        )
    
    def check_and_add_request(self) -> Tuple[bool, str]:
        """
        Thread-safe check if request is allowed under rate limits.
        Returns (allowed: bool, reason: str)
        """
        with self._lock:
            current_time = time.time()

            minute_count, hour_count, day_count = self._counts(current_time)

            # Check limits
            if minute_count >= self.per_minute:
                retry = self._retry_after(self.minute_requests, 60, current_time)
                logger.warning(
                    "Rate limit exceeded (%s/min). Window count=%s; retry in ~%ss",
                    self.per_minute,
                    minute_count,
                    retry,
                )
                return False, f"Rate limit exceeded: {self.per_minute} requests per minute (retry in {retry}s)"

            if hour_count >= self.per_hour:
                retry = self._retry_after(self.hour_requests, 3600, current_time)
                logger.warning(
                    "Rate limit exceeded (%s/hr). Window count=%s; retry in ~%ss",
                    self.per_hour,
                    hour_count,
                    retry,
                )
                return False, f"Rate limit exceeded: {self.per_hour} requests per hour (retry in {retry}s)"

            if day_count >= self.per_day:
                retry = self._retry_after(self.day_requests, 86400, current_time)
                logger.warning(
                    "Rate limit exceeded (%s/day). Window count=%s; retry in ~%ss",
                    self.per_day,
                    day_count,
                    retry,
                )
                return False, f"Rate limit exceeded: {self.per_day} requests per day (retry in {retry}s)"

            # Add request timestamp to each queue
            self.minute_requests.append(current_time)
            self.hour_requests.append(current_time)
            self.day_requests.append(current_time)

            return True, "OK"
    
    def get_stats(self) -> Dict[str, Any]:
        """Thread-safe get current rate limit statistics."""
        with self._lock:
            current_time = time.time()
            minute_count, hour_count, day_count = self._counts(current_time)

            return {
                "last_minute": minute_count,
                "last_hour": hour_count,
                "last_day": day_count,
                "limits": {
                    "per_minute": self.per_minute,
                    "per_hour": self.per_hour,
                    "per_day": self.per_day
                }
            }

# Create global rate limiter instance
rate_limiter = RateLimiter()
