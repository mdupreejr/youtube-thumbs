"""
Decorators for simplifying repetitive patterns in the codebase.
"""
from functools import wraps
from typing import Any, Callable
from googleapiclient.errors import HttpError
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)
from quota_error import (
    QuotaExceededError,
    VideoNotFoundError,
    AuthenticationError,
    NetworkError,
    InvalidRequestError,
    YouTubeAPIError
)

# Will be set by youtube_api module
_db = None


def handle_youtube_error(context: str, api_method: str = None, quota_cost: int = 0):
    """
    Decorator to convert YouTube API HttpErrors to specific exception types.

    IMPORTANT: This decorator does NOT suppress errors - it converts them to
    specific types so callers can handle them appropriately. All errors are logged.

    Args:
        context: Description of the operation for logging
        api_method: Optional API method name (e.g., "videos.rate") for database logging
        quota_cost: Optional quota cost for this API call (for database logging)

    Raises:
        QuotaExceededError: When API quota is exhausted
        VideoNotFoundError: When video doesn't exist (404)
        AuthenticationError: When credentials are invalid (401, 403)
        NetworkError: When server/network issues occur (5xx, timeouts)
        InvalidRequestError: When request is malformed (400)
        YouTubeAPIError: For other YouTube API errors
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                result = func(self, *args, **kwargs)

                # v4.0.26: Log successful API calls (not just failures!)
                if api_method and _db:
                    _db.record_api_call(api_method, success=True, quota_cost=quota_cost)
                    _db.log_api_call_detailed(
                        api_method=api_method,
                        operation_type=context,
                        query_params=str(args[0]) if args else None,
                        quota_cost=quota_cost,
                        success=True,
                        error_message=None,
                        results_count=None,
                        context=context
                    )

                return result

            except YouTubeAPIError:
                # Already converted to specific type - just re-raise
                raise

            except HttpError as e:
                status_code = e.resp.status if hasattr(e, 'resp') else None

                # Build descriptive error message
                error_context = f"{context}"
                if args:
                    error_context += f" | {args[0]}"

                # Check for quota error first
                detail = self._quota_error_detail(e) if hasattr(self, '_quota_error_detail') else None
                if detail:
                    logger.error(f"Quota exceeded: {error_context}")
                    # v4.0.13: Record quota error to BOTH aggregate and detailed logs
                    # Aggregate: quota_cost=1 for visibility (shows call was made)
                    # Detailed: quota_cost=0 for accuracy (YouTube didn't charge us)
                    if api_method and _db:
                        _db.record_api_call(api_method, success=False, quota_cost=1, error_message="Quota exceeded")
                        _db.log_api_call_detailed(
                            api_method=api_method,
                            operation_type=context,
                            query_params=str(args[0]) if args else None,
                            quota_cost=0,
                            success=False,
                            error_message="Quota exceeded",
                            context=error_context
                        )
                    raise QuotaExceededError("YouTube API quota exceeded")

                # v4.0.13: Record API call error to BOTH aggregate and detailed logs
                # Aggregate: quota_cost=1 for visibility (shows call was made)
                # Detailed: quota_cost=0 for accuracy (YouTube didn't charge us)
                error_msg = f"{context} | Status: {status_code}"
                if api_method and _db:
                    _db.record_api_call(api_method, success=False, quota_cost=1, error_message=error_msg)
                    _db.log_api_call_detailed(
                        api_method=api_method,
                        operation_type=context,
                        query_params=str(args[0]) if args else None,
                        quota_cost=0,
                        success=False,
                        error_message=error_msg,
                        context=error_context
                    )

                # Convert based on status code
                if status_code == 404:
                    video_id = args[0] if args else "unknown"
                    logger.warning(f"Video not found: {error_context}")
                    raise VideoNotFoundError(video_id, f"Video not found: {error_context}")

                elif status_code in (401, 403):
                    logger.error(f"Authentication failed: {error_context} | Status: {status_code}")
                    raise AuthenticationError(f"Authentication failed: {error_context}")

                elif status_code >= 500:
                    logger.warning(f"YouTube server error: {error_context} | Status: {status_code}")
                    raise NetworkError(f"YouTube server error {status_code}: {error_context}")

                elif status_code == 400:
                    logger.error(f"Invalid request: {error_context} | Error: {str(e)}")
                    raise InvalidRequestError(f"Invalid request: {error_context}")

                else:
                    # Unknown HTTP error - log and raise as generic YouTube API error
                    logger.error(f"YouTube API error: {error_context} | Status: {status_code} | Error: {str(e)}")
                    raise YouTubeAPIError(f"YouTube API error {status_code}: {error_context}")

            except Exception as e:
                # Unexpected non-HTTP error - log and re-raise (don't suppress!)
                error_msg = f"Unexpected error in {context}"
                if args:
                    error_msg += f" | {args[0]}"
                logger.error(f"{error_msg}: {str(e)}")
                raise

        return wrapper
    return decorator


