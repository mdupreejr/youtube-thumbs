"""
YouTube API module - Interface to YouTube Data API v3.

This module provides a clean interface for YouTube API operations including
authentication, video search, and rating management.

The module is organized into focused submodules:
- auth: OAuth2 authentication
- search: Video search operations
- rating: Get/set video ratings
- video_parser: Video data processing
- title_cleaner: Title sanitization and cleaning
- quota_manager: Quota error detection
"""

from typing import Optional
from logging_helper import LoggingHelper, LogType

# Import submodule functions
from .auth import authenticate, SCOPES
from .search import search_video_globally, set_database as set_search_database
from .rating import get_video_rating, set_video_rating, NO_RATING
from .video_parser import parse_duration
from .title_cleaner import build_smart_search_query
from .quota_manager import quota_error_detail

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

# Global database instance for API usage tracking (injected from app.py)
_db = None


def set_database(db):
    """Set the database instance for API usage tracking."""
    global _db
    _db = db
    # Also set database in search module for API call logging
    set_search_database(db)
    # Also set database in decorators module so it can log API call errors
    import decorators
    decorators._db = db


class YouTubeAPI:
    """Interface to YouTube Data API v3."""

    SCOPES = SCOPES
    NO_RATING = NO_RATING

    def __init__(self) -> None:
        self.youtube = None
        self.authenticate()

    def authenticate(self) -> None:
        """Authenticate with YouTube API using OAuth2."""
        self.youtube = authenticate()

    def search_video_globally(
        self,
        title: str,
        expected_duration: Optional[int] = None,
        artist: Optional[str] = None,
        return_api_response: bool = False
    ):
        """
        Search for a video globally. Filters by duration (exact or +1s) if provided.

        Args:
            title: Video title to search for
            expected_duration: Expected HA duration in seconds (YouTube must be exact or +1s)
            artist: Artist/channel name (optional, improves accuracy for generic titles)
            return_api_response: If True, return tuple of (candidates, api_debug_data)

        Returns:
            If return_api_response=False: List of candidate videos or None
            If return_api_response=True: Tuple of (candidates or None, api_debug_data dict)
        """
        return search_video_globally(
            self.youtube,
            title,
            expected_duration,
            artist,
            return_api_response
        )

    def get_video_rating(self, yt_video_id: str) -> str:
        """
        Get current rating for a video.

        Args:
            yt_video_id: YouTube video ID

        Returns:
            'like', 'dislike', or 'none'

        Raises:
            Specific exceptions on failure (no error suppression)
        """
        return get_video_rating(self.youtube, yt_video_id)

    def set_video_rating(self, yt_video_id: str, rating: str) -> bool:
        """
        Set rating for a video.

        Args:
            yt_video_id: YouTube video ID
            rating: Rating value ('like', 'dislike', or 'none')

        Returns:
            True on success

        Raises:
            Specific exceptions on failure (no error suppression)
        """
        return set_video_rating(self.youtube, yt_video_id, rating)


# Create global instance (will be initialized when module is imported)
yt_api = None


def get_youtube_api() -> YouTubeAPI:
    """Get or create YouTube API instance."""
    global yt_api
    if yt_api is None:
        logger.debug("Creating new YouTube API instance")
        yt_api = YouTubeAPI()
    return yt_api


# Re-export key functions and classes for backward compatibility
__all__ = [
    'YouTubeAPI',
    'get_youtube_api',
    'set_database',
    'authenticate',
    'search_video_globally',
    'get_video_rating',
    'set_video_rating',
    'parse_duration',
    'build_smart_search_query',
    'quota_error_detail',
    'SCOPES',
    'NO_RATING',
]
