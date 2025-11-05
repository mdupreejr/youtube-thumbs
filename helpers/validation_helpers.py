"""
Parameter validation helper utilities.

Provides reusable validation logic to eliminate code duplication across routes.
"""
from typing import Tuple, Optional
from flask import jsonify, Response, make_response


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
        error_response = make_response(jsonify({
            'success': False,
            'error': f'Invalid {param_name} parameter'
        }), 400)
        return None, error_response
