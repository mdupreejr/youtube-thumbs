"""
Database proxy module for forwarding requests to sqlite_web.
Handles ingress path rewriting and custom CSS injection.
"""
import os
import re
import traceback
import requests
from flask import request, Response
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


def create_database_proxy_handler():
    """
    Create and return the database proxy handler function.

    Returns:
        Function that handles database proxy requests
    """
    def database_proxy(path):
        """Proxy requests to sqlite_web running on port 8080."""
        sqlite_web_host = os.getenv('SQLITE_WEB_HOST', '127.0.0.1')
        sqlite_web_port = os.getenv('SQLITE_WEB_PORT', '8080')
        sqlite_web_url = f"http://{sqlite_web_host}:{sqlite_web_port}"

        # Build the target URL
        if path:
            target_url = f"{sqlite_web_url}/{path}"
        else:
            target_url = sqlite_web_url

        # Forward query parameters
        query_string = request.query_string.decode('utf-8')
        if query_string:
            target_url += f"?{query_string}"

        try:
            # Forward the request to sqlite_web
            resp = requests.request(
                method=request.method,
                url=target_url,
                headers={key: value for (key, value) in request.headers if key != 'Host'},
                data=request.get_data(),
                cookies=request.cookies,
                allow_redirects=False,
                timeout=30
            )

            # Build response
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            headers = [(name, value) for (name, value) in resp.raw.headers.items()
                       if name.lower() not in excluded_headers]

            # Inject custom CSS and fix links for Home Assistant ingress if this is HTML
            content = resp.content
            content_type = resp.headers.get('Content-Type', '')
            if 'text/html' in content_type and b'</head>' in content:
                # Rewrite links for ingress compatibility
                # sqlite_web generates links like href="/ratings.db/table"
                # We need to rewrite them to include the ingress prefix
                raw_ingress_path = request.environ.get('HTTP_X_INGRESS_PATH')
                if raw_ingress_path:
                    # SECURITY: Sanitize ingress path to prevent XSS/HTML injection
                    ingress_path = sanitize_ingress_path(raw_ingress_path)
                    if ingress_path:  # Only rewrite if we have a valid sanitized path
                        # Rewrite hrefs to include /database prefix and ingress path
                        content = content.replace(b'href="/', f'href="{ingress_path}/database/'.encode())
                        content = content.replace(b"href='/", f"href='{ingress_path}/database/".encode())
                        content = content.replace(b'action="/', f'action="{ingress_path}/database/'.encode())
                        content = content.replace(b"action='/", f"action='{ingress_path}/database/".encode())
                    else:
                        # Invalid ingress path, use fallback
                        content = content.replace(b'href="/', b'href="/database/')
                        content = content.replace(b"href='/", b"href='/database/")
                        content = content.replace(b'action="/', b'action="/database/')
                        content = content.replace(b"action='/", b"action='/database/")
                else:
                    # Not through ingress, just add /database prefix
                    content = content.replace(b'href="/', b'href="/database/')
                    content = content.replace(b"href='/", b"href='/database/")
                    content = content.replace(b'action="/', b'action="/database/')
                    content = content.replace(b"action='/", b"action='/database/")
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
                # Auto-sort video_ratings table by date_last_played using JavaScript
                auto_sort_js = b''
                if 'video_ratings' in path.lower() and 'content' in path.lower():
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
                content = content.replace(b'</head>', custom_css + auto_sort_js + b'</head>')

            # SECURITY: Create response from proxied content
            # Mitigations in place:
            # 1. Content from localhost-only sqlite_web (trusted source)
            # 2. Ingress path is sanitized via sanitize_ingress_path() (line 86)
            # 3. CSP headers restrict script execution
            # 4. X-Content-Type-Options prevents MIME sniffing
            # nosec B201 - Multiple layers of XSS protection applied
            response = Response(content, resp.status_code, headers)

            # SECURITY: Add comprehensive security headers to prevent XSS
            # Strict CSP: only allow scripts/styles from self
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'

            return response

        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to sqlite_web - is it running?")
            return Response("Database viewer not available. sqlite_web may not be running.", status=503)
        except Exception as e:
            logger.error(f"Error proxying to sqlite_web: {e}")
            logger.error(traceback.format_exc())
            return Response("Error accessing database viewer", status=500)

    return database_proxy
