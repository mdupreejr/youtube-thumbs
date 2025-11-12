"""
Quota error detection and analysis for YouTube API.

This module handles detection of quota-related errors from YouTube API responses.
"""

import json
from typing import Optional
from googleapiclient.errors import HttpError


# YouTube API quota-related error codes
QUOTA_REASON_CODES = {
    'quotaExceeded',
    'rateLimitExceeded',
    'userRateLimitExceeded',
    'dailyLimitExceeded',
    'dailyLimitExceededUnreg',
    'limitExceeded',
    'usageLimits.rateLimitExceeded',
}

QUOTA_REASON_TOKENS = tuple(code.lower() for code in QUOTA_REASON_CODES)
QUOTA_MESSAGE_KEYWORDS = ('quota', 'rate limit', 'ratelimit', 'limit exceeded')


def _message_indicates_quota(message: Optional[str]) -> bool:
    """Check if error message indicates quota issue."""
    if not message:
        return False
    lowered = message.lower()
    return any(keyword in lowered for keyword in QUOTA_MESSAGE_KEYWORDS)


def _text_matches_reason(text: Optional[str]) -> Optional[str]:
    """Check if text contains quota-related reason tokens."""
    if not text:
        return None
    lowered = text.lower()
    for token in QUOTA_REASON_TOKENS:
        if token in lowered:
            return text
    return None


def quota_error_detail(error: HttpError) -> Optional[str]:
    """
    Extract detailed quota error information from HttpError.

    Analyzes the error response to determine if it's quota-related and
    extracts a meaningful error message.

    Args:
        error: HttpError from YouTube API

    Returns:
        Error message if quota-related, None otherwise
    """
    content = getattr(error, 'content', None)
    if isinstance(content, bytes):
        try:
            content = content.decode('utf-8')
        except Exception:
            content = None
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = None
    else:
        payload = None

    if payload:
        error_payload = payload.get('error', {})
        for item in error_payload.get('errors', []):
            reason = item.get('reason')
            match = _text_matches_reason(reason)
            if match:
                return item.get('message') or error_payload.get('message') or match
        message = error_payload.get('message')
        if _message_indicates_quota(message):
            return message

    resp = getattr(error, 'resp', None)
    if resp:
        resp_reason = getattr(resp, 'reason', None)
        match = _text_matches_reason(resp_reason)
        if match:
            return match

    text = str(error)
    match = _text_matches_reason(text)
    if match:
        return match
    if _message_indicates_quota(text):
        return text
    return None
