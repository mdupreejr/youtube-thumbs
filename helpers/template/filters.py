"""
Filter creation functions for the unified table viewer.

Provides utilities to create filter configurations and page configurations.
"""

from typing import Dict, Any, List
from .data_structures import PageConfig, TableColumn


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
