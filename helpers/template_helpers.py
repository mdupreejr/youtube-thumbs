"""
Template helper functions for the unified table viewer.

Provides utilities to format data for the table_viewer.html template.
"""

from typing import Dict, Any, List, Optional
import html
import re


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
        # This is a simple approach but better than no sanitization
        
        # Remove script tags and their content (safe pattern)
        # Use simple, non-backtracking pattern to prevent ReDoS
        html_content = re.sub(
            r'<script[^>]*>[\s\S]*?</script[^>]*>',
            '',
            html_content,
            flags=re.IGNORECASE
        )
        
        # Remove potentially dangerous attributes
        html_content = re.sub(r'\son\w+\s*=\s*["\'][^"\']*["\']', '', html_content, flags=re.IGNORECASE)
        
        # Remove javascript: protocols
        html_content = re.sub(r'javascript\s*:', '', html_content, flags=re.IGNORECASE)
        
        # Remove data: protocols (except for safe image data)
        html_content = re.sub(r'data\s*:(?!image/)', '', html_content, flags=re.IGNORECASE)
        
        # Allow only specific safe tags using safe, non-backtracking patterns
        safe_tags = ['a', 'span', 'strong', 'em', 'br', 'small', 'code', 'pre']
        
        # Remove all HTML tags except safe ones
        # First, remove all unsafe tags
        html_content = re.sub(
            r'<(?!/?)(?!(?:' + '|'.join(safe_tags) + r')(?:\s|>))[^>]*>',
            '',
            html_content,
            flags=re.IGNORECASE
        )
        
        # Clean up any malformed tags that might remain
        html_content = re.sub(r'<[^>]*$', '', html_content)  # Remove incomplete tags at end
        html_content = re.sub(r'^[^<]*>', '', html_content)  # Remove incomplete tags at start
        
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
    config = PageConfig('Logs', 'logs', f'logs-{current_tab}')
    config.current_url = f'{ingress_path}/logs'

    # Add main navigation tabs
    config.add_main_tab('Rated Songs', f'/logs?tab=rated', current_tab == 'rated')
    config.add_main_tab('Matches', f'/logs?tab=matches', current_tab == 'matches')
    config.add_main_tab('Recent', f'/logs?tab=recent', current_tab == 'recent')
    config.add_main_tab('Errors', f'/logs?tab=errors', current_tab == 'errors')
    config.add_main_tab('API Calls', f'/logs/api-calls', current_tab == 'api-calls')

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
    config = PageConfig('📊 YouTube API Call Logs', 'logs', 'api-calls')
    config.current_url = f'{ingress_path}/logs/api-calls'

    # Add main navigation tabs (Queue removed - it's now a top-level nav item)
    config.add_main_tab('Rated Songs', f'/logs?tab=rated', False)
    config.add_main_tab('Matches', f'/logs?tab=matches', False)
    config.add_main_tab('Recent', f'/logs?tab=recent', False)
    config.add_main_tab('Errors', f'/logs?tab=errors', False)
    config.add_main_tab('API Calls', f'/logs/api-calls', True)

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