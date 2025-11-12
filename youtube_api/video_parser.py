"""
Video data parsing and validation for YouTube API responses.

This module handles processing of individual video data from YouTube API,
including duration parsing and validation.
"""

import re
from typing import Optional, Dict, Any
from logging_helper import LoggingHelper, LogType
from constants import YOUTUBE_DURATION_OFFSET

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

# ISO 8601 duration pattern
DURATION_PATTERN = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')


def parse_duration(duration_str: str) -> int:
    """
    Parse ISO 8601 duration string to seconds.

    Args:
        duration_str: ISO 8601 duration (e.g., "PT3M45S")

    Returns:
        Duration in seconds

    Raises:
        ValueError: If duration string format is invalid
    """
    if not duration_str:
        raise ValueError("Duration string is empty")

    match = DURATION_PATTERN.match(duration_str)
    if not match:
        raise ValueError(f"Invalid ISO 8601 duration format: {duration_str}")

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def validate_video_id(video_id: str) -> bool:
    """Validate YouTube video ID format."""
    if not video_id:
        return False
    if len(video_id) != 11:
        logger.warning("Invalid video ID length: %s", video_id)
        return False
    if not re.match(r'^[A-Za-z0-9_-]{11}$', video_id):
        logger.warning("Invalid video ID format: %s", video_id)
        return False
    return True


def validate_and_truncate_description(description: str) -> str:
    """Truncate description to prevent memory issues."""
    if not description:
        return ""
    if len(description) > 5000:
        logger.warning("Truncating description from %d to 5000 characters", len(description))
        return description[:5000]
    return description


def validate_duration(duration: int) -> Optional[int]:
    """Validate duration is within reasonable bounds."""
    if duration is None:
        return None
    if duration < 0:
        logger.warning("Invalid negative duration: %d", duration)
        return None
    if duration > 86400:  # 24 hours
        logger.warning("Invalid duration exceeding 24 hours: %d", duration)
        return None
    return duration


def process_search_result(video: Dict[str, Any], expected_duration: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    Process a single video from YouTube API response.

    Args:
        video: Video data from YouTube API
        expected_duration: Expected HA duration (YouTube will be +1s)

    Returns:
        Processed video_info dict or None if video should be skipped
    """
    video_id = video['id']
    if not validate_video_id(video_id):
        logger.error("Skipping video with invalid ID: %s", video_id)
        return None

    snippet = video.get('snippet') or {}
    content_details = video.get('contentDetails') or {}
    recording_details = video.get('recordingDetails') or {}

    duration_str = content_details.get('duration')
    try:
        duration = parse_duration(duration_str) if duration_str else None
    except ValueError as e:
        logger.error(f"Failed to parse duration for video {video_id}: {e}")
        # Skip videos with invalid duration format
        return None

    # Extract location if available
    location = None
    if recording_details.get('location'):
        loc = recording_details['location']
        if loc.get('latitude') and loc.get('longitude'):
            location = f"{loc['latitude']},{loc['longitude']}"
            if loc.get('altitude'):
                location += f",{loc['altitude']}"

    video_info = {
        'yt_video_id': video_id,
        'title': snippet.get('title'),
        'channel': snippet.get('channelTitle'),
        'channel_id': snippet.get('channelId'),
        'description': validate_and_truncate_description(snippet.get('description')),
        'published_at': snippet.get('publishedAt'),
        'category_id': snippet.get('categoryId'),
        'live_broadcast': snippet.get('liveBroadcastContent'),
        'location': location,
        'recording_date': recording_details.get('recordingDate'),
        'duration': validate_duration(duration)
    }

    # Check duration matching if expected_duration is provided
    if expected_duration is not None and duration is not None:
        # YouTube duration must be either:
        # 1. Exact match with HA (duration == expected_duration)
        # 2. Exactly 1 second longer than HA (duration == expected_duration + 1)
        if duration != expected_duration and duration != expected_duration + YOUTUBE_DURATION_OFFSET:
            return None  # Skip videos that don't match duration (exact or +1s only)
        duration_diff = duration - expected_duration
        logger.debug(
            f"Duration match: {expected_duration}s (HA) → {video_info['duration']}s (YT) | Diff: +{duration_diff}s | ID: {video_info['yt_video_id']}"
        )
    elif duration is None and expected_duration is not None:
        logger.warning(
            f"Duration missing for video ID: {video_info['yt_video_id']}; falling back to title match only"
        )

    return video_info
