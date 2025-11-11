"""
Template helper functions for the unified table viewer.

Provides utilities to format data for the table_viewer.html template.
"""

from typing import Dict, Any, List, Optional
import html
import re
from flask import render_template


def sanitize_html(html_content: str) -> str:
    """
    Sanitize HTML content to prevent XSS attacks.
    
    This function allows only safe HTML tags and attributes while stripping
    potentially dangerous content.
    
    Args:
        html_content: Raw HTML content to sanitize
        
    Returns:
        Sanitized HTML content safe for rendering
    """
    if not html_content:
        return ''
    
    # Try to use bleach if available, otherwise fall back to basic cleaning
    try:
        import bleach
        
        # Define allowed tags and attributes for safe HTML
        allowed_tags = ['a', 'span', 'strong', 'em', 'br', 'small', 'code', 'pre']
        allowed_attributes = {
            'a': ['href', 'target', 'rel', 'title'],
            'span': ['class', 'title', 'style'],
            '*': ['class', 'title']
        }
        
        # Define allowed protocols for links
        allowed_protocols = ['http', 'https', 'mailto']
        
        return bleach.clean(
            html_content,
            tags=allowed_tags,
            attributes=allowed_attributes,
            protocols=allowed_protocols,
            strip=True
        )
    except ImportError:
        # Fallback: basic HTML sanitization using regex
        # Limit input length to prevent ReDoS attacks (10KB limit)
        MAX_HTML_LENGTH = 10000
        if len(html_content) > MAX_HTML_LENGTH:
            html_content = html_content[:MAX_HTML_LENGTH]

        # Remove script tags and their content using simple string replacement for safety
        # This avoids complex regex patterns that could cause ReDoS
        # Process in chunks to avoid catastrophic backtracking
        parts = html_content.lower().split('<script')
        if len(parts) > 1:
            cleaned_parts = [parts[0]]  # Keep content before first script tag
            for part in parts[1:]:
                # Find the end of the script tag
                script_end = part.find('</script>')
                if script_end != -1:
                    # Keep content after the closing script tag
                    cleaned_parts.append(part[script_end + 9:])
            html_content = ''.join(cleaned_parts)

        # Remove potentially dangerous attributes (limit match length to prevent ReDoS)
        html_content = re.sub(r'\son\w{1,20}\s*=\s*["\'][^"\']{0,100}["\']', '', html_content, flags=re.IGNORECASE)

        # Remove javascript: protocols
        html_content = re.sub(r'javascript\s*:', '', html_content, flags=re.IGNORECASE)

        # Remove data: protocols (except for safe image data)
        html_content = re.sub(r'data\s*:(?!image/)', '', html_content, flags=re.IGNORECASE)

        # Allow only specific safe tags using safe, non-backtracking patterns
        safe_tags = ['a', 'span', 'strong', 'em', 'br', 'small', 'code', 'pre']

        # Remove all HTML tags except safe ones (with length limits to prevent ReDoS)
        html_content = re.sub(
            r'<(?!/?)(?!(?:' + '|'.join(safe_tags) + r')(?:\s|>))[^>]{0,200}>',
            '',
            html_content,
            flags=re.IGNORECASE
        )

        # Clean up any malformed tags that might remain (with bounded quantifiers)
        # Limit to 200 chars to prevent ReDoS
        html_content = re.sub(r'<[^>]{0,200}$', '', html_content)  # Remove incomplete tags at end
        html_content = re.sub(r'^[^<]{0,200}>', '', html_content)  # Remove incomplete tags at start

        sanitized = html_content

        return sanitized


class TableColumn:
    """
    Represents a table column configuration for the unified table viewer.
    
    Args:
        key: Unique identifier for the column (used for sorting/filtering)
        label: Display name for the column header
        sortable: Whether this column can be sorted by clicking the header
        resizable: Whether this column can be resized by dragging
        width: Optional CSS width value (e.g., "200px", "20%")
    """
    
    def __init__(self, key: str, label: str, sortable: bool = True, 
                 resizable: bool = True, width: Optional[str] = None):
        self.key = key
        self.label = label
        self.sortable = sortable
        self.resizable = resizable
        self.width = width
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'label': self.label,
            'sortable': self.sortable,
            'resizable': self.resizable,
            'width': self.width
        }


class TableCell:
    """
    Represents a table cell with value and optional formatting.

    Automatically sanitizes HTML content to prevent XSS attacks while preserving
    safe formatting elements like links, spans, and basic text formatting.

    Args:
        value: The plain text value of the cell
        display_html: Optional HTML content (will be sanitized)
        style: Optional CSS style string
        title: Optional title attribute for hover tooltips
    """

    def __init__(self, value: Any, display_html: Optional[str] = None,
                 style: Optional[str] = None, title: Optional[str] = None):
        self.value = str(value) if value is not None else ''

        # Sanitize HTML content to prevent XSS
        if display_html:
            self.html = sanitize_html(display_html)
        else:
            self.html = None

        # Sanitize style and title attributes
        self.style = html.escape(style) if style else None
        self.title = html.escape(title) if title else None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'value': self.value,
            'html': self.html,
            'style': self.style,
            'title': self.title
        }


class TableRow:
    """
    Represents a table row with cells and optional click handling.
    
    Args:
        cells: List of TableCell objects for each column
        clickable: Whether this row should respond to click events
        row_id: Unique identifier passed to click handler if clickable
    """
    
    def __init__(self, cells: List[TableCell], clickable: bool = False, 
                 row_id: Optional[str] = None):
        self.cells = cells
        self.clickable = clickable
        self.id = row_id
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'cells': [cell.to_dict() for cell in self.cells],
            'clickable': self.clickable,
            'id': self.id
        }


class TableData:
    """
    Container for table columns and rows in the unified table viewer.
    
    This class holds the complete data structure needed to render a table
    with the table_viewer.html template.
    
    Args:
        columns: List of TableColumn objects defining the table structure
        rows: List of TableRow objects containing the actual data
    """
    
    def __init__(self, columns: List[TableColumn], rows: List[TableRow]):
        self.columns = columns
        self.rows = rows
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'columns': [col.to_dict() for col in self.columns],
            'rows': [row.to_dict() for row in self.rows]
        }


class PageConfig:
    """
    Configuration for a page using the table viewer template.
    
    This class contains all the configuration options for customizing
    the appearance and behavior of a table viewer page.
    
    Args:
        title: The page title displayed in the header
        nav_active: Which top-level navigation item is active
        storage_key: localStorage key for saving user preferences
    """
    
    def __init__(self, title: str, nav_active: str = '', storage_key: str = ''):
        # Basic page settings
        self.title = title
        self.nav_active = nav_active
        self.storage_key = storage_key or f"table-{nav_active}"
        self.show_title = True
        self.title_suffix = None
        
        # Navigation settings
        self.back_link = None
        self.back_text = None
        self.main_tabs = []
        self.sub_tabs = []
        self.logs_tab = None  # For dropdown navigation highlighting
        
        # Filtering and form settings
        self.filters = []
        self.hidden_fields = []
        self.current_url = ''
        self.filter_button_text = 'Apply'
        
        # Empty state configuration
        self.empty_state = None
        
        # Table functionality settings
        self.enable_sorting = True
        self.enable_resizing = True
        self.enable_column_toggle = True
        
        # Row interaction settings
        self.row_click_handler = None
        self.modal_api_url = None
        self.modal_title = 'Details'
        self.modal_formatter = None
        
        # Custom JavaScript
        self.custom_js = None
    
    def add_back_link(self, url: str, text: str):
        """Add a back navigation link."""
        self.back_link = url
        self.back_text = text
        return self
    
    def add_main_tab(self, label: str, url: str, active: bool = False):
        """Add a main navigation tab."""
        self.main_tabs.append({'label': label, 'url': url, 'active': active})
        return self
    
    def add_sub_tab(self, label: str, url: str, active: bool = False):
        """Add a sub navigation tab."""
        self.sub_tabs.append({'label': label, 'url': url, 'active': active})
        return self
    
    def add_filter(self, name: str, label: str, options: List[Dict[str, Any]]):
        """Add a filter dropdown."""
        self.filters.append({
            'name': name,
            'label': label,
            'options': options
        })
        return self
    
    def add_hidden_field(self, name: str, value: str):
        """Add a hidden form field."""
        self.hidden_fields.append({'name': name, 'value': value})
        return self
    
    def set_empty_state(self, icon: str, title: str, message: str):
        """Set the empty state display."""
        self.empty_state = {'icon': icon, 'title': title, 'message': message}
        return self
    
    def set_modal_config(self, api_url: str, title: str = 'Details', 
                        formatter: str = None):
        """Configure modal popup functionality."""
        self.modal_api_url = api_url
        self.modal_title = title
        self.modal_formatter = formatter
        self.row_click_handler = 'showRowDetails'
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for template rendering."""
        return {
            'title': self.title,
            'nav_active': self.nav_active,
            'storage_key': self.storage_key,
            'show_title': self.show_title,
            'title_suffix': self.title_suffix,
            'back_link': self.back_link,
            'back_text': self.back_text,
            'main_tabs': self.main_tabs,
            'sub_tabs': self.sub_tabs,
            'filters': self.filters,
            'hidden_fields': self.hidden_fields,
            'current_url': self.current_url,
            'filter_button_text': self.filter_button_text,
            'empty_state': self.empty_state,
            'enable_sorting': self.enable_sorting,
            'enable_resizing': self.enable_resizing,
            'enable_column_toggle': self.enable_column_toggle,
            'row_click_handler': self.row_click_handler,
            'modal_api_url': self.modal_api_url,
            'modal_title': self.modal_title,
            'modal_formatter': self.modal_formatter,
            'custom_js': self.custom_js,
            'logs_tab': self.logs_tab
        }


def create_logs_page_config(current_tab: str, ingress_path: str) -> PageConfig:
    """Create page configuration for logs pages."""
    config = PageConfig('Logs', f'logs-{current_tab}', f'logs-{current_tab}')
    config.current_url = f'{ingress_path}/logs'
    return config


def create_queue_page_config(current_tab: str, ingress_path: str) -> PageConfig:
    """Create page configuration for queue pages."""
    config = PageConfig('📊 Queue Monitor', 'queue', f'queue-{current_tab}')
    config.current_url = f'{ingress_path}/logs/pending-ratings'

    # Queue is now a top-level nav item, so no logs main tabs needed
    # Just add the queue sub-tabs
    config.add_sub_tab('Pending', f'/logs/pending-ratings?tab=pending', current_tab == 'pending')
    config.add_sub_tab('History', f'/logs/pending-ratings?tab=history', current_tab == 'history')
    config.add_sub_tab('Errors', f'/logs/pending-ratings?tab=errors', current_tab == 'errors')
    config.add_sub_tab('Statistics', f'/logs/pending-ratings?tab=statistics', current_tab == 'statistics')

    return config


def create_api_calls_page_config(ingress_path: str) -> PageConfig:
    """Create page configuration for API calls page."""
    config = PageConfig('📊 YouTube API Call Logs', 'logs-api-calls', 'api-calls')
    config.current_url = f'{ingress_path}/logs/api-calls'
    return config


def create_stats_page_config(rating_type: str, ingress_path: str) -> PageConfig:
    """Create page configuration for stats pages."""
    config = PageConfig(f'{rating_type.capitalize()} Videos', 'stats', f'stats-{rating_type}')
    config.current_url = f'{ingress_path}/stats/{rating_type}'
    config.add_back_link('/stats', 'Stats')
    
    return config


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


def create_pagination_info(page: int, per_page: int, total_count: int, base_url: str) -> Dict[str, Any]:
    """
    Create pagination information for the unified table template.
    
    Args:
        page: Current page number (1-based)
        per_page: Number of items per page
        total_count: Total number of items
        base_url: Base URL for pagination links
        
    Returns:
        Dictionary containing pagination information for the template
    """
    total_pages = (total_count + per_page - 1) // per_page
    
    if total_pages <= 1:
        return None
    
    # Generate page numbers to display
    page_numbers = []
    start_page = max(1, page - 2)
    end_page = min(total_pages, page + 2)
    
    if start_page > 1:
        page_numbers.append(1)
        if start_page > 2:
            page_numbers.append('...')
    
    for p in range(start_page, end_page + 1):
        page_numbers.append(p)
    
    if end_page < total_pages:
        if end_page < total_pages - 1:
            page_numbers.append('...')
        page_numbers.append(total_pages)
    
    return {
        'current_page': page,
        'total_pages': total_pages,
        'page_numbers': page_numbers,
        'prev_url': f"{base_url}?page={page-1}" if page > 1 else None,
        'next_url': f"{base_url}?page={page+1}" if page < total_pages else None,
        'page_url_template': f"{base_url}?page=PAGE_NUM"
    }


def create_status_message(items_count: int, total_count: int = None, 
                         item_type: str = 'items') -> str:
    """
    Create a standardized status message for table displays.
    
    Args:
        items_count: Number of items currently displayed
        total_count: Total number of items available (if different from displayed)
        item_type: Type of items being displayed (e.g., 'songs', 'errors')
        
    Returns:
        Formatted status message
    """
    if total_count and total_count > items_count:
        return f"Showing {items_count:,} of {total_count:,} {item_type}"
    else:
        return f"Showing {items_count:,} {item_type}"


def create_filter_option(value: str, label: str, selected: bool = False) -> Dict[str, Any]:
    """
    Create a filter option for use in PageConfig.add_filter().
    
    Args:
        value: The value to submit when this option is selected
        label: The display text for the option
        selected: Whether this option is currently selected
        
    Returns:
        Dictionary formatted for use in filter dropdowns
    """
    return {
        'value': value,
        'label': label,
        'selected': selected
    }


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


# ============================================================================
# NEW OPTIMIZATION HELPERS (v5.3.3)
# Consolidate repeated patterns across route handlers
# ============================================================================

def render_table_page(
    page_config: PageConfig,
    ingress_path: str,
    table_data: Optional[TableData] = None,
    pagination: Optional[Dict] = None,
    status_message: str = '',
    summary_stats: Optional[Dict] = None
):
    """
    Render table viewer page with consistent parameters.

    Consolidates 15+ identical render_template calls across route files.

    Args:
        page_config: PageConfig object with page configuration
        ingress_path: Ingress path for navigation
        table_data: Optional TableData object with table rows/columns
        pagination: Optional pagination dictionary
        status_message: Optional status message to display
        summary_stats: Optional summary statistics dictionary

    Returns:
        Rendered template response

    Example:
        builder = LogsPageBuilder('recent', ingress_path)
        builder.set_title('Recent Videos')
        page_config, table_data, pagination, status = builder.build()
        return render_table_page(page_config, ingress_path, table_data, pagination, status)
    """
    return render_template(
        'table_viewer.html',
        ingress_path=ingress_path,
        page_config=page_config.to_dict(),
        table_data=table_data.to_dict() if table_data and table_data.rows else None,
        pagination=pagination,
        status_message=status_message,
        summary_stats=summary_stats
    )


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


def create_period_filter(current_value: str = 'all', name: str = 'period', label: str = 'Time Period') -> Dict:
    """
    Create standard time period filter options.

    Consolidates 3+ identical period filter definitions.

    Args:
        current_value: Currently selected value
        name: Filter parameter name
        label: Filter label text

    Returns:
        Filter configuration dictionary

    Example:
        page_config.add_filter(**create_period_filter(period_filter))
    """
    options = [
        ('hour', 'Last Hour'),
        ('day', 'Last Day'),
        ('week', 'Last Week'),
        ('month', 'Last Month'),
        ('all', 'All Time')
    ]
    return {
        'name': name,
        'label': label,
        'options': [
            {'value': val, 'label': lbl, 'selected': current_value == val}
            for val, lbl in options
        ]
    }


def create_rating_filter(current_value: str = 'all', name: str = 'rating', label: str = 'Rating') -> Dict:
    """
    Create standard rating filter options.

    Args:
        current_value: Currently selected value
        name: Filter parameter name
        label: Filter label text

    Returns:
        Filter configuration dictionary

    Example:
        page_config.add_filter(**create_rating_filter(rating_filter))
    """
    options = [
        ('all', 'All Ratings'),
        ('like', '👍 Liked'),
        ('dislike', '👎 Disliked'),
        ('none', '➖ No Rating')
    ]
    return {
        'name': name,
        'label': label,
        'options': [
            {'value': val, 'label': lbl, 'selected': current_value == val}
            for val, lbl in options
        ]
    }


def create_status_filter(current_value: str = 'all', name: str = 'status', label: str = 'Status') -> Dict:
    """
    Create standard status filter options.

    Args:
        current_value: Currently selected value
        name: Filter parameter name
        label: Filter label text

    Returns:
        Filter configuration dictionary

    Example:
        page_config.add_filter(**create_status_filter(status_filter))
    """
    options = [
        ('all', 'All Status'),
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ]
    return {
        'name': name,
        'label': label,
        'options': [
            {'value': val, 'label': lbl, 'selected': current_value == val}
            for val, lbl in options
        ]
    }


def add_queue_tabs(page_config: PageConfig, current_tab: str, ingress_path: str):
    """
    Add standard queue monitoring tabs.

    Consolidates 4+ identical tab configurations for queue pages.

    Args:
        page_config: PageConfig object to add tabs to
        current_tab: Currently active tab identifier
        ingress_path: Ingress path for tab URLs

    Example:
        add_queue_tabs(page_config, 'pending', ingress_path)
    """
    tabs = [
        ('Pending', 'pending'),
        ('History', 'history'),
        ('Errors', 'errors'),
        ('Statistics', 'statistics')
    ]
    for label, tab in tabs:
        page_config.add_sub_tab(
            label,
            f'/logs/pending-ratings?tab={tab}',
            current_tab == tab
        )


def get_video_table_columns() -> List[TableColumn]:
    """
    Get standard columns for video/song tables.

    Consolidates identical column definitions for liked/disliked/recent videos.

    Returns:
        List of TableColumn objects

    Example:
        columns = get_video_table_columns()
    """
    return [
        TableColumn('song', 'Song', width='50%'),
        TableColumn('artist', 'Artist'),
        TableColumn('plays', 'Plays'),
        TableColumn('last_played', 'Last Played')
    ]