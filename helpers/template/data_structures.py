"""
Data structures for the unified table viewer.

Provides classes for table configuration and data representation.
"""

from typing import Dict, Any, List, Optional


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
        import html
        from .sanitization import sanitize_html

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
