"""
Request helpers for handling HTTP request data safely.
"""
from flask import request


def get_real_ip() -> str:
    """
    Get real client IP address, accounting for reverse proxies.

    When behind a reverse proxy (like nginx, Home Assistant ingress, etc.),
    request.remote_addr returns the proxy's IP, not the client's real IP.
    This function checks X-Forwarded-For header first.

    Returns:
        Real client IP address as string

    Security Notes:
        - X-Forwarded-For can be spoofed by malicious clients
        - In production, ensure your reverse proxy is configured to:
          1. Strip client-provided X-Forwarded-For headers
          2. Add its own trusted X-Forwarded-For header
        - For high-security logging, consider using both real IP and remote_addr
    """
    # X-Forwarded-For format: "client, proxy1, proxy2"
    # We want the leftmost (original client) IP
    forwarded_for = request.headers.get('X-Forwarded-For')

    if forwarded_for:
        # Get first IP in the chain (original client)
        client_ip = forwarded_for.split(',')[0].strip()
        return client_ip

    # Fallback to direct connection IP if no proxy headers
    return request.remote_addr
