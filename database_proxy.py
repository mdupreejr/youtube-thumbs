"""
Database viewer integration module - mounts sqlite_web directly into Flask.
Replaces HTTP proxying with in-process WSGI mounting for better performance.
"""
import os
import re
from logger import logger


def sanitize_ingress_path(path):
    """
    Sanitize ingress path to prevent XSS and HTML injection.

    Args:
        path: The ingress path from HTTP headers

    Returns:
        Sanitized path or empty string if invalid
    """
    if not path:
        return ''

    # Only allow alphanumeric, hyphens, underscores, and forward slashes
    # This prevents XSS via script tags or HTML injection
    if not re.match(r'^/[a-zA-Z0-9/_-]*$', path):
        logger.warning(f"Invalid ingress path rejected: {path}")
        return ''

    return path


def create_sqlite_web_middleware(db_path):
    """
    Create sqlite_web WSGI application for direct mounting into Flask.

    This replaces the HTTP proxy approach with direct WSGI app mounting,
    providing better performance and simpler architecture.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        WSGI application callable that serves sqlite_web
    """
    try:
        from sqlite_web import app as sqlite_web_module

        # Configure sqlite_web
        # Note: sqlite_web uses global config, so we set environment variables
        os.environ['SQLITE_WEB_DATABASE'] = db_path
        os.environ['SQLITE_WEB_PASSWORD'] = ''  # No password (protected by Home Assistant)

        # Get the WSGI app from sqlite_web
        # sqlite_web creates its Flask app on import
        sqlite_web_app = sqlite_web_module.app

        # Wrap sqlite_web app to inject custom CSS and handle ingress paths
        def wrapped_sqlite_web(environ, start_response):
            """
            WSGI wrapper that injects custom styling and handles ingress paths.
            """
            # Fix PATH_INFO for sqlite_web (remove /database prefix)
            original_path = environ.get('PATH_INFO', '/')
            if original_path.startswith('/database'):
                environ['PATH_INFO'] = original_path[len('/database'):]
            if not environ['PATH_INFO']:
                environ['PATH_INFO'] = '/'

            # Store original start_response to intercept response
            responses = []
            def custom_start_response(status, headers, exc_info=None):
                responses.append((status, headers))
                return start_response(status, headers, exc_info)

            # Call sqlite_web app
            app_iter = sqlite_web_app(environ, custom_start_response)

            # If HTML response, inject custom CSS
            if responses and len(responses) > 0:
                status, headers = responses[0]
                content_type = dict(headers).get('Content-Type', '')

                if 'text/html' in content_type:
                    # Collect response body
                    body_parts = []
                    for data in app_iter:
                        body_parts.append(data)

                    body = b''.join(body_parts)

                    # Inject custom CSS if we find </head>
                    if b'</head>' in body:
                        # Get ingress path from environ
                        ingress_path = environ.get('HTTP_X_INGRESS_PATH', '')

                        # Rewrite links for ingress compatibility
                        if ingress_path:
                            sanitized_path = sanitize_ingress_path(ingress_path)
                            if sanitized_path:
                                body = body.replace(b'href="/', f'href="{sanitized_path}/database/'.encode())
                                body = body.replace(b"href='/", f"href='{sanitized_path}/database/".encode())
                                body = body.replace(b'action="/', f'action="{sanitized_path}/database/'.encode())
                                body = body.replace(b"action='/", f"action='{sanitized_path}/database/".encode())
                            else:
                                body = body.replace(b'href="/', b'href="/database/')
                                body = body.replace(b"href='/", b"href='/database/")
                                body = body.replace(b'action="/', b'action="/database/')
                                body = body.replace(b"action='/", b"action='/database/")
                        else:
                            body = body.replace(b'href="/', b'href="/database/')
                            body = body.replace(b"href='/", b"href='/database/")
                            body = body.replace(b'action="/', b'action="/database/')
                            body = body.replace(b"action='/", b"action='/database/")

                        custom_css = b'''
<style>
/* Custom CSS to make sqlite_web sidebar narrower and fix theme compatibility */
#sidebar, .col-3 {
    width: 100px !important;
    min-width: 100px !important;
    max-width: 100px !important;
    flex: 0 0 100px !important;
}
.col-9, .content, main {
    margin-left: 0 !important;
    width: calc(100% - 100px) !important;
    max-width: calc(100% - 100px) !important;
}

/* Fix background colors for proper visibility */
body {
    background-color: #ffffff !important;
    color: #333333 !important;
}

/* Ensure content areas have proper background */
.content, .main, #content, main {
    background-color: #ffffff !important;
    color: #333333 !important;
}

/* Fix table styling */
table {
    background-color: #ffffff !important;
    color: #333333 !important;
}

table th {
    background-color: #f5f5f5 !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

table td {
    background-color: #ffffff !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

table tr:hover td {
    background-color: #f9f9f9 !important;
}

/* Fix form and input elements */
input, select, textarea, button {
    background-color: #ffffff !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

/* Fix links */
a {
    color: #0066cc !important;
}

a:hover {
    color: #004499 !important;
}

/* Fix pre and code blocks */
pre, code {
    background-color: #f5f5f5 !important;
    color: #333333 !important;
    border: 1px solid #ddd !important;
}

/* Fix sidebar */
.sidebar, #sidebar, nav {
    background-color: #f8f8f8 !important;
    color: #333333 !important;
}

/* Fix header areas */
header, .header {
    background-color: #f5f5f5 !important;
    color: #333333 !important;
}

@media (max-width: 768px) {
    #sidebar, .col-3 {
        width: 80px !important;
        min-width: 80px !important;
        max-width: 80px !important;
        flex: 0 0 80px !important;
    }
    .col-9, .content, main {
        width: calc(100% - 80px) !important;
        max-width: calc(100% - 80px) !important;
    }
}
</style>
'''
                        # Auto-sort video_ratings table by date_last_played
                        auto_sort_js = b''
                        if b'video_ratings' in original_path.lower().encode() and b'content' in original_path.lower().encode():
                            auto_sort_js = b'''
<script>
// Auto-sort video_ratings table by date_last_played (descending, NULLs last)
document.addEventListener('DOMContentLoaded', function() {
    const currentUrl = window.location.href;

    // Check if already sorted (either ascending or descending)
    if (!currentUrl.includes('ordering=')) {
        console.log('Auto-sorting by date_last_played (descending)');
        // Redirect to sorted view with descending order (- prefix means descending in sqlite_web)
        window.location.href = currentUrl + (currentUrl.includes('?') ? '&' : '?') + 'ordering=-date_last_played';
    }
});
</script>
'''

                        body = body.replace(b'</head>', custom_css + auto_sort_js + b'</head>')

                        # Update Content-Length header
                        new_headers = []
                        for name, value in headers:
                            if name.lower() not in ['content-length', 'content-encoding', 'transfer-encoding']:
                                new_headers.append((name, value))
                        new_headers.append(('Content-Length', str(len(body))))

                        # Add security headers
                        new_headers.append(('Content-Security-Policy',
                            "default-src 'self'; "
                            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                            "style-src 'self' 'unsafe-inline'; "
                            "img-src 'self' data:; "
                            "connect-src 'self'; "
                            "frame-ancestors 'self'"))
                        new_headers.append(('X-Content-Type-Options', 'nosniff'))
                        new_headers.append(('X-Frame-Options', 'SAMEORIGIN'))
                        new_headers.append(('X-XSS-Protection', '1; mode=block'))

                        # Start response with modified headers
                        start_response(status, new_headers)
                        return [body]

            # Not HTML or no modification needed, return as-is
            return app_iter

        logger.info(f"sqlite_web WSGI app created successfully for {db_path}")
        return wrapped_sqlite_web

    except Exception as e:
        logger.error(f"Failed to create sqlite_web WSGI app: {e}")
        raise
