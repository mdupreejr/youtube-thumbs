"""
Helper functions for video operations.
"""
import hashlib
import re
from typing import Dict, Any, Optional


def prepare_video_upsert(video: Dict[str, Any], ha_media: Dict[str, Any], source: str = 'ha_live') -> Dict[str, Any]:
    """
    Prepare video data for database upsert.

    Args:
        video: Video info dict with yt_video_id and metadata from YouTube
        ha_media: Media info from Home Assistant with title, channel, duration
        source: Source of the video data (default: 'ha_live')

    Returns:
        Dict ready for database upsert_video method
    """
    yt_video_id = video['yt_video_id']
    video_title = video.get('title', ha_media.get('title', 'Unknown'))

    # Calculate ha_content_id from HA metadata for duplicate detection
    ha_title = ha_media.get('title', video_title)
    ha_duration = ha_media.get('duration')
    ha_artist = ha_media.get('artist', 'Unknown')
    ha_content_id = get_content_hash(ha_title, ha_duration, ha_artist)

    return {
        'yt_video_id': yt_video_id,
        'ha_content_id': ha_content_id,
        'ha_title': ha_title,
        'ha_artist': ha_artist,
        'ha_app_name': ha_media.get('app_name', 'YouTube'),
        'yt_title': video_title,
        'yt_channel': video.get('channel'),
        'yt_channel_id': video.get('channel_id'),
        'yt_description': video.get('description'),
        'yt_published_at': video.get('published_at'),
        'yt_category_id': video.get('category_id'),
        'yt_live_broadcast': video.get('live_broadcast'),
        'yt_location': video.get('location'),
        'yt_recording_date': video.get('recording_date'),
        'ha_duration': ha_duration,
        'yt_duration': video.get('duration'),
        'yt_url': f"https://www.youtube.com/watch?v={yt_video_id}",
        'source': source,
    }


def is_youtube_content(ha_media: Dict[str, Any]) -> bool:
    """
    Check if the media is from YouTube based on app_name field.

    Args:
        ha_media: Media data from Home Assistant

    Returns:
        True if content is from YouTube, False otherwise
    """
    app_name = ha_media.get('app_name', '').lower()
    return 'youtube' in app_name if app_name else False


def get_content_hash(title: Optional[str], duration: Optional[int], artist: Optional[str] = None) -> str:
    """
    Generate a hash for content identification with improved collision resistance.

    Args:
        title: Media title
        duration: Media duration in seconds
        artist: Artist/channel name (optional but recommended)

    Returns:
        SHA-256 hash of the normalized content
    """
    # Better normalization to reduce false positives while preventing collisions
    normalized_title = (title or '').lower().strip()
    # Remove punctuation but keep spaces
    normalized_title = re.sub(r'[^\w\s]', '', normalized_title)
    # Collapse multiple spaces
    normalized_title = re.sub(r'\s+', ' ', normalized_title)
    # Remove common noise words that don't help with uniqueness
    normalized_title = re.sub(r'\b(official|video|audio|hd|hq|lyrics|music)\b', '', normalized_title)
    normalized_title = normalized_title.strip()

    # Include artist for better uniqueness (if provided)
    if artist:
        normalized_artist = re.sub(r'[^\w\s]', '', artist.lower().strip())
        normalized_artist = re.sub(r'\s+', ' ', normalized_artist)
    else:
        normalized_artist = ''

    # Use -1 for None duration to distinguish from 0-second videos
    duration_str = str(duration if duration is not None else -1)

    # Combine fields for hash (artist first if provided)
    if normalized_artist:
        content = f"{normalized_artist}|{normalized_title}|{duration_str}"
    else:
        content = f"{normalized_title}|{duration_str}"

    # Return SHA-256 hash
    return hashlib.sha256(content.encode('utf-8')).hexdigest()