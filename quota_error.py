"""
YouTube API exception classes.

These specific exceptions allow proper error handling instead of suppressing all errors.
Each error type requires different handling (retry, skip, alert, etc.)
"""


class YouTubeAPIError(Exception):
    """Base class for all YouTube API errors."""
    pass


class QuotaExceededError(YouTubeAPIError):
    """
    Raised when YouTube API quota is exceeded.

    Handling: Worker sleeps until midnight Pacific Time (quota reset).
    Logging: Always logged - quota exhaustion is important to track.
    """

    def __init__(self, message: str = "YouTube API quota exceeded"):
        self.message = message
        super().__init__(self.message)


class VideoNotFoundError(YouTubeAPIError):
    """
    Raised when a video doesn't exist or is unavailable.

    Handling: Mark as permanently failed, don't retry.
    Logging: Log as warning - not an error, video just doesn't exist.
    """

    def __init__(self, video_id: str, message: str = None):
        self.video_id = video_id
        self.message = message or f"Video not found: {video_id}"
        super().__init__(self.message)


class AuthenticationError(YouTubeAPIError):
    """
    Raised when authentication fails or credentials are invalid.

    Handling: CRITICAL - stop processing, alert user immediately.
    Logging: Always logged as ERROR - requires immediate attention.
    """

    def __init__(self, message: str = "YouTube API authentication failed"):
        self.message = message
        super().__init__(self.message)


class NetworkError(YouTubeAPIError):
    """
    Raised when network/server issues occur (timeouts, 5xx errors).

    Handling: Transient - retry with exponential backoff.
    Logging: Log as warning - temporary issue.
    """

    def __init__(self, message: str = "Network error communicating with YouTube API"):
        self.message = message
        super().__init__(self.message)


class InvalidRequestError(YouTubeAPIError):
    """
    Raised when the request is malformed or has invalid parameters.

    Handling: Permanent error - don't retry, fix the code.
    Logging: Always logged as ERROR - indicates a bug.
    """

    def __init__(self, message: str = "Invalid request to YouTube API"):
        self.message = message
        super().__init__(self.message)
