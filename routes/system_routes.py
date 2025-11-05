"""
System routes for health checks, status, metrics, and connectivity tests.
Extracted from app.py for better organization.
"""
import json
import time
import traceback
from flask import Blueprint, request, jsonify, Response
from logger import logger

bp = Blueprint('system', __name__)

# Global references (set by init function)
_ha_api = None
_quota_guard = None
_quota_prober = None
_get_youtube_api = None
_db = None
_rate_limiter = None
_metrics = None
_check_home_assistant_api = None
_check_youtube_api = None
_check_database = None

def init_system_routes(
    ha_api,
    quota_guard,
    quota_prober,
    get_youtube_api_func,
    database,
    rate_limiter,
    metrics_tracker,
    check_home_assistant_api_func,
    check_youtube_api_func,
    check_database_func
):
    """Initialize system routes with dependencies."""
    global _ha_api, _quota_guard, _quota_prober, _get_youtube_api, _db
    global _rate_limiter, _metrics, _check_home_assistant_api
    global _check_youtube_api, _check_database

    _ha_api = ha_api
    _quota_guard = quota_guard
    _quota_prober = quota_prober
    _get_youtube_api = get_youtube_api_func
    _db = database
    _rate_limiter = rate_limiter
    _metrics = metrics_tracker
    _check_home_assistant_api = check_home_assistant_api_func
    _check_youtube_api = check_youtube_api_func
    _check_database = check_database_func


# ============================================================================
# DECORATORS
# ============================================================================

def require_rate_limit(f):
    """
    SECURITY: Decorator to apply rate limiting to API endpoints.
    Returns 429 Too Many Requests if rate limit is exceeded.
    """
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        allowed, reason = _rate_limiter.check_and_add_request()
        if not allowed:
            logger.warning(f"Rate limit exceeded for {request.remote_addr} on {request.path}")
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': reason}), 429
            return reason, 429
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# TEST ROUTES (System Connectivity Tests)
# ============================================================================

@bp.route('/test/youtube')
@require_rate_limit
def test_youtube() -> Response:
    """Test YouTube API connectivity and quota status."""
    logger.debug("=== /test/youtube endpoint called ===")
    try:
        yt_api = _get_youtube_api()
        success, message = _check_youtube_api(yt_api, _quota_guard, _db)
        logger.debug(f"YouTube test result: success={success}, message={message}")
        response = jsonify({"success": success, "message": message})
        logger.debug(f"Returning JSON response: {response.get_json()}")
        return response
    except Exception as e:
        logger.error(f"=== ERROR in /test/youtube endpoint ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": "Error testing YouTube API connection"})


@bp.route('/test/ha')
@require_rate_limit
def test_ha() -> Response:
    """Test Home Assistant API connectivity."""
    logger.debug("=== /test/ha endpoint called ===")
    try:
        success, message = _check_home_assistant_api(_ha_api)
        logger.debug(f"HA test result: success={success}, message={message}")
        response = jsonify({"success": success, "message": message})
        logger.debug(f"Returning JSON response: {response.get_json()}")
        return response
    except Exception as e:
        logger.error(f"=== ERROR in /test/ha endpoint ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": "Error testing Home Assistant connection"})


@bp.route('/test/db')
@require_rate_limit
def test_db() -> Response:
    """Test database connectivity and integrity."""
    logger.debug("=== /test/db endpoint called ===")
    try:
        success, message = _check_database(_db)
        logger.debug(f"DB test result: success={success}, message={message}")
        response = jsonify({"success": success, "message": message})
        logger.debug(f"Returning JSON response: {response.get_json()}")
        return response
    except Exception as e:
        logger.error(f"=== ERROR in /test/db endpoint ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": "Error testing database connection"})


# ============================================================================
# MONITORING ROUTES (Health, Status, Metrics)
# ============================================================================

@bp.route('/health', methods=['GET'])
def health() -> Response:
    """
    Fast health check endpoint optimized for frequent polling.

    This endpoint is optimized for speed (< 100ms response time) and does NOT:
    - Attempt thread restarts
    - Perform blocking operations

    It provides basic status information for UI polling without expensive operations.
    For full diagnostics with thread recovery, use /status endpoint instead.
    """
    # Quick non-blocking checks only - no thread restarts
    guard_status = _quota_guard.status()
    prober_healthy = _quota_prober.is_healthy()

    # Simple health score without expensive metric calculations
    # Base score of 100, deduct for issues
    health_score = 100
    warnings = []

    if not prober_healthy:
        warnings.append("Quota prober is not running")
        health_score -= 15

    if guard_status.get('blocked'):
        overall_status = "cooldown"
    elif health_score >= 70:
        overall_status = "healthy"
    elif health_score >= 40:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return jsonify({
        "status": overall_status,
        "health_score": health_score,
        "warnings": warnings,
        "quota_guard": guard_status,
        "quota_prober": {
            "healthy": prober_healthy,
            "enabled": _quota_prober.enabled,
        },
        "timestamp": time.time()
    }), 200


@bp.route('/status', methods=['GET'])
def status() -> Response:
    """
    Detailed system status endpoint with full diagnostics.

    This endpoint provides comprehensive health information but may be slower
    due to metric calculations. Use /health for fast uptime checks.

    Query Parameters:
        format: 'json' (default) or 'html' for formatted view
    """
    stats = _rate_limiter.get_stats()
    guard_status = _quota_guard.status()

    # Check quota prober health and attempt recovery if needed
    prober_healthy = _quota_prober.is_healthy()
    if not prober_healthy:
        logger.warning("Quota prober unhealthy, attempting restart")
        _quota_prober.ensure_running()
        prober_healthy = _quota_prober.is_healthy()

    # Get health score from metrics
    health_score, warnings = _metrics.get_health_score()

    # Add prober warning if still unhealthy
    if not prober_healthy:
        warnings.append("Quota prober is not running")
        health_score = min(health_score, 60)  # Cap health score if prober is down

    if guard_status.get('blocked'):
        overall_status = "cooldown"
    elif health_score >= 70:
        overall_status = "healthy"
    elif health_score >= 40:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    response_data = {
        "status": overall_status,
        "health_score": health_score,
        "warnings": warnings,
        "rate_limiter": stats,
        "quota_guard": guard_status,
        "quota_prober": {
            "healthy": prober_healthy,
            "enabled": _quota_prober.enabled,
        }
    }

    # Check if HTML format is requested (default for browser access)
    format_type = request.args.get('format', 'html')

    if format_type == 'html':
        # Return formatted HTML view
        json_str = json.dumps(response_data, indent=2, sort_keys=True)
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>YouTube Thumbs - System Status</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                    margin: 0;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
                }}
                h1 {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                    margin-bottom: 10px;
                }}
                .subtitle {{
                    color: #666;
                    margin-bottom: 30px;
                    font-size: 14px;
                }}
                pre {{
                    background: #f5f5f5;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    padding: 20px;
                    overflow-x: auto;
                    font-family: 'Monaco', 'Courier New', monospace;
                    font-size: 13px;
                    line-height: 1.6;
                }}
                .back-link {{
                    display: inline-block;
                    margin-top: 20px;
                    color: #667eea;
                    text-decoration: none;
                    font-weight: 600;
                    padding: 10px 20px;
                    border-radius: 8px;
                    background: #667eea15;
                    transition: all 0.2s;
                }}
                .back-link:hover {{
                    background: #667eea;
                    color: white;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>💚 System Status</h1>
                <div class="subtitle">Detailed health and diagnostics monitoring</div>
                <pre>{json_str}</pre>
                <a href="javascript:history.back()" class="back-link">← Back to Dashboard</a>
            </div>
        </body>
        </html>
        """
        return html, 200

    return jsonify(response_data)


@bp.route('/metrics', methods=['GET'])
def get_metrics() -> Response:
    """
    Comprehensive metrics endpoint for monitoring and analysis.

    Returns detailed statistics about:
    - Cache performance and hit rates
    - API usage and quota status
    - Rating operations (success/failed/queued)
    - Search patterns and failures
    - System uptime and health

    Query Parameters:
        format: 'json' (default) or 'html' for formatted view
    """
    try:
        all_metrics = _metrics.get_all_metrics()
        health_score, warnings = _metrics.get_health_score()

        response_data = {
            'health': {
                'score': health_score,
                'status': 'healthy' if health_score >= 70 else 'degraded' if health_score >= 40 else 'unhealthy',
                'warnings': warnings
            },
            **all_metrics
        }

        # Check if HTML format is requested (default for browser access)
        format_type = request.args.get('format', 'html')

        if format_type == 'html':
            # Return formatted HTML view
            json_str = json.dumps(response_data, indent=2, sort_keys=True)
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>YouTube Thumbs - Metrics</title>
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                        padding: 20px;
                        margin: 0;
                    }}
                    .container {{
                        max-width: 1200px;
                        margin: 0 auto;
                        background: white;
                        border-radius: 16px;
                        padding: 40px;
                        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
                    }}
                    h1 {{
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        -webkit-background-clip: text;
                        -webkit-text-fill-color: transparent;
                        background-clip: text;
                        margin-bottom: 10px;
                    }}
                    .subtitle {{
                        color: #666;
                        margin-bottom: 30px;
                        font-size: 14px;
                    }}
                    pre {{
                        background: #f5f5f5;
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 20px;
                        overflow-x: auto;
                        font-family: 'Monaco', 'Courier New', monospace;
                        font-size: 13px;
                        line-height: 1.6;
                    }}
                    .back-link {{
                        display: inline-block;
                        margin-top: 20px;
                        color: #667eea;
                        text-decoration: none;
                        font-weight: 600;
                        padding: 10px 20px;
                        border-radius: 8px;
                        background: #667eea15;
                        transition: all 0.2s;
                    }}
                    .back-link:hover {{
                        background: #667eea;
                        color: white;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>📈 System Metrics</h1>
                    <div class="subtitle">Real-time monitoring and performance statistics</div>
                    <pre>{json_str}</pre>
                    <a href="javascript:history.back()" class="back-link">← Back to Dashboard</a>
                </div>
            </body>
            </html>
            """
            return html, 200

        return jsonify(response_data), 200
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        return jsonify({'error': 'Failed to generate metrics'}), 500
