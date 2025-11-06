"""
Helper functions and decorators for API endpoints.
Consolidates repeated patterns in route handlers.
"""
import traceback
from functools import wraps
from typing import Callable, Optional, Tuple, Any
from flask import request, jsonify, Response
from logger import logger
from helpers.response_helpers import error_response


def api_endpoint(
    db_method_name: str,
    param_validator: Optional[Callable] = None,
    error_message: str = "Failed to retrieve data",
    custom_params_builder: Optional[Callable] = None
):
    """
    Decorator for standard API endpoints that follow the pattern:
    1. Validate parameters (optional)
    2. Call database method
    3. Return JSON response with standard format
    4. Handle errors consistently

    Args:
        db_method_name: Name of the database method to call (e.g., 'get_most_played')
        param_validator: Optional function to validate/extract parameters from request.args
                        Should return (param_value, error_response) tuple
        error_message: Custom error message for failures
        custom_params_builder: Optional function to build custom parameters for db method
                              Takes request.args, returns tuple of args for db method

    Example usage:
        @bp.route('/stats/most-played', methods=['GET'])
        @api_endpoint('get_most_played',
                     param_validator=lambda args: validate_limit_param(args, default=10, max_value=100),
                     error_message='Failed to retrieve most played statistics')
        def get_most_played_stats(db):
            pass  # Decorator handles everything
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # Get database instance from the blueprint's module-level variable
                import sys
                # Get the module where the decorated function is defined
                func_module = sys.modules[func.__module__]
                db = getattr(func_module, 'db', None)

                if db is None:
                    logger.error(f"Database not initialized for {func.__name__}")
                    return error_response("Database not available", 500)

                # Validate parameters if validator provided
                param_value = None
                if param_validator:
                    param_value, error = param_validator(request.args)
                    if error:
                        return error

                # Build custom parameters if builder provided
                if custom_params_builder:
                    params = custom_params_builder(request.args)
                    # Call database method with custom params
                    db_method = getattr(db, db_method_name)
                    if isinstance(params, tuple):
                        result = db_method(*params)
                    else:
                        result = db_method(params)
                elif param_value is not None:
                    # Call database method with validated parameter
                    db_method = getattr(db, db_method_name)
                    result = db_method(param_value)
                else:
                    # Call database method with no parameters
                    db_method = getattr(db, db_method_name)
                    result = db_method()

                return jsonify({'success': True, 'data': result})

            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                return error_response(error_message, 500)

        return wrapper
    return decorator


def stats_endpoint(db_method_name: str, limit_default: int = 10, limit_max: int = 100, error_message: str = None):
    """
    Specialized decorator for stats endpoints with limit parameter.

    Args:
        db_method_name: Name of the database method to call
        limit_default: Default limit value
        limit_max: Maximum limit value
        error_message: Custom error message (auto-generated if not provided)
    """
    from helpers.validation_helpers import validate_limit_param

    if error_message is None:
        error_message = f"Failed to retrieve {db_method_name.replace('_', ' ')}"

    return api_endpoint(
        db_method_name=db_method_name,
        param_validator=lambda args: validate_limit_param(args, default=limit_default, max_value=limit_max),
        error_message=error_message
    )


def simple_stats_endpoint(db_method_name: str, error_message: str = None):
    """
    Specialized decorator for simple stats endpoints with no parameters.

    Args:
        db_method_name: Name of the database method to call
        error_message: Custom error message (auto-generated if not provided)
    """
    if error_message is None:
        error_message = f"Failed to retrieve {db_method_name.replace('_', ' ')}"

    return api_endpoint(
        db_method_name=db_method_name,
        error_message=error_message
    )


def test_endpoint(endpoint_name: str, test_function: Callable, *test_args):
    """
    Wrapper for system test endpoints with standard error handling and logging.
    Eliminates duplicate try/except/logging boilerplate across test endpoints.

    Args:
        endpoint_name: Short name for the test (e.g., 'youtube', 'ha', 'db')
        test_function: Function to call for testing, should return (success: bool, message: str)
        *test_args: Arguments to pass to the test function

    Returns:
        Flask Response with JSON containing success and message fields

    Example:
        @bp.route('/test/youtube')
        def test_youtube() -> Response:
            return test_endpoint('youtube', _check_youtube_api, _get_youtube_api(), None, _db)
    """
    logger.debug(f"=== /test/{endpoint_name} endpoint called ===")
    try:
        success, message = test_function(*test_args)
        logger.debug(f"{endpoint_name} test result: success={success}, message={message}")
        response = jsonify({"success": success, "message": message})
        logger.debug(f"Returning JSON response: {response.get_json()}")
        return response
    except Exception as e:
        logger.error(f"=== ERROR in /test/{endpoint_name} endpoint ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": f"Error testing {endpoint_name} connection"})
