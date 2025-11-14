"""
Table building helpers for video lists.

Consolidates duplicate table row building code used across video list pages
(liked/disliked pages).
"""
from helpers.template import TableRow, TableCell


def build_video_table_rows(videos: list, format_videos_for_display_fn, format_youtube_link_fn) -> list:
    """
    Build standardized table rows for video lists (liked/disliked pages).

    Args:
        videos: List of video dicts from database
        format_videos_for_display_fn: Function to format videos
        format_youtube_link_fn: Function to create YouTube links

    Returns:
        List of TableRow objects
    """
    rows = []
    for video in videos:
        formatted_video = format_videos_for_display_fn([video])[0]

        # Format song title with YouTube link
        song_html = format_youtube_link_fn(
            formatted_video.get('yt_video_id'),
            formatted_video.get('title', 'Unknown'),
            icon=False
        )

        # Format last played date
        last_played = '-'
        if formatted_video.get('date_last_played'):
            last_played = str(formatted_video['date_last_played'])[:10]

        cells = [
            TableCell(formatted_video.get('title', 'Unknown'), song_html),
            TableCell(formatted_video.get('artist', '-'), style='color: #64748b;'),
            TableCell(formatted_video.get('play_count', 0), style='color: #64748b;'),
            TableCell(last_played, style='color: #64748b; white-space: nowrap;')
        ]
        rows.append(TableRow(cells))

    return rows
