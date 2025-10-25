import time
from collections import deque
from typing import Tuple, Dict, Any
import os
from logger import logger

# Constants for time windows (in seconds)
TIME_WINDOW_MINUTE = 60
TIME_WINDOW_HOUR = 3600
TIME_WINDOW_DAY = 86400

class RateLimiter:
    """Rate limiter to prevent API abuse."""
    
    def __init__(self) -> None:
        self.per_minute = int(os.getenv('RATE_LIMIT_PER_MINUTE', '10'))
        self.per_hour = int(os.getenv('RATE_LIMIT_PER_HOUR', '100'))
        self.per_day = int(os.getenv('RATE_LIMIT_PER_DAY', '500'))
        
        # Single deque to track all request timestamps (more memory efficient)
        self.requests = deque()
    
    def _clean_old_requests(self, time_window: int) -> None:
        """Remove requests older than the time window."""
        current_time = time.time()
        while self.requests and current_time - self.requests[0] > time_window:
            self.requests.popleft()
    
    def _count_recent_requests(self, time_window: int) -> int:
        """Count requests within the time window."""
        current_time = time.time()
        return sum(1 for ts in self.requests if current_time - ts <= time_window)
    
    def check_and_add_request(self) -> Tuple[bool, str]:
        """
        Check if request is allowed under rate limits.
        Returns (allowed: bool, reason: str)
        """
        current_time = time.time()

        # Clean old requests (older than 1 day)
        self._clean_old_requests(TIME_WINDOW_DAY)

        # Count requests in each time window
        minute_count = self._count_recent_requests(TIME_WINDOW_MINUTE)
        hour_count = self._count_recent_requests(TIME_WINDOW_HOUR)
        day_count = self._count_recent_requests(TIME_WINDOW_DAY)
        
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
        
        # Add request timestamp
        self.requests.append(current_time)
        
        return True, "OK"
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limit statistics."""
        # Clean old requests (older than 1 day)
        self._clean_old_requests(TIME_WINDOW_DAY)

        return {
            "last_minute": self._count_recent_requests(TIME_WINDOW_MINUTE),
            "last_hour": self._count_recent_requests(TIME_WINDOW_HOUR),
            "last_day": self._count_recent_requests(TIME_WINDOW_DAY),
            "limits": {
                "per_minute": self.per_minute,
                "per_hour": self.per_hour,
                "per_day": self.per_day
            }
        }

# Create global rate limiter instance
rate_limiter = RateLimiter()
