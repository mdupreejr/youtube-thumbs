"""
Decorators for simplifying repetitive patterns in the codebase.
"""
from functools import wraps
from typing import Any, Optional, Callable
from googleapiclient.errors import HttpError
from logger import logger
from quota_guard import quota_guard
from error_handler import log_and_suppress
import sqlite3
import json
import fcntl


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
                if detail is not None:
                    quota_guard.trip('quotaExceeded', context=context, detail=detail)

                # Build error message with context
                error_msg = f"YouTube API error in {context}"
                if args:
                    # Add first argument (usually ID or query) to error message
                    error_msg += f" | {args[0]}"

                return log_and_suppress(
                    e, error_msg,
                    level="error",
                    return_value=return_value
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


def handle_database_error(operation: str, critical: bool = False):
    """
    Decorator to handle database errors consistently.

    Args:
        operation: Description of the database operation
        critical: If True, re-raises the exception after logging
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except sqlite3.DatabaseError as exc:
                error_msg = f"Failed to {operation}"
                if args:
                    error_msg += f" | {args[0]}"

                if critical:
                    logger.error(error_msg + f": {exc}")
                    raise
                else:
                    log_and_suppress(exc, error_msg, level="error")
        return wrapper
    return decorator


def with_file_lock(lock_timeout: int = 10):
    """
    Decorator to handle file locking operations.

    Args:
        lock_timeout: Maximum seconds to wait for lock
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, 'state_file'):
                return func(self, *args, **kwargs)

            try:
                with self.state_file.open('r+', encoding='utf-8') as handle:
                    # Acquire exclusive lock
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        # Pass the file handle to the function
                        return func(self, handle, *args, **kwargs)
                    finally:
                        # Always release the lock
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                logger.error(f"File operation failed in {func.__name__}: %s", exc)
                return None
        return wrapper
    return decorator


def data_driven_scoring(scoring_rules: list):
    """
    Decorator to apply data-driven scoring rules.
    Simplifies repetitive if/elif scoring patterns.

    Args:
        scoring_rules: List of (condition_func, score_penalty, warning_message) tuples
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Get the base stats needed for scoring
            stats = func(self, *args, **kwargs)

            score = 100
            warnings = []

            for condition_func, penalty, warning_template in scoring_rules:
                value = condition_func(stats)
                if value is not None:
                    score -= penalty
                    warning = warning_template.format(value=value)
                    warnings.append(warning)

            return max(0, score), warnings
        return wrapper
    return decorator


def cache_result(ttl_seconds: int = 60):
    """
    Simple caching decorator for expensive operations.

    Args:
        ttl_seconds: Time-to-live for cached results
    """
    def decorator(func: Callable) -> Callable:
        cache = {}
        cache_time = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            import time

            # Create cache key from arguments
            cache_key = str(args) + str(kwargs)
            current_time = time.time()

            # Check if cached result exists and is still valid
            if cache_key in cache:
                if current_time - cache_time[cache_key] < ttl_seconds:
                    return cache[cache_key]

            # Compute result and cache it
            result = func(*args, **kwargs)
            cache[cache_key] = result
            cache_time[cache_key] = current_time

            # Clean old cache entries
            for key in list(cache.keys()):
                if current_time - cache_time[key] >= ttl_seconds:
                    del cache[key]
                    del cache_time[key]

            return result
        return wrapper
    return decorator