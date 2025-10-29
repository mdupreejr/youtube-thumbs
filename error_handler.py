"""
Standardized error handling utilities for consistent error management.
"""

from typing import Optional, Any, Callable
from functools import wraps
import sqlite3
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


def log_and_suppress(
    exc: Exception,
    message: str,
    *args,
    level: str = "error",
    return_value: Any = None
) -> Any:
    """
    Log an exception with context and return a default value.

    Args:
        exc: The exception to log
        message: Log message with format placeholders
        *args: Arguments for message formatting
        level: Log level (error, warning, debug)
        return_value: Value to return after logging

    Returns:
        The specified return_value
    """
    log_func = getattr(logger, level, logger.error)
    log_func(f"{message}: {exc}", *args)
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
    log_func(f"{message}: {exc}", *args)
    logger.debug("Exception details", exc_info=True)

    if as_type:
        raise as_type(f"{message}: {exc}") from exc
    raise


def handle_database_error(
    operation: str,
    critical: bool = False
) -> Callable:
    """
    Decorator for consistent database error handling.

    Args:
        operation: Description of the database operation
        critical: Whether this is a critical operation that should re-raise

    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except sqlite3.DatabaseError as exc:
                error_msg = f"Database {operation} failed"

                # Critical errors should be re-raised
                if critical or "no such table" in str(exc).lower():
                    log_and_reraise(
                        exc, error_msg,
                        level="critical" if critical else "error",
                        as_type=DatabaseError
                    )

                # Non-critical errors can be suppressed with proper logging
                return log_and_suppress(
                    exc, error_msg,
                    level="error",
                    return_value=None if func.__name__ != 'record_play' else False
                )
            except Exception as exc:
                # Unexpected errors should always be logged
                return log_and_suppress(
                    exc, f"Unexpected error during {operation}",
                    level="error",
                    return_value=None if func.__name__ != 'record_play' else False
                )
        return wrapper
    return decorator


def handle_api_error(
    api_name: str,
    operation: str,
    default_return: Any = None
) -> Callable:
    """
    Decorator for consistent API error handling.

    Args:
        api_name: Name of the API (YouTube, Home Assistant)
        operation: Description of the API operation
        default_return: Default value to return on error

    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                # Check for quota errors (critical)
                if 'quota' in str(exc).lower():
                    log_and_suppress(
                        exc, f"{api_name} API quota exceeded during {operation}",
                        level="critical",
                        return_value=default_return
                    )
                    # Could trigger quota guard here
                    return default_return

                # Check for auth errors (critical)
                if any(word in str(exc).lower() for word in ['auth', 'credential', 'token']):
                    log_and_reraise(
                        exc, f"{api_name} API authentication failed during {operation}",
                        level="critical",
                        as_type=APIError
                    )

                # Other API errors are logged but not critical
                return log_and_suppress(
                    exc, f"{api_name} API error during {operation}",
                    level="error",
                    return_value=default_return
                )
        return wrapper
    return decorator


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