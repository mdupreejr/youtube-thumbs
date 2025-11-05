"""
Parameter validation helper utilities.

Provides reusable validation logic to eliminate code duplication across routes.
"""
import re
from typing import Tuple, Optional, Union
from flask import Response
from helpers.response_helpers import error_response as create_error_response

# Pre-compiled regex patterns for performance
_YOUTUBE_VIDEO_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{11}$')


def validate_limit_param(
    request_args,
    param_name: str = 'limit',
    default: int = 10,
    min_value: int = 1,
    max_value: int = 100
) -> Tuple[Optional[int], Optional[Response]]:
    """
    Validate and sanitize a numeric limit parameter from request arguments.

    Args:
        request_args: Flask request.args object
        param_name: Name of the parameter to validate (default: 'limit')
        default: Default value if parameter not provided
        min_value: Minimum allowed value (inclusive)
        max_value: Maximum allowed value (inclusive)

    Returns:
        Tuple of (validated_value, error_response)
        - (int, None) if validation succeeds
        - (None, Response) if validation fails

    Usage:
        limit, error = validate_limit_param(request.args, default=10, max_value=100)
        if error:
            return error
        # Use limit safely...

    Examples:
        >>> # Valid input
        >>> limit, error = validate_limit_param(request.args)
        >>> # limit = 10 (default), error = None

        >>> # Out of bounds (gets clamped)
        >>> # request.args.get('limit') = '200'
        >>> limit, error = validate_limit_param(request.args, max_value=100)
        >>> # limit = 100, error = None

        >>> # Invalid input
        >>> # request.args.get('limit') = 'abc'
        >>> limit, error = validate_limit_param(request.args)
        >>> # limit = None, error = <Response with 400 status>
    """
    try:
        value = int(request_args.get(param_name, default))
        # Clamp to valid range
        value = max(min_value, min(value, max_value))
        return value, None
    except (ValueError, TypeError):
        return None, create_error_response(f'Invalid {param_name} parameter')


def validate_page_param(
    request_args,
    param_name: str = 'page',
    default: int = 1,
    max_page: int = 10000
) -> Tuple[Optional[int], Optional[Response]]:
    """
    Validate and sanitize a page number parameter from request arguments.

    Args:
        request_args: Flask request.args object
        param_name: Name of the parameter to validate (default: 'page')
        default: Default value if parameter not provided (default: 1)
        max_page: Maximum allowed page number to prevent DoS (default: 10000)

    Returns:
        Tuple of (validated_value, error_response)
        - (int, None) if validation succeeds
        - (None, Response) if validation fails

    Usage:
        page, error = validate_page_param(request.args)
        if error:
            return error
        # Use page safely...

    Examples:
        >>> # Valid input
        >>> page, error = validate_page_param(request.args)
        >>> # page = 1 (default), error = None

        >>> # Valid page number
        >>> # request.args.get('page') = '5'
        >>> page, error = validate_page_param(request.args)
        >>> # page = 5, error = None

        >>> # Invalid input (less than 1)
        >>> # request.args.get('page') = '0'
        >>> page, error = validate_page_param(request.args)
        >>> # page = None, error = <Response with 400 status>

        >>> # Invalid input (not a number)
        >>> # request.args.get('page') = 'abc'
        >>> page, error = validate_page_param(request.args)
        >>> # page = None, error = <Response with 400 status>
    """
    # Get raw value and handle None/empty explicitly
    raw_value = request_args.get(param_name)
    if raw_value is None or raw_value == '':
        return default, None

    try:
        value = int(raw_value)
        if value < 1:
            return None, create_error_response(f'{param_name.capitalize()} must be at least 1')
        # SECURITY: Prevent DoS by limiting maximum page number
        if value > max_page:
            return None, create_error_response(f'{param_name.capitalize()} exceeds maximum allowed value of {max_page}')
        return value, None
    except (ValueError, TypeError):
        return None, create_error_response(f'Invalid {param_name} parameter: must be a positive integer')


def validate_youtube_video_id(video_id: str) -> Tuple[bool, Optional[Tuple[Response, int]]]:
    """
    Validate YouTube video ID format for security.

    YouTube video IDs are exactly 11 characters long and can only contain
    alphanumeric characters, hyphens, and underscores.

    Args:
        video_id: The video ID to validate

    Returns:
        Tuple of (is_valid, error_response)
        - (True, None) if validation succeeds
        - (False, Response) if validation fails

    Usage:
        is_valid, error = validate_youtube_video_id(video_id)
        if not is_valid:
            return error
        # Use video_id safely...

    Examples:
        >>> # Valid video ID
        >>> is_valid, error = validate_youtube_video_id('dQw4w9WgXcQ')
        >>> # is_valid = True, error = None

        >>> # Invalid: too short
        >>> is_valid, error = validate_youtube_video_id('short')
        >>> # is_valid = False, error = <Response with 400 status>

        >>> # Invalid: contains invalid characters
        >>> is_valid, error = validate_youtube_video_id('dQw4w9WgX@Q')
        >>> # is_valid = False, error = <Response with 400 status>

        >>> # Invalid: None or wrong type
        >>> is_valid, error = validate_youtube_video_id(None)
        >>> # is_valid = False, error = <Response with 400 status>
    """
    # Validate type and None
    if not video_id or not isinstance(video_id, str):
        return False, create_error_response('Invalid video ID format')

    # Validate format using pre-compiled regex (performance optimization)
    if not _YOUTUBE_VIDEO_ID_PATTERN.match(video_id):
        return False, create_error_response('Invalid video ID format')

    return True, None
