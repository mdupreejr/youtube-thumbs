"""
Helper functions for video operations.
"""
import hashlib
import re
from datetime import datetime
from typing import Dict, Any, Optional, List


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

    # Current timestamp for match tracking
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

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


def get_video_title(video: Dict[str, Any]) -> str:
    """
    Extract title from video data, preferring ha_title over yt_title.

    Args:
        video: Video dict with ha_title and/or yt_title fields

    Returns:
        Video title, or 'Unknown' if not found

    Examples:
        >>> video = {'ha_title': 'Song Name', 'yt_title': 'Song Name - Artist'}
        >>> get_video_title(video)
        'Song Name'

        >>> video = {'yt_title': 'Video Title'}
        >>> get_video_title(video)
        'Video Title'

        >>> video = {}
        >>> get_video_title(video)
        'Unknown'
    """
    title = (video.get('ha_title') or video.get('yt_title') or 'Unknown').strip() or 'Unknown'
    return title


def get_video_artist(video: Dict[str, Any]) -> str:
    """
    Extract artist/channel from video data, preferring ha_artist over yt_channel.

    Args:
        video: Video dict with ha_artist and/or yt_channel fields

    Returns:
        Artist/channel name, or 'Unknown' if not found

    Examples:
        >>> video = {'ha_artist': 'Artist Name', 'yt_channel': 'Channel Name'}
        >>> get_video_artist(video)
        'Artist Name'

        >>> video = {'yt_channel': 'Channel Name'}
        >>> get_video_artist(video)
        'Channel Name'

        >>> video = {}
        >>> get_video_artist(video)
        'Unknown'
    """
    artist = (video.get('ha_artist') or video.get('yt_channel') or 'Unknown').strip() or 'Unknown'
    return artist


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


def format_videos_for_display(videos: List[Dict], base_fields: List[str] = None, additional_fields: List[str] = None) -> List[Dict]:
    """
    Format video list for template display with standard title/artist extraction.
    Eliminates duplicate formatting loops across stats routes.

    Args:
        videos: List of video dicts from database
        base_fields: Base fields to include from video dict (default: ['yt_video_id', 'play_count', 'date_last_played'])
        additional_fields: Additional fields to copy from video dict (e.g., ['pending_reason', 'yt_match_attempts'])

    Returns:
        List of formatted video dicts with 'title' and 'artist' extracted

    Examples:
        # For rated videos (liked/disliked)
        >>> videos = [{'ha_title': 'Song', 'yt_video_id': 'abc', 'play_count': 5}]
        >>> formatted = format_videos_for_display(videos)
        >>> formatted[0]['title']
        'Song'

        # For unmatched videos (tracked in queue for retry)
        >>> videos = [{'ha_title': 'Song', 'yt_video_id': None, 'play_count': 2, 'date_added': '2025-01-01'}]
        >>> formatted = format_videos_for_display(videos,
        ...     base_fields=['yt_video_id', 'play_count', 'date_added'])
    """
    # Default base fields for rated videos
    if base_fields is None:
        base_fields = ['yt_video_id', 'play_count', 'date_last_played']

    formatted = []
    for video in videos:
        # Always include title and artist
        formatted_video = {
            'title': get_video_title(video),
            'artist': get_video_artist(video)
        }

        # Add base fields
        for field in base_fields:
            formatted_video[field] = video.get(field, 0 if 'count' in field else None)

        # Add additional fields if specified
        if additional_fields:
            for field in additional_fields:
                formatted_video[field] = video.get(field)

        formatted.append(formatted_video)

    return formatted