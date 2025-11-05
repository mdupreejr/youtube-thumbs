"""
Helper utilities for YouTube Thumbs addon.
Centralizes common patterns to reduce code duplication.
"""

# Export all helpers for easy importing
from .cache_helpers import find_cached_video
from .search_helpers import search_and_match_video
from .rating_helpers import (
    check_rate_limit,
    validate_current_media,
    check_youtube_content,
    find_or_search_video,
    update_database_for_rating,
    check_already_rated,
    handle_quota_blocked_rating,
    execute_rating
)
from .video_helpers import (
    is_youtube_content,
    get_video_title,
    get_video_artist,
    prepare_video_upsert,
    get_content_hash
)
from .pagination_helpers import generate_page_numbers
from .response_helpers import error_response, success_response
from .time_helpers import format_relative_time, parse_timestamp
from .validation_helpers import validate_page_param

__all__ = [
    # Cache helpers
    'find_cached_video',
    # Search helpers
    'search_and_match_video',
    # Rating helpers
    'check_rate_limit',
    'validate_current_media',
    'check_youtube_content',
    'find_or_search_video',
    'update_database_for_rating',
    'check_already_rated',
    'handle_quota_blocked_rating',
    'execute_rating',
    # Video helpers
    'is_youtube_content',
    'get_video_title',
    'get_video_artist',
    'prepare_video_upsert',
    'get_content_hash',
    # Pagination helpers
    'generate_page_numbers',
    # Response helpers
    'error_response',
    'success_response',
    # Time helpers
    'format_relative_time',
    'parse_timestamp',
    # Validation helpers
    'validate_page_param',
]
