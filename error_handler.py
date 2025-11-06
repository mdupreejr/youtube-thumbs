"""
Standardized error handling utilities for consistent error management.
"""

import json
from typing import Optional, Any, Callable
from functools import wraps
from logger import logger


class YouTubeThumbsError(Exception):
    """Base exception for all YouTube Thumbs errors."""
    pass


class DatabaseError(YouTubeThumbsError):
    """Database-related errors."""
    pass


class APIError(YouTubeThumbsError):
    """API-related errors (YouTube or Home Assistant)."""
    pass


class ValidationError(YouTubeThumbsError):
    """Data validation errors."""
    pass


class ConfigurationError(YouTubeThumbsError):
    """Configuration-related errors."""
    pass


def _extract_clean_error_message(exc: Exception) -> str:
    """
    Extract a clean, human-readable error message from an exception.
    
    For HttpError exceptions from Google API, this extracts the actual error
    message instead of returning HTML error pages.
    
    Args:
        exc: The exception to extract message from
        
    Returns:
        Clean error message string
    """
    # Try to import HttpError to check type safely
    try:
        from googleapiclient.errors import HttpError
        is_http_error = isinstance(exc, HttpError)
    except ImportError:
        # googleapiclient not available, fall back to type name check
        is_http_error = type(exc).__name__ == 'HttpError'
    
    if is_http_error:
        try:
            # Try to extract error from content attribute
            content = getattr(exc, 'content', None)
            if isinstance(content, bytes):
                try:
                    content = content.decode('utf-8')
                except UnicodeDecodeError:
                    content = None
            
            if isinstance(content, str):
                try:
                    payload = json.loads(content)
                    error_payload = payload.get('error', {})
                    
                    # Extract the first error message if available
                    errors = error_payload.get('errors', [])
                    if errors and isinstance(errors, list):
                        first_error = errors[0]
                        message = first_error.get('message')
                        if message:
                            return message
                    
                    # Fallback to main error message
                    message = error_payload.get('message')
                    if message:
                        return message
                except json.JSONDecodeError:
                    pass
            
            # Try to get status and reason from resp attribute
            resp = getattr(exc, 'resp', None)
            if resp:
                status = getattr(resp, 'status', None)
                reason = getattr(resp, 'reason', None)
                if status and reason:
                    return f"HTTP {status}: {reason}"
                elif reason:
                    return reason
        except (AttributeError, TypeError) as e:
            # Log extraction failure for debugging but continue to fallback
            logger.debug("Failed to extract clean message from HttpError: %s", e)
    
    # For all other exceptions or if extraction failed, use str()
    return str(exc)


def log_and_suppress(
    exc: Exception,
    message: str,
    *args,
    level: str = "error",
    return_value: Any = None,
    log_traceback: bool = True
) -> Any:
    """
    Log an exception with context and return a default value.

    Args:
        exc: The exception to log
        message: Log message with format placeholders
        *args: Arguments for message formatting
        level: Log level (error, warning, debug)
        return_value: Value to return after logging
        log_traceback: Whether to log full traceback (default True)

    Returns:
        The specified return_value
    """
    log_func = getattr(logger, level, logger.error)
    clean_error_msg = _extract_clean_error_message(exc)
    log_func(f"{message}: {clean_error_msg}", *args)
    if log_traceback:
        logger.debug("Exception details", exc_info=True)
    return return_value


def log_and_reraise(
    exc: Exception,
    message: str,
    *args,
    level: str = "error",
    as_type: Optional[type] = None
) -> None:
    """
    Log an exception with context and re-raise it.

    Args:
        exc: The exception to log
        message: Log message with format placeholders
        *args: Arguments for message formatting
        level: Log level (error, warning, critical)
        as_type: Optional exception type to raise instead

    Raises:
        The original exception or as_type if specified
    """
    log_func = getattr(logger, level, logger.error)
    clean_error_msg = _extract_clean_error_message(exc)
    log_func(f"{message}: {clean_error_msg}", *args)
    logger.debug("Exception details", exc_info=True)

    if as_type:
        raise as_type(f"{message}: {clean_error_msg}") from exc
    raise


def validate_environment_variable(
    var_name: str,
    default: Any,
    validator: Optional[Callable[[Any], bool]] = None,
    converter: Optional[Callable[[str], Any]] = None
) -> Any:
    """
    Safely get and validate an environment variable.

    Args:
        var_name: Name of the environment variable
        default: Default value if not set or invalid
        validator: Optional validation function
        converter: Optional conversion function (e.g., int, float)

    Returns:
        The validated and converted environment variable value
    """
    import os

    raw_value = os.getenv(var_name)

    if raw_value is None:
        logger.debug(f"Environment variable {var_name} not set, using default: {default}")
        return default

    # Try to convert the value
    if converter:
        try:
            value = converter(raw_value)
        except (ValueError, TypeError) as exc:
            logger.warning(
                f"Invalid {var_name}='{raw_value}': {exc}. Using default: {default}"
            )
            return default
    else:
        value = raw_value

    # Validate the converted value
    if validator and not validator(value):
        logger.warning(
            f"Invalid {var_name}='{value}' failed validation. Using default: {default}"
        )
        return default

    logger.debug(f"Using {var_name}={value}")
    return value


def safe_db_operation(
    operation_name: str,
    return_on_error: Any = None
) -> Callable:
    """
    Simple decorator for database operations that should not crash the app.

    Args:
        operation_name: Name of the operation for logging
        return_on_error: What to return if operation fails

    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                # Extract meaningful context from args if possible
                context = ""
                if args and hasattr(args[0], '__class__'):
                    context = f" in {args[0].__class__.__name__}"

                logger.error(
                    f"Failed to {operation_name}{context}: {exc}"
                )
                logger.debug("Full traceback", exc_info=True)
                return return_on_error
        return wrapper
    return decorator