"""
Simple quota exceeded exception.

This is raised when YouTube API quota is exceeded.
The worker catches this and sleeps for 1 hour.
"""


class QuotaExceededError(Exception):
    """Raised when YouTube API quota is exceeded."""

    def __init__(self, message: str = "YouTube API quota exceeded"):
        self.message = message
        super().__init__(self.message)
