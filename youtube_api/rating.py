"""
YouTube video rating operations (get/set rating).

This module handles getting and setting ratings (like/dislike) for YouTube videos.
"""

from logging_helper import LoggingHelper, LogType
from decorators import handle_youtube_error

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

NO_RATING = 'none'  # YouTube API rating value for unrated videos


@handle_youtube_error(context='get_rating', api_method='videos.getRating', quota_cost=1)
def get_video_rating(youtube_client, yt_video_id: str) -> str:
    """
    Get current rating for a video.

    Args:
        youtube_client: Authenticated YouTube API client
        yt_video_id: YouTube video ID

    Returns:
        'like', 'dislike', or 'none'

    Raises:
        Specific exceptions on failure (no error suppression)
    """
    logger.info(f"Checking rating for video ID: {yt_video_id}")

    request = youtube_client.videos().getRating(id=yt_video_id)
    response = request.execute()

    # API logging handled by @handle_youtube_error decorator
    # Removed duplicate logging (Issue #124)

    if response.get('items'):
        rating = response['items'][0].get('rating', NO_RATING)
        logger.info(f"Current rating for {yt_video_id}: {rating}")
        return rating

    return NO_RATING


@handle_youtube_error(context='set_rating', api_method='videos.rate', quota_cost=50)
def set_video_rating(youtube_client, yt_video_id: str, rating: str) -> bool:
    """
    Set rating for a video.

    Args:
        youtube_client: Authenticated YouTube API client
        yt_video_id: YouTube video ID
        rating: Rating value ('like', 'dislike', or 'none')

    Returns:
        True on success

    Raises:
        Specific exceptions on failure (no error suppression)
    """
    logger.info(f"Setting rating '{rating}' for video ID: {yt_video_id}")

    request = youtube_client.videos().rate(
        id=yt_video_id,
        rating=rating
    )
    request.execute()

    # API logging handled by @handle_youtube_error decorator
    # Removed duplicate logging (Issue #124)

    logger.info(f"Successfully rated video {yt_video_id} as '{rating}'")
    return True
