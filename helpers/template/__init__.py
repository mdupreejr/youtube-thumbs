"""
Template helpers for the unified table viewer.

This module provides utilities to format data for the table_viewer.html template.
All functions and classes are re-exported for backward compatibility.
"""

# Data structures
from .data_structures import (
    TableColumn,
    TableCell,
    TableRow,
    TableData,
    PageConfig
)

# Formatters
from .formatters import (
    format_badge,
    format_time_ago,
    format_youtube_link,
    format_song_display,
    format_status_badge,
    format_rating_badge,
    format_log_level_badge,
    format_count_message,
    pluralize,
    truncate_text
)

# Filters and page configurations
from .filters import (
    create_filter_option,
    create_period_filter,
    create_rating_filter,
    create_status_filter,
    create_logs_page_config,
    create_queue_page_config,
    create_api_calls_page_config,
    create_stats_page_config,
    add_queue_tabs,
    get_video_table_columns
)

# Sanitization
from .sanitization import (
    sanitize_html
)

# Rendering
from .rendering import (
    render_table_page,
    create_pagination_info,
    create_status_message
)

# Table helpers
from .table_helpers import (
    build_video_table_rows
)

__all__ = [
    # Data structures
    'TableColumn',
    'TableCell',
    'TableRow',
    'TableData',
    'PageConfig',
    # Formatters
    'format_badge',
    'format_time_ago',
    'format_youtube_link',
    'format_song_display',
    'format_status_badge',
    'format_rating_badge',
    'format_log_level_badge',
    'format_count_message',
    'pluralize',
    'truncate_text',
    # Filters and page configurations
    'create_filter_option',
    'create_period_filter',
    'create_rating_filter',
    'create_status_filter',
    'create_logs_page_config',
    'create_queue_page_config',
    'create_api_calls_page_config',
    'create_stats_page_config',
    'add_queue_tabs',
    'get_video_table_columns',
    # Sanitization
    'sanitize_html',
    # Rendering
    'render_table_page',
    'create_pagination_info',
    'create_status_message',
    # Table helpers
    'build_video_table_rows',
]
