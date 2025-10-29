"""
Helper functions for video operations.
"""
import hashlib
from typing import Dict, Any, Optional


def prepare_video_upsert(video: Dict[str, Any], ha_media: Dict[str, Any], source: str = 'ha_live') -> Dict[str, Any]:
    """
    Prepare video data for database upsert.

    Args:
        video: Video info dict with yt_video_id and metadata from YouTube
        ha_media: Media info from Home Assistant with title, artist, duration
        source: Source of the video data (default: 'ha_live')

    Returns:
        Dict ready for database upsert_video method
    """
    yt_video_id = video['yt_video_id']
    video_title = video.get('title', ha_media.get('title', 'Unknown'))

    return {
        'yt_video_id': yt_video_id,
        'ha_title': ha_media.get('title', video_title),
        'ha_artist': ha_media.get('artist'),
        'yt_title': video_title,
        'yt_channel': video.get('channel'),
        'yt_channel_id': video.get('channel_id'),
        'yt_description': video.get('description'),
        'yt_published_at': video.get('published_at'),
        'yt_category_id': video.get('category_id'),
        'yt_live_broadcast': video.get('live_broadcast'),
        'yt_location': video.get('location'),
        'yt_recording_date': video.get('recording_date'),
        'ha_duration': ha_media.get('duration'),
        'yt_duration': video.get('duration'),
        'yt_url': f"https://www.youtube.com/watch?v={yt_video_id}",
        'source': source,
    }


def is_youtube_content(ha_media: Dict[str, Any]) -> bool:
    """
    Check if the media is from YouTube based on channel/app_name.

    Args:
        ha_media: Media data from Home Assistant

    Returns:
        True if content is from YouTube, False otherwise
    """
    channel = ha_media.get('channel', '').lower()

    # List of known YouTube app/channel names
    youtube_channels = ['youtube', 'youtube music', 'youtube tv', 'yt', 'ytmusic']

    return any(yt in channel for yt in youtube_channels) if channel else False


def get_content_hash(title: Optional[str], duration: Optional[int]) -> str:
    """
    Generate a hash for content identification based on title and duration.

    Args:
        title: Media title
        duration: Media duration in seconds

    Returns:
        SHA-256 hash of the normalized title and duration
    """
    # Normalize the title - lowercase and strip whitespace
    normalized_title = (title or '').lower().strip()
    # Include duration in the hash, use 0 if not provided
    duration_str = str(duration if duration is not None else 0)

    # Create a consistent string to hash
    content = f"{normalized_title}|{duration_str}"

    # Return SHA-256 hash
    return hashlib.sha256(content.encode('utf-8')).hexdigest()