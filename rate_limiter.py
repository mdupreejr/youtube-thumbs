import time
from collections import deque
from typing import Tuple, Dict, Any
import os
from logger import logger

class RateLimiter:
    """Rate limiter to prevent API abuse."""
    
    def __init__(self) -> None:
        self.per_minute = self._get_limit('RATE_LIMIT_PER_MINUTE', 10)
        self.per_hour = self._get_limit('RATE_LIMIT_PER_HOUR', 100)
        self.per_day = self._get_limit('RATE_LIMIT_PER_DAY', 500)
        
        # Dedicated queues per window to keep operations O(1)
        self.minute_requests = deque()
        self.hour_requests = deque()
        self.day_requests = deque()
    
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
        Check if request is allowed under rate limits.
        Returns (allowed: bool, reason: str)
        """
        current_time = time.time()
        
        minute_count, hour_count, day_count = self._counts(current_time)
        
        # Check limits
        if minute_count >= self.per_minute:
            logger.warning(f"Rate limit exceeded: {self.per_minute} requests per minute")
            return False, f"Rate limit exceeded: {self.per_minute} requests per minute"
        
        if hour_count >= self.per_hour:
            logger.warning(f"Rate limit exceeded: {self.per_hour} requests per hour")
            return False, f"Rate limit exceeded: {self.per_hour} requests per hour"
        
        if day_count >= self.per_day:
            logger.warning(f"Rate limit exceeded: {self.per_day} requests per day")
            return False, f"Rate limit exceeded: {self.per_day} requests per day"
        
        # Add request timestamp to each queue
        self.minute_requests.append(current_time)
        self.hour_requests.append(current_time)
        self.day_requests.append(current_time)
        
        return True, "OK"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limit statistics."""
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
