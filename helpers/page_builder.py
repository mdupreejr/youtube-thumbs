"""
Architectural fix: Unified page builder for logs pages.

This module provides a consistent, validated approach to building pages
that prevents the fragile manual attribute-setting pattern that caused
multiple pages to break (v4.2.2, v4.2.6, v4.2.7).

The LogsPageBuilder ensures all required attributes are set and provides
a single source of truth for page configuration.
"""
from typing import Optional, List, Dict, Any, Callable
from helpers.template import PageConfig, TableData, TableColumn, TableRow
from helpers.pagination_helpers import generate_page_numbers


class LogsPageBuilder:
    """
    Builder class for creating logs pages with consistent configuration.

    This replaces the fragile pattern of manually setting attributes in each
    _create_*_page() function. Instead, required attributes are set automatically
    and the builder validates everything before returning.

    Usage:
        builder = LogsPageBuilder('recent', ingress_path)
        builder.set_title('Recent Videos')
        builder.set_empty_state('📭', 'No Videos Yet', 'No videos have been added')
        # ... add table data ...
        return builder.build()

    Advantages:
        - Required attributes (logs_tab, current_url, nav_active) set automatically
        - Validation ensures nothing is forgotten
        - Single source of truth for page structure
        - Impossible to forget required fields
        - Type-safe interface
    """

    def __init__(self, tab_name: str, ingress_path: str):
        """
        Initialize builder with required parameters.

        Args:
            tab_name: The tab identifier ('rated', 'matches', 'recent', 'errors', 'queue')
            ingress_path: The ingress path from the request
        """
        self.tab_name = tab_name
        self.ingress_path = ingress_path

        # Create page config with automatic defaults
        self.page_config = PageConfig(
            title=self._default_title(tab_name),
            nav_active=f'logs-{tab_name}',
            storage_key=f'logs-{tab_name}'
        )

        # Set required attributes automatically
        self.page_config.logs_tab = tab_name
        self.page_config.current_url = '/logs'

        # Initialize optional attributes
        self.table_data: Optional[TableData] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self.status_message: str = ''

        # Track if table was set
        self._table_set = False

    def _default_title(self, tab_name: str) -> str:
        """Generate default title from tab name."""
        titles = {
            'rated': 'Rated Songs',
            'matches': 'Matches',
            'recent': 'Recent Videos',
            'errors': 'Errors',
            'queue': 'Queue Statistics'
        }
        return titles.get(tab_name, tab_name.capitalize())

    def set_title(self, title: str, suffix: Optional[str] = None) -> 'LogsPageBuilder':
        """
        Set custom page title.

        Args:
            title: The page title
            suffix: Optional title suffix

        Returns:
            Self for method chaining
        """
        self.page_config.title = title
        if suffix:
            self.page_config.title_suffix = suffix
        return self

    def add_filter(self, name: str, label: str, options: List[Dict[str, Any]]) -> 'LogsPageBuilder':
        """
        Add a filter dropdown to the page.

        Args:
            name: Filter name (e.g., 'period', 'rating')
            label: Display label (e.g., 'Time Period')
            options: List of option dicts with 'value', 'label', 'selected'

        Returns:
            Self for method chaining
        """
        self.page_config.add_filter(name, label, options)
        return self

    def add_hidden_field(self, name: str, value: str) -> 'LogsPageBuilder':
        """
        Add a hidden form field.

        Args:
            name: Field name
            value: Field value

        Returns:
            Self for method chaining
        """
        self.page_config.add_hidden_field(name, value)
        return self

    def set_empty_state(self, icon: str, title: str, message: str) -> 'LogsPageBuilder':
        """
        Set the empty state display.

        Args:
            icon: Emoji or icon to display
            title: Empty state title
            message: Empty state message

        Returns:
            Self for method chaining
        """
        self.page_config.set_empty_state(icon, title, message)
        return self

    def set_table(self, columns: List[TableColumn], rows: List[TableRow]) -> 'LogsPageBuilder':
        """
        Set the table data.

        Args:
            columns: List of table columns
            rows: List of table rows

        Returns:
            Self for method chaining
        """
        self.table_data = TableData(columns, rows)
        self._table_set = True
        return self

    def set_pagination(
        self,
        current_page: int,
        total_pages: int,
        page_numbers: List[int],
        base_url: str,
        query_params: Optional[Dict[str, str]] = None
    ) -> 'LogsPageBuilder':
        """
        Set pagination configuration.

        Args:
            current_page: Current page number (1-indexed)
            total_pages: Total number of pages
            page_numbers: List of page numbers to show
            base_url: Base URL for pagination links
            query_params: Optional query parameters to preserve

        Returns:
            Self for method chaining
        """
        if total_pages <= 1:
            self.pagination = None
            return self

        # Build query string
        query_string = ''
        if query_params:
            query_string = '&' + '&'.join(f"{k}={v}" for k, v in query_params.items() if v)

        self.pagination = {
            'current_page': current_page,
            'total_pages': total_pages,
            'page_numbers': page_numbers,
            'prev_url': f"{base_url}?page={current_page-1}{query_string}",
            'next_url': f"{base_url}?page={current_page+1}{query_string}",
            'page_url_template': f"{base_url}?page=PAGE_NUM{query_string}"
        }
        return self

    def set_status_message(self, message: str) -> 'LogsPageBuilder':
        """
        Set the status message displayed below the page.

        Args:
            message: Status message text

        Returns:
            Self for method chaining
        """
        self.status_message = message
        return self

    def set_row_click_navigation(self, url_template: str) -> 'LogsPageBuilder':
        """
        Set up row click navigation to detail pages.

        Consolidates 3+ identical JavaScript blocks for clickable rows.

        Args:
            url_template: URL template with ingress path (e.g., '/logs/pending-ratings/item/')

        Returns:
            Self for method chaining

        Example:
            builder.set_row_click_navigation(f'{ingress_path}/logs/pending-ratings/item/')
        """
        self.page_config.custom_js = f'''
            document.querySelectorAll('.clickable-row').forEach(row => {{
                row.style.cursor = 'pointer';
                row.addEventListener('click', function() {{
                    const rowId = this.dataset.rowId;
                    window.location.href = '{url_template}' + rowId;
                }});
            }});
        '''
        return self

    def set_filter_button_text(self, text: str) -> 'LogsPageBuilder':
        """
        Set custom filter button text.

        Args:
            text: Button text (default: 'Apply')

        Returns:
            Self for method chaining
        """
        self.page_config.filter_button_text = text
        return self

    def set_custom_js(self, js_code: str) -> 'LogsPageBuilder':
        """
        Add custom JavaScript to the page.

        Args:
            js_code: JavaScript code to include

        Returns:
            Self for method chaining
        """
        self.page_config.custom_js = js_code
        return self

    def validate(self) -> None:
        """
        Validate that all required attributes are set.

        Raises:
            ValueError: If validation fails
        """
        # Check required attributes on page_config
        if not self.page_config.logs_tab:
            raise ValueError(f"logs_tab not set (should be '{self.tab_name}')")

        if not self.page_config.current_url:
            raise ValueError("current_url not set (should be '/logs')")

        if not self.page_config.nav_active:
            raise ValueError(f"nav_active not set (should be 'logs-{self.tab_name}')")

        # Check that table was set
        if not self._table_set:
            raise ValueError("Table data not set - call set_table() before build()")

        # Status message should be set
        if not self.status_message:
            raise ValueError("Status message not set - call set_status_message() before build()")

    def build(self) -> tuple:
        """
        Build and return the page tuple.

        This validates all required attributes are set and returns the standard
        tuple expected by the logs route handler.

        Returns:
            Tuple of (page_config, table_data, pagination, status_message)

        Raises:
            ValueError: If validation fails
        """
        from logging_helper import LoggingHelper, LogType
        logger = LoggingHelper.get_logger(LogType.MAIN)

        # Validate before building
        self.validate()

        # Debug logging for URL generation
        logger.debug(f"[PAGE_BUILDER] LogsPageBuilder.build() - Tab: {self.tab_name}")
        logger.debug(f"[PAGE_BUILDER]   Ingress Path: '{self.ingress_path}'")
        logger.debug(f"[PAGE_BUILDER]   Current URL: '{self.page_config.current_url}'")
        logger.debug(f"[PAGE_BUILDER]   Nav Active: '{self.page_config.nav_active}'")
        if self.pagination:
            logger.debug(f"[PAGE_BUILDER]   Pagination prev_url: '{self.pagination.get('prev_url')}'")
            logger.debug(f"[PAGE_BUILDER]   Pagination next_url: '{self.pagination.get('next_url')}'")
            logger.debug(f"[PAGE_BUILDER]   Page {self.pagination.get('current_page')}/{self.pagination.get('total_pages')}")

        # Return standard tuple
        return (
            self.page_config,
            self.table_data,
            self.pagination,
            self.status_message
        )


class StatsPageBuilder:
    """
    Builder class for stats pages (liked/disliked videos).

    Provides consistent page creation for /stats/liked and /stats/disliked routes.
    """

    def __init__(self, rating_type: str, ingress_path: str):
        """
        Initialize builder for stats page.

        Args:
            rating_type: 'liked' or 'disliked'
            ingress_path: The ingress path from the request
        """
        from helpers.template import create_stats_page_config

        self.rating_type = rating_type
        self.ingress_path = ingress_path
        self.page_config = create_stats_page_config(rating_type, ingress_path)

        # Initialize optional attributes
        self.table_data: Optional[TableData] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self._table_set = False

    def set_title(self, title: str, suffix: Optional[str] = None) -> 'StatsPageBuilder':
        """Set custom page title."""
        self.page_config.title = title
        if suffix:
            self.page_config.title_suffix = suffix
        return self

    def set_empty_state(self, icon: str, title: str, message: str) -> 'StatsPageBuilder':
        """Set empty state display."""
        self.page_config.set_empty_state(icon, title, message)
        return self

    def set_table(self, columns: List[TableColumn], rows: List[TableRow]) -> 'StatsPageBuilder':
        """Set table data."""
        self.table_data = TableData(columns, rows)
        self._table_set = True
        return self

    def set_pagination(
        self,
        current_page: int,
        total_pages: int,
        page_numbers: List[int]
    ) -> 'StatsPageBuilder':
        """Set pagination configuration."""
        if total_pages <= 1:
            self.pagination = None
            return self

        base_url = f"/stats/{self.rating_type}"
        self.pagination = {
            'current_page': current_page,
            'total_pages': total_pages,
            'page_numbers': page_numbers,
            'prev_url': f"{base_url}?page={current_page-1}" if current_page > 1 else None,
            'next_url': f"{base_url}?page={current_page+1}" if current_page < total_pages else None,
            'page_url_template': f"{base_url}?page=PAGE_NUM"
        }
        return self

    def validate(self) -> None:
        """Validate all required attributes are set."""
        if not self.page_config.current_url:
            raise ValueError("current_url not set")

        if not self._table_set:
            raise ValueError("Table data not set - call set_table() before build()")

    def build(self) -> tuple:
        """
        Build and return the page tuple.

        Returns:
            Tuple of (page_config, table_data, pagination)
        """
        self.validate()

        return (
            self.page_config,
            self.table_data,
            self.pagination
        )


class DataViewerPageBuilder:
    """
    Builder class for database viewer page.

    Provides consistent page creation for /data route.
    """

    def __init__(self, ingress_path: str):
        """
        Initialize builder for data viewer page.

        Args:
            ingress_path: The ingress path from the request
        """
        self.ingress_path = ingress_path
        self.page_config = PageConfig('Database Viewer', nav_active='data', storage_key='database-viewer')
        self.page_config.dropdown_section = 'database'
        self.page_config.current_url = '/data'

        # Initialize optional attributes
        self.table_data: Optional[TableData] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self.status_message: str = ''
        self._table_set = False

    def set_title_suffix(self, suffix: str) -> 'DataViewerPageBuilder':
        """Set title suffix."""
        self.page_config.title_suffix = suffix
        return self

    def set_empty_state(self, icon: str, title: str, message: str) -> 'DataViewerPageBuilder':
        """Set empty state display."""
        self.page_config.set_empty_state(icon, title, message)
        return self

    def enable_table_features(
        self,
        sorting: bool = True,
        resizing: bool = True,
        column_toggle: bool = True
    ) -> 'DataViewerPageBuilder':
        """Enable table features."""
        self.page_config.enable_sorting = sorting
        self.page_config.enable_resizing = resizing
        self.page_config.enable_column_toggle = column_toggle
        return self

    def set_table(self, columns: List[TableColumn], rows: List[TableRow]) -> 'DataViewerPageBuilder':
        """Set table data."""
        self.table_data = TableData(columns, rows)
        self._table_set = True
        return self

    def set_pagination(
        self,
        current_page: int,
        total_pages: int,
        sort_by: str,
        sort_order: str,
        columns_param: str
    ) -> 'DataViewerPageBuilder':
        """Set pagination configuration."""
        if total_pages <= 1:
            self.pagination = None
            return self

        self.pagination = {
            'current_page': current_page,
            'total_pages': total_pages,
            'page_numbers': generate_page_numbers(current_page, total_pages),
            'prev_url': f"/data?page={current_page-1}&sort={sort_by}&order={sort_order}&columns={columns_param}",
            'next_url': f"/data?page={current_page+1}&sort={sort_by}&order={sort_order}&columns={columns_param}",
            'page_url_template': f"/data?page=PAGE_NUM&sort={sort_by}&order={sort_order}&columns={columns_param}"
        }
        return self

    def set_status_message(self, message: str) -> 'DataViewerPageBuilder':
        """Set status message."""
        self.status_message = message
        return self

    def validate(self) -> None:
        """Validate all required attributes are set."""
        if not self.page_config.current_url:
            raise ValueError("current_url not set")

        if not self._table_set:
            raise ValueError("Table data not set - call set_table() before build()")

        if not self.status_message:
            raise ValueError("Status message not set - call set_status_message() before build()")

    def build(self) -> tuple:
        """
        Build and return the page tuple.

        Returns:
            Tuple of (page_config, table_data, pagination, status_message)
        """
        self.validate()

        return (
            self.page_config,
            self.table_data,
            self.pagination,
            self.status_message
        )


class ApiCallsPageBuilder:
    """
    Builder class for API calls page (separate route from main logs).

    This provides the same consistency guarantees as LogsPageBuilder
    but for the /logs/api-calls route.
    """

    def __init__(self, ingress_path: str):
        """
        Initialize builder for API calls page.

        Args:
            ingress_path: The ingress path from the request
        """
        from helpers.template import create_api_calls_page_config

        self.ingress_path = ingress_path
        self.page_config = create_api_calls_page_config(ingress_path)

        # Ensure logs_tab is set for navbar highlighting
        self.page_config.logs_tab = 'api-calls'

        # Initialize optional attributes
        self.table_data: Optional[TableData] = None
        self.pagination: Optional[Dict[str, Any]] = None
        self.status_message: str = ''
        self.summary_stats: Optional[Dict[str, Any]] = None

        self._table_set = False

    def add_filter(self, name: str, label: str, options: List[Dict[str, Any]]) -> 'ApiCallsPageBuilder':
        """Add a filter dropdown."""
        self.page_config.add_filter(name, label, options)
        return self

    def set_filter_button_text(self, text: str) -> 'ApiCallsPageBuilder':
        """Set filter button text."""
        self.page_config.filter_button_text = text
        return self

    def set_empty_state(self, icon: str, title: str, message: str) -> 'ApiCallsPageBuilder':
        """Set empty state display."""
        self.page_config.set_empty_state(icon, title, message)
        return self

    def set_table(self, columns: List[TableColumn], rows: List[TableRow]) -> 'ApiCallsPageBuilder':
        """Set table data."""
        self.table_data = TableData(columns, rows)
        self._table_set = True
        return self

    def set_summary_stats(self, stats: Dict[str, Any]) -> 'ApiCallsPageBuilder':
        """Set summary statistics."""
        self.summary_stats = stats
        return self

    def set_pagination(
        self,
        current_page: int,
        total_pages: int,
        page_numbers: List[int],
        query_params: Optional[Dict[str, str]] = None
    ) -> 'ApiCallsPageBuilder':
        """Set pagination configuration."""
        if total_pages <= 1:
            self.pagination = None
            return self

        query_string = ''
        if query_params:
            query_string = '&' + '&'.join(f"{k}={v}" for k, v in query_params.items() if v)

        self.pagination = {
            'current_page': current_page,
            'total_pages': total_pages,
            'page_numbers': page_numbers,
            'prev_url': f"/logs/api-calls?page={current_page-1}{query_string}",
            'next_url': f"/logs/api-calls?page={current_page+1}{query_string}",
            'page_url_template': f"/logs/api-calls?page=PAGE_NUM{query_string}"
        }
        return self

    def set_status_message(self, message: str) -> 'ApiCallsPageBuilder':
        """Set status message."""
        self.status_message = message
        return self

    def validate(self) -> None:
        """Validate all required attributes are set."""
        if not self.page_config.logs_tab:
            raise ValueError("logs_tab not set (should be 'api-calls')")

        if not self._table_set:
            raise ValueError("Table data not set - call set_table() before build()")

        if not self.status_message:
            raise ValueError("Status message not set - call set_status_message() before build()")

    def build(self) -> tuple:
        """
        Build and return the page tuple.

        Returns:
            Tuple of (page_config, table_data, pagination, status_message, summary_stats)
        """
        self.validate()

        return (
            self.page_config,
            self.table_data,
            self.pagination,
            self.status_message,
            self.summary_stats
        )


class QueuePageBuilder:
    """
    Builder class for queue monitor pages.

    This provides the same consistency guarantees as LogsPageBuilder
    but for the /logs/pending-ratings route with its sub-tabs.
    """

    def __init__(self, tab_name: str, ingress_path: str):
        """
        Initialize builder for queue page.

        Args:
            tab_name: The tab identifier ('pending', 'history', 'errors', 'statistics')
            ingress_path: The ingress path from the request
        """
        self.tab_name = tab_name
        self.ingress_path = ingress_path

        # Create page config
        self.page_config = PageConfig(
            title='📊 Queue Monitor',
            nav_active='queue',
            storage_key=f'queue-{tab_name}'
        )

        # Add sub-tabs using helper
        from helpers.template import add_queue_tabs
        add_queue_tabs(self.page_config, tab_name, ingress_path)

        # Initialize optional attributes
        self.table_data: Optional[TableData] = None
        self.status_message: str = ''
        self.summary_stats: Optional[Dict[str, Any]] = None

        self._table_set = False

    def set_empty_state(self, icon: str, title: str, message: str) -> 'QueuePageBuilder':
        """Set empty state display."""
        self.page_config.set_empty_state(icon, title, message)
        return self

    def set_row_click_navigation(self, url_template: str) -> 'QueuePageBuilder':
        """
        Set up row click navigation to detail pages.

        Args:
            url_template: URL template with {id} placeholder

        Returns:
            Self for method chaining
        """
        self.page_config.set_row_click_navigation(url_template)
        return self

    def set_table(self, columns: List[TableColumn], rows: List[TableRow]) -> 'QueuePageBuilder':
        """Set table data."""
        self.table_data = TableData(columns, rows)
        self._table_set = True
        return self

    def set_status_message(self, message: str) -> 'QueuePageBuilder':
        """Set status message."""
        self.status_message = message
        return self

    def set_summary_stats(self, stats: Dict[str, Any]) -> 'QueuePageBuilder':
        """Set summary statistics (for statistics tab)."""
        self.summary_stats = stats
        return self

    def validate(self) -> None:
        """Validate all required attributes are set."""
        # For statistics tab, table is not required (has summary_stats instead)
        if self.tab_name != 'statistics' and not self._table_set:
            raise ValueError("Table data not set - call set_table() before build()")

        if not self.status_message:
            raise ValueError("Status message not set - call set_status_message() before build()")

    def build(self) -> tuple:
        """
        Build and return the page tuple.

        Returns:
            Tuple of (page_config, table_data, status_message) for most tabs
            Tuple of (page_config, table_data, status_message, summary_stats) for statistics tab
        """
        from logging_helper import LoggingHelper, LogType
        logger = LoggingHelper.get_logger(LogType.MAIN)

        # Validate before building
        self.validate()

        # Debug logging
        logger.debug(f"[PAGE_BUILDER] QueuePageBuilder.build() - Tab: {self.tab_name}")
        logger.debug(f"[PAGE_BUILDER]   Ingress Path: '{self.ingress_path}'")
        logger.debug(f"[PAGE_BUILDER]   Nav Active: '{self.page_config.nav_active}'")
        logger.debug(f"[PAGE_BUILDER]   Has Table: {self.table_data is not None}")
        logger.debug(f"[PAGE_BUILDER]   Has Summary Stats: {self.summary_stats is not None}")

        # Return tuple based on tab type
        if self.tab_name == 'statistics':
            return (
                self.page_config,
                None,  # statistics tab doesn't have table
                self.status_message,
                self.summary_stats
            )
        else:
            return (
                self.page_config,
                self.table_data,
                self.status_message
            )

