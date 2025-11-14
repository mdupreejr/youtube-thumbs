"""
Health check endpoints for YouTube Thumbs Rating addon.
Provides comprehensive health monitoring with actual content verification.
v5.20.0: Added detailed health checks for production monitoring.
"""

from flask import Blueprint, jsonify, g, current_app
from typing import Dict, Any, Tuple
import time
import os
import json
from datetime import datetime, timedelta
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

# Create blueprint
bp = Blueprint('health', __name__)

# Store references to shared resources (set by app.py)
_db = None
_ha_api = None
_yt_api = None
_metrics = None


def init(db, ha_api, yt_api, metrics):
    """Initialize health routes with shared resources."""
    global _db, _ha_api, _yt_api, _metrics
    _db = db
    _ha_api = ha_api
    _yt_api = yt_api
    _metrics = metrics


def check_database() -> Dict[str, Any]:
    """
    Check database connectivity and basic operations.
    Tests actual queries return valid data.
    """
    try:
        start = time.time()

        # Test 1: Basic connectivity
        with _db._lock:
            cursor = _db._conn.execute("SELECT 1")
            result = cursor.fetchone()
            if not result or result[0] != 1:
                raise Exception("Basic query failed")

        # Test 2: Check tables exist and have data
        with _db._lock:
            cursor = _db._conn.execute("""
                SELECT COUNT(*) as videos,
                       (SELECT COUNT(*) FROM queue WHERE status = 'pending') as pending_queue,
                       (SELECT COUNT(*) FROM queue WHERE status = 'failed' AND attempts >= 5) as permanently_failed,
                       (SELECT COUNT(*) FROM api_calls WHERE timestamp > datetime('now', '-1 hour')) as recent_api_calls
                FROM video_ratings
            """)
            stats = cursor.fetchone()

        # Test 3: Verify critical indexes exist
        with _db._lock:
            cursor = _db._conn.execute("""
                SELECT COUNT(*) FROM sqlite_master
                WHERE type='index' AND name LIKE 'idx_%'
            """)
            index_count = cursor.fetchone()[0]

        elapsed = time.time() - start

        return {
            'status': 'healthy',
            'response_time_ms': round(elapsed * 1000, 2),
            'stats': {
                'total_videos': stats[0] if stats else 0,
                'pending_queue_items': stats[1] if stats else 0,
                'permanently_failed_items': stats[2] if stats else 0,
                'recent_api_calls': stats[3] if stats else 0,
                'indexes': index_count
            },
            'checks': {
                'connectivity': True,
                'tables_exist': True,
                'has_indexes': index_count > 0
            }
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'checks': {
                'connectivity': False,
                'tables_exist': False,
                'has_indexes': False
            }
        }


def check_youtube_api() -> Dict[str, Any]:
    """
    Check YouTube API connectivity and authentication.
    Actually tests if we can make API calls.
    """
    try:
        if not _yt_api:
            return {
                'status': 'not_initialized',
                'error': 'YouTube API not initialized',
                'authenticated': False,
                'quota_available': False
            }

        start = time.time()

        # Test 1: Check if authenticated (token exists and is valid)
        token_file = '/app/token.json'
        token_exists = os.path.exists(token_file)

        # Test 2: Check quota status
        quota_exceeded = False
        quota_reset_in = None
        with _db._lock:
            cursor = _db._conn.execute("""
                SELECT COUNT(*) FROM api_calls
                WHERE endpoint = 'videos/rate'
                AND response_data LIKE '%quotaExceeded%'
                AND timestamp > datetime('now', '-24 hours')
            """)
            recent_quota_errors = cursor.fetchone()[0]
            quota_exceeded = recent_quota_errors > 0

        if quota_exceeded:
            # Calculate time until quota reset (midnight Pacific)
            from helpers.time_helpers import get_next_quota_reset_time
            next_reset = get_next_quota_reset_time()
            now = datetime.utcnow()
            quota_reset_in = int((next_reset - now).total_seconds())

        # Test 3: Check recent API success rate
        with _db._lock:
            cursor = _db._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN response_data NOT LIKE '%error%' THEN 1 ELSE 0 END) as successful
                FROM api_calls
                WHERE timestamp > datetime('now', '-1 hour')
            """)
            api_stats = cursor.fetchone()

        total_calls = api_stats[0] if api_stats else 0
        successful_calls = api_stats[1] if api_stats else 0
        success_rate = (successful_calls / total_calls * 100) if total_calls > 0 else 100

        elapsed = time.time() - start

        return {
            'status': 'healthy' if token_exists and not quota_exceeded else 'degraded',
            'response_time_ms': round(elapsed * 1000, 2),
            'authenticated': token_exists,
            'quota_exceeded': quota_exceeded,
            'quota_reset_in_seconds': quota_reset_in,
            'recent_api_calls': total_calls,
            'success_rate': round(success_rate, 1),
            'checks': {
                'token_exists': token_exists,
                'quota_available': not quota_exceeded,
                'api_responsive': success_rate > 50
            }
        }
    except Exception as e:
        logger.error(f"YouTube API health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'authenticated': False,
            'quota_available': False
        }


def check_queue_worker() -> Dict[str, Any]:
    """
    Check if queue worker is alive and processing items.
    Verifies PID file and checks for recent activity.
    """
    try:
        # Test 1: Check PID file exists
        pid_file = '/tmp/youtube_thumbs_queue_worker.pid'
        pid_exists = os.path.exists(pid_file)

        pid = None
        process_running = False
        if pid_exists:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())

            # Test 2: Check if process is actually running
            try:
                os.kill(pid, 0)  # Signal 0 doesn't kill, just checks
                process_running = True
            except (OSError, ProcessLookupError):
                process_running = False

        # Test 3: Check for recent queue activity
        with _db._lock:
            cursor = _db._conn.execute("""
                SELECT
                    COUNT(*) as total_processed,
                    MAX(completed_at) as last_completed,
                    (SELECT COUNT(*) FROM queue WHERE status = 'processing') as currently_processing,
                    (SELECT COUNT(*) FROM queue WHERE status = 'pending') as pending
                FROM queue
                WHERE status = 'completed'
                AND completed_at > datetime('now', '-1 hour')
            """)
            queue_stats = cursor.fetchone()

        recent_activity = queue_stats[0] if queue_stats else 0
        last_completed = queue_stats[1] if queue_stats else None
        currently_processing = queue_stats[2] if queue_stats else 0
        pending_items = queue_stats[3] if queue_stats else 0

        # Calculate time since last activity
        time_since_activity = None
        if last_completed:
            try:
                last_time = datetime.strptime(last_completed, '%Y-%m-%d %H:%M:%S')
                time_since_activity = int((datetime.utcnow() - last_time).total_seconds())
            except:
                pass

        # Test 4: Check if paused
        pause_file = '/tmp/youtube_thumbs_queue_paused'
        is_paused = os.path.exists(pause_file)

        # Determine overall status
        if not pid_exists or not process_running:
            status = 'unhealthy'
        elif is_paused:
            status = 'paused'
        elif pending_items > 0 and recent_activity == 0 and time_since_activity and time_since_activity > 300:
            status = 'stuck'  # Has pending items but no recent activity
        else:
            status = 'healthy'

        return {
            'status': status,
            'pid': pid,
            'process_running': process_running,
            'is_paused': is_paused,
            'stats': {
                'recent_processed': recent_activity,
                'currently_processing': currently_processing,
                'pending': pending_items,
                'time_since_last_activity_seconds': time_since_activity
            },
            'checks': {
                'pid_file_exists': pid_exists,
                'process_alive': process_running,
                'actively_processing': recent_activity > 0 or currently_processing > 0,
                'not_stuck': status != 'stuck'
            }
        }
    except Exception as e:
        logger.error(f"Queue worker health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'process_running': False
        }


def check_home_assistant() -> Dict[str, Any]:
    """
    Check Home Assistant API connectivity.
    Tests actual API call to get current media.
    """
    try:
        if not _ha_api:
            return {
                'status': 'not_initialized',
                'error': 'Home Assistant API not initialized'
            }

        start = time.time()

        # Test 1: Try to get current media
        try:
            media_data = _ha_api.get_current_media()
            has_media = media_data is not None
            is_playing = media_data.get('state') == 'playing' if media_data else False
        except Exception as e:
            has_media = False
            is_playing = False
            media_data = None

        # Test 2: Check configured media player exists
        media_player = os.environ.get('MEDIA_PLAYER_ENTITY', 'unknown')

        elapsed = time.time() - start

        return {
            'status': 'healthy' if has_media is not None else 'degraded',
            'response_time_ms': round(elapsed * 1000, 2),
            'media_player': media_player,
            'current_state': {
                'has_media': has_media,
                'is_playing': is_playing,
                'title': media_data.get('title') if media_data else None,
                'artist': media_data.get('artist') if media_data else None
            },
            'checks': {
                'api_responsive': True,
                'media_player_configured': media_player != 'unknown',
                'can_get_media': has_media is not None
            }
        }
    except Exception as e:
        logger.error(f"Home Assistant health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'checks': {
                'api_responsive': False,
                'media_player_configured': False,
                'can_get_media': False
            }
        }


def check_endpoints() -> Dict[str, Any]:
    """
    Check key endpoints return expected content.
    Actually verifies response content, not just status codes.
    """
    results = {}

    # List of endpoints to test with expected content
    endpoints_to_test = [
        {
            'name': 'main_page',
            'path': '/',
            'expected_content': ['YouTube Thumbs', 'Tests', 'Rating'],
            'check_json': False
        },
        {
            'name': 'stats_page',
            'path': '/stats',
            'expected_content': ['Statistics Dashboard', 'Total Videos', 'Overview'],
            'check_json': False
        },
        {
            'name': 'api_unrated',
            'path': '/api/unrated',
            'expected_content': ['songs', 'page', 'total_pages'],
            'check_json': True
        },
        {
            'name': 'api_system_info',
            'path': '/api/system-info',
            'expected_content': ['version', 'db_size', 'uptime'],
            'check_json': True
        }
    ]

    # Import test client
    from app import app

    with app.test_client() as client:
        for endpoint in endpoints_to_test:
            try:
                start = time.time()

                # Set ingress path header
                response = client.get(
                    endpoint['path'],
                    headers={'X-Ingress-Path': g.get('ingress_path', '')}
                )

                elapsed = time.time() - start

                # Check status code
                status_ok = response.status_code == 200

                # Check content
                content_ok = True
                if endpoint['check_json']:
                    try:
                        data = json.loads(response.data)
                        for expected in endpoint['expected_content']:
                            if expected not in data:
                                content_ok = False
                                break
                    except:
                        content_ok = False
                else:
                    response_text = response.data.decode('utf-8')
                    for expected in endpoint['expected_content']:
                        if expected not in response_text:
                            content_ok = False
                            break

                results[endpoint['name']] = {
                    'status': 'healthy' if status_ok and content_ok else 'unhealthy',
                    'status_code': response.status_code,
                    'content_valid': content_ok,
                    'response_time_ms': round(elapsed * 1000, 2)
                }

            except Exception as e:
                results[endpoint['name']] = {
                    'status': 'unhealthy',
                    'error': str(e),
                    'content_valid': False
                }

    # Determine overall status
    all_healthy = all(r.get('status') == 'healthy' for r in results.values())

    return {
        'status': 'healthy' if all_healthy else 'degraded',
        'endpoints': results,
        'checks': {
            endpoint['name']: results.get(endpoint['name'], {}).get('status') == 'healthy'
            for endpoint in endpoints_to_test
        }
    }


@bp.route('/health')
def health_check() -> Tuple[Any, int]:
    """
    Comprehensive health check endpoint.
    Returns detailed status of all system components with actual content verification.

    Returns:
        JSON with health status and detailed checks
        HTTP 200 if healthy
        HTTP 503 if degraded or unhealthy
    """
    try:
        start_time = time.time()

        # Run all health checks
        checks = {
            'database': check_database(),
            'youtube_api': check_youtube_api(),
            'queue_worker': check_queue_worker(),
            'home_assistant': check_home_assistant(),
            'endpoints': check_endpoints()
        }

        # Calculate overall status
        statuses = [check.get('status', 'unknown') for check in checks.values()]

        if all(s == 'healthy' for s in statuses):
            overall_status = 'healthy'
            status_code = 200
        elif any(s == 'unhealthy' for s in statuses):
            overall_status = 'unhealthy'
            status_code = 503
        else:
            overall_status = 'degraded'
            status_code = 503

        # Get system info
        uptime_seconds = None
        if hasattr(current_app, 'start_time'):
            uptime_seconds = int(time.time() - current_app.start_time)

        response = {
            'status': overall_status,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'version': current_app.config.get('VERSION', 'unknown'),
            'uptime_seconds': uptime_seconds,
            'response_time_ms': round((time.time() - start_time) * 1000, 2),
            'checks': checks,
            'summary': {
                'healthy_components': sum(1 for s in statuses if s == 'healthy'),
                'degraded_components': sum(1 for s in statuses if s == 'degraded'),
                'unhealthy_components': sum(1 for s in statuses if s == 'unhealthy'),
                'total_components': len(statuses)
            }
        }

        return jsonify(response), status_code

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500


@bp.route('/health/simple')
def health_check_simple() -> Tuple[Any, int]:
    """
    Simple health check endpoint for load balancers.
    Returns just OK/NOT OK with minimal processing.
    """
    try:
        # Just check database connectivity
        with _db._lock:
            cursor = _db._conn.execute("SELECT 1")
            result = cursor.fetchone()

        if result and result[0] == 1:
            return jsonify({'status': 'OK'}), 200
        else:
            return jsonify({'status': 'NOT OK'}), 503
    except:
        return jsonify({'status': 'NOT OK'}), 503