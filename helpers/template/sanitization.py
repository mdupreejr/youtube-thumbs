"""
HTML sanitization functions for the unified table viewer.

Provides utilities to sanitize HTML content to prevent XSS attacks.
"""

import re


def sanitize_html(html_content: str) -> str:
    """
    Sanitize HTML content to prevent XSS attacks.

    This function allows only safe HTML tags and attributes while stripping
    potentially dangerous content.

    Args:
        html_content: Raw HTML content to sanitize

    Returns:
        Sanitized HTML content safe for rendering
    """
    if not html_content:
        return ''

    # Try to use bleach if available, otherwise fall back to basic cleaning
    try:
        import bleach

        # Define allowed tags and attributes for safe HTML
        allowed_tags = ['a', 'span', 'strong', 'em', 'br', 'small', 'code', 'pre']
        allowed_attributes = {
            'a': ['href', 'target', 'rel', 'title'],
            'span': ['class', 'title', 'style'],
            '*': ['class', 'title']
        }

        # Define allowed protocols for links
        allowed_protocols = ['http', 'https', 'mailto']

        return bleach.clean(
            html_content,
            tags=allowed_tags,
            attributes=allowed_attributes,
            protocols=allowed_protocols,
            strip=True
        )
    except ImportError:
        # Fallback: basic HTML sanitization using regex
        # Limit input length to prevent ReDoS attacks (10KB limit)
        MAX_HTML_LENGTH = 10000
        if len(html_content) > MAX_HTML_LENGTH:
            html_content = html_content[:MAX_HTML_LENGTH]

        # Remove script tags and their content using simple string replacement for safety
        # This avoids complex regex patterns that could cause ReDoS
        # Process in chunks to avoid catastrophic backtracking
        parts = html_content.lower().split('<script')
        if len(parts) > 1:
            cleaned_parts = [parts[0]]  # Keep content before first script tag
            for part in parts[1:]:
                # Find the end of the script tag
                script_end = part.find('</script>')
                if script_end != -1:
                    # Keep content after the closing script tag
                    cleaned_parts.append(part[script_end + 9:])
            html_content = ''.join(cleaned_parts)

        # Remove potentially dangerous attributes (limit match length to prevent ReDoS)
        html_content = re.sub(r'\son\w{1,20}\s*=\s*["\'][^"\']{0,100}["\']', '', html_content, flags=re.IGNORECASE)

        # Remove javascript: protocols
        html_content = re.sub(r'javascript\s*:', '', html_content, flags=re.IGNORECASE)

        # Remove data: protocols (except for safe image data)
        html_content = re.sub(r'data\s*:(?!image/)', '', html_content, flags=re.IGNORECASE)

        # Allow only specific safe tags using safe, non-backtracking patterns
        safe_tags = ['a', 'span', 'strong', 'em', 'br', 'small', 'code', 'pre']

        # Remove all HTML tags except safe ones (with length limits to prevent ReDoS)
        html_content = re.sub(
            r'<(?!/?)(?!(?:' + '|'.join(safe_tags) + r')(?:\s|>))[^>]{0,200}>',
            '',
            html_content,
            flags=re.IGNORECASE
        )

        # Clean up any malformed tags that might remain (with bounded quantifiers)
        # Limit to 200 chars to prevent ReDoS
        html_content = re.sub(r'<[^>]{0,200}$', '', html_content)  # Remove incomplete tags at end
        html_content = re.sub(r'^[^<]{0,200}>', '', html_content)  # Remove incomplete tags at start

        sanitized = html_content

        return sanitized
