"""
Decorators for simplifying repetitive patterns in the codebase.
"""
from functools import wraps
from typing import Any, Callable
from googleapiclient.errors import HttpError
from logger import logger
from error_handler import log_and_suppress
from quota_error import QuotaExceededError


def handle_youtube_error(context: str, return_value: Any = None):
    """
    Decorator to handle YouTube API errors consistently.
    Eliminates duplicate try/except blocks across API methods.

    Args:
        context: Description of the operation for logging
        return_value: Value to return on error
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except HttpError as e:
                # Check if it's a quota error
                detail = self._quota_error_detail(e) if hasattr(self, '_quota_error_detail') else None
                is_quota_error = detail is not None
                if is_quota_error:
                    # Raise QuotaExceededError - worker will catch and sleep
                    raise QuotaExceededError(f"YouTube quota exceeded during {context}: {detail}")

                # Build error message with context
                error_msg = f"YouTube API error in {context}"
                if args:
                    # Add first argument (usually ID or query) to error message
                    error_msg += f" | {args[0]}"

                return log_and_suppress(
                    e, error_msg,
                    level="error",
                    return_value=return_value,
                    log_traceback=not is_quota_error  # Skip traceback for quota errors
                )
            except Exception as e:
                error_msg = f"Unexpected error in {context}"
                if args:
                    error_msg += f" | {args[0]}"

                return log_and_suppress(
                    e, error_msg,
                    level="error",
                    return_value=return_value
                )
        return wrapper
    return decorator


