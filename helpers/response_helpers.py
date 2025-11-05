"""
Response formatting helper utilities.

Provides standardized JSON response creation to ensure consistent API responses
and eliminate code duplication across routes.
"""
from typing import Any, Dict, Optional, Tuple
from flask import jsonify, Response


def error_response(
    message: str,
    status_code: int = 400,
    extra_data: Optional[Dict[str, Any]] = None
) -> Tuple[Response, int]:
    """
    Create a standardized error response.

    Args:
        message: Error message to return to client
        status_code: HTTP status code (default: 400)
        extra_data: Optional additional data to include in response

    Returns:
        Tuple of (Response, status_code)

    Usage:
        return error_response("Invalid video ID", 400)
        return error_response("Not found", 404, {"video_id": video_id})

    Examples:
        >>> error_response("Invalid parameter")
        (<Response 400>, 400)

        >>> error_response("Not found", 404)
        (<Response 404>, 404)

        >>> error_response("Failed", 500, {"detail": "DB error"})
        (<Response 500>, 500)
    """
    response_data = {
        'success': False,
        'error': message
    }

    if extra_data:
        response_data.update(extra_data)

    return jsonify(response_data), status_code


def success_response(
    data: Optional[Any] = None,
    message: Optional[str] = None,
    status_code: int = 200
) -> Tuple[Response, int]:
    """
    Create a standardized success response.

    Always merges dict fields at top level for consistent API responses.
    Non-dict data is wrapped in a 'data' key.

    Args:
        data: Data to return (dict fields merged at top level, non-dicts wrapped in 'data')
        message: Optional success message
        status_code: HTTP status code (default: 200)

    Returns:
        Tuple of (Response, status_code)

    Usage:
        return success_response({"video_id": "abc123"})  # Merges video_id at top level
        return success_response(None, "Rating submitted successfully")
        return success_response(videos_list, "Found 10 videos")  # Wraps list in 'data'

    Examples:
        >>> success_response({"count": 5})
        # Returns: {'success': True, 'count': 5}

        >>> success_response(None, "Operation complete")
        # Returns: {'success': True, 'message': 'Operation complete'}

        >>> success_response([1, 2, 3], "Results")
        # Returns: {'success': True, 'message': 'Results', 'data': [1, 2, 3]}
    """
    response_data = {'success': True}

    if message:
        response_data['message'] = message

    if data is not None:
        # Consistent behavior: merge dicts at top level, wrap non-dicts in 'data'
        if isinstance(data, dict):
            response_data.update(data)
        else:
            response_data['data'] = data

    return jsonify(response_data), status_code
