"""
Template helper functions for the unified table viewer.

Provides utilities to format data for the table_viewer.html template.
"""

from typing import Dict, Any, List, Optional
import html


class TableColumn:
    """Represents a table column configuration."""
    
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
    """Represents a table cell with value and optional formatting."""
    
    def __init__(self, value: Any, html: Optional[str] = None, 
                 style: Optional[str] = None, title: Optional[str] = None):
        self.value = str(value) if value is not None else ''
        self.html = html
        self.style = style
        self.title = title
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'value': self.value,
            'html': self.html,
            'style': self.style,
            'title': self.title
        }


class TableRow:
    """Represents a table row with cells and optional click handling."""
    
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
    """Container for table columns and rows."""
    
    def __init__(self, columns: List[TableColumn], rows: List[TableRow]):
        self.columns = columns
        self.rows = rows
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'columns': [col.to_dict() for col in self.columns],
            'rows': [row.to_dict() for row in self.rows]
        }


class PageConfig:
    """Configuration for a page using the table viewer template."""
    
    def __init__(self, title: str, nav_active: str = '', storage_key: str = ''):
        self.title = title
        self.nav_active = nav_active
        self.storage_key = storage_key or f"table-{nav_active}"
        self.show_title = True
        self.title_suffix = None
        self.back_link = None
        self.back_text = None
        self.main_tabs = []
        self.sub_tabs = []
        self.filters = []
        self.hidden_fields = []
        self.current_url = ''
        self.filter_button_text = 'Apply'
        self.empty_state = None
        self.enable_sorting = True
        self.enable_resizing = True
        self.enable_column_toggle = True
        self.row_click_handler = None
        self.modal_api_url = None
        self.modal_title = 'Details'
        self.modal_formatter = None
        self.custom_js = None
        self.logs_tab = None  # For dropdown navigation highlighting
    
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
    config.add_main_tab('Queue', f'/logs/pending-ratings', current_tab == 'queue')
    
    return config


def create_queue_page_config(current_tab: str, ingress_path: str) -> PageConfig:
    """Create page configuration for queue pages."""
    config = PageConfig('📊 Queue Monitor', 'logs', f'queue-{current_tab}')
    config.current_url = f'{ingress_path}/logs/pending-ratings'
    
    # Add main navigation tabs (same as logs)
    config.add_main_tab('Rated Songs', f'/logs?tab=rated', False)
    config.add_main_tab('Matches', f'/logs?tab=matches', False)
    config.add_main_tab('Recent', f'/logs?tab=recent', False)
    config.add_main_tab('Errors', f'/logs?tab=errors', False)
    config.add_main_tab('API Calls', f'/logs/api-calls', False)
    config.add_main_tab('Queue', f'/logs/pending-ratings', True)
    
    # Add sub-navigation tabs
    config.add_sub_tab('Pending', f'/logs/pending-ratings?tab=pending', current_tab == 'pending')
    config.add_sub_tab('History', f'/logs/pending-ratings?tab=history', current_tab == 'history')
    config.add_sub_tab('Errors', f'/logs/pending-ratings?tab=errors', current_tab == 'errors')
    config.add_sub_tab('Statistics', f'/logs/pending-ratings?tab=statistics', current_tab == 'statistics')
    
    return config


def create_api_calls_page_config(ingress_path: str) -> PageConfig:
    """Create page configuration for API calls page."""
    config = PageConfig('📊 YouTube API Call Logs', 'logs', 'api-calls')
    config.current_url = f'{ingress_path}/logs/api-calls'
    
    # Add main navigation tabs (same as logs)
    config.add_main_tab('Rated Songs', f'/logs?tab=rated', False)
    config.add_main_tab('Matches', f'/logs?tab=matches', False)
    config.add_main_tab('Recent', f'/logs?tab=recent', False)
    config.add_main_tab('Errors', f'/logs?tab=errors', False)
    config.add_main_tab('API Calls', f'/logs/api-calls', True)
    config.add_main_tab('Queue', f'/logs/pending-ratings', False)
    
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