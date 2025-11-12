"""
Formatting functions for the unified table viewer.

Provides utilities to format data for display in the table_viewer.html template.
"""

import html


def format_badge(text: str, badge_type: str = 'default') -> str:
    """Format a badge/pill element."""
    badge_classes = {
        'success': 'badge-success',
        'error': 'badge-error',
        'warning': 'badge-warning',
        'info': 'badge-info',
        'like': 'badge-like',
        'dislike': 'badge-dislike',
        'count': 'badge-count'
    }

    # Validate badge_type to prevent injection
    if badge_type not in badge_classes and badge_type != 'default':
        badge_type = 'default'

    css_class = badge_classes.get(badge_type, 'badge')
    escaped_text = html.escape(str(text))
    return f'<span class="badge {css_class}">{escaped_text}</span>'


def format_time_ago(timestamp: str) -> str:
    """Format timestamp as relative time with title."""
    if not timestamp:
        return '-'

    escaped_timestamp = html.escape(str(timestamp))
    return f'<span class="time-ago" title="{escaped_timestamp}">{escaped_timestamp}</span>'


def format_youtube_link(video_id: str, title: str, icon: bool = True) -> str:
    """Format a YouTube link with optional icon."""
    if not video_id:
        return html.escape(title or 'Unknown')

    # Validate video_id format (basic YouTube ID validation)
    if not isinstance(video_id, str) or not video_id.replace('-', '').replace('_', '').isalnum():
        return html.escape(title or 'Unknown')

    escaped_video_id = html.escape(video_id)
    escaped_title = html.escape(title or video_id)
    icon_html = ' 🔗' if icon else ''
    return f'<a href="https://www.youtube.com/watch?v={escaped_video_id}" target="_blank" rel="noopener noreferrer">{escaped_title}{icon_html}</a>'


def format_song_display(title: str, artist: str) -> str:
    """
    Format song title and artist for consistent display across the app.

    Creates a two-line display with the title in bold and the artist
    in a smaller, subdued font below.

    Args:
        title: The song title
        artist: The artist name

    Returns:
        HTML formatted song display

    Example:
        >>> format_song_display("Bohemian Rhapsody", "Queen")
        '<strong>Bohemian Rhapsody</strong><br><span style="font-size: 0.85em; color: #64748b;">Queen</span>'
    """
    if not title:
        title = 'Unknown'
    if not artist:
        artist = 'Unknown'

    # Sanitize to prevent XSS
    escaped_title = html.escape(str(title))
    escaped_artist = html.escape(str(artist))

    return f'<strong>{escaped_title}</strong><br><span style="font-size: 0.85em; color: #64748b;">{escaped_artist}</span>'


def format_status_badge(success: bool, success_text: str = '✓ Success',
                        failure_text: str = '✗ Failed') -> str:
    """
    Format a success/failure status badge.

    This is a convenience wrapper around format_badge() for boolean success states.

    Args:
        success: Whether the operation was successful
        success_text: Text to display for successful operations (default: '✓ Success')
        failure_text: Text to display for failed operations (default: '✗ Failed')

    Returns:
        HTML formatted badge element

    Example:
        >>> format_status_badge(True)
        '<span class="badge badge-success">✓ Success</span>'
        >>> format_status_badge(False)
        '<span class="badge badge-error">✗ Failed</span>'
    """
    if success:
        return format_badge(success_text, 'success')
    else:
        return format_badge(failure_text, 'error')


def format_rating_badge(rating: str) -> str:
    """
    Format rating value as badge.

    Consolidates 10+ identical rating badge formatting blocks.

    Args:
        rating: Rating value ('like', 'dislike', or other)

    Returns:
        HTML formatted badge element

    Example:
        >>> format_rating_badge('like')
        '<span class="badge badge-success">👍 Like</span>'
        >>> format_rating_badge('dislike')
        '<span class="badge badge-error">👎 Dislike</span>'
        >>> format_rating_badge('none')
        '<span class="badge badge-info">➖ None</span>'
    """
    badges = {
        'like': ('👍 Like', 'success'),
        'dislike': ('👎 Dislike', 'error'),
    }
    text, badge_type = badges.get(rating, ('➖ None', 'info'))
    return format_badge(text, badge_type)


def format_log_level_badge(level: str) -> str:
    """
    Format log level as badge.

    Consolidates repeated log level badge formatting.

    Args:
        level: Log level string ('ERROR', 'WARNING', 'INFO', etc.)

    Returns:
        HTML formatted badge element

    Example:
        >>> format_log_level_badge('ERROR')
        '<span class="badge badge-error">ERROR</span>'
        >>> format_log_level_badge('WARNING')
        '<span class="badge badge-warning">WARNING</span>'
    """
    level_types = {
        'ERROR': 'error',
        'CRITICAL': 'error',
        'WARNING': 'warning',
        'INFO': 'info',
        'DEBUG': 'default'
    }
    badge_type = level_types.get(level, 'info')
    return format_badge(level, badge_type)


def format_count_message(count: int, item_type: str, prefix: str = '') -> str:
    """
    Format message with count and pluralization.

    Consolidates repeated count message formatting patterns.

    Args:
        count: The count to display
        item_type: Type of item (e.g., 'operation', 'video', 'error')
        prefix: Optional prefix text

    Returns:
        Formatted HTML message string

    Example:
        >>> format_count_message(5, 'operation', 'Operations waiting...')
        'Operations waiting... <strong>5 operations</strong>'
        >>> format_count_message(1, 'video', 'Found')
        'Found <strong>1 video</strong>'
    """
    plural_form = pluralize(count, item_type)
    if prefix:
        return f"{prefix} <strong>{count} {plural_form}</strong>"
    return f"<strong>{count} {plural_form}</strong>"


def pluralize(count: int, singular: str, plural: str = None) -> str:
    """
    Return singular or plural form based on count.

    Args:
        count: The count to check
        singular: Singular form of the word
        plural: Optional plural form (defaults to singular + 's')

    Returns:
        Singular or plural form of the word

    Example:
        >>> pluralize(1, 'operation')
        'operation'
        >>> pluralize(5, 'operation')
        'operations'
        >>> pluralize(1, 'category', 'categories')
        'category'
        >>> pluralize(3, 'category', 'categories')
        'categories'
    """
    if plural is None:
        plural = singular + 's'
    return singular if count == 1 else plural


def truncate_text(text: str, max_length: int = 80, suffix: str = '...') -> str:
    """
    Truncate text with optional suffix.

    Args:
        text: The text to truncate
        max_length: Maximum length before truncation
        suffix: Suffix to add when truncating

    Returns:
        Truncated text with suffix if needed
    """
    if not text or not isinstance(text, str):
        return text or ''

    if len(text) <= max_length:
        return text

    return text[:max_length] + suffix
