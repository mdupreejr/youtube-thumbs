"""
Helper functions for video operations.
"""
from typing import Dict, Any


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