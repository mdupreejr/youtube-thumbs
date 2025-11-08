"""
Startup checks to verify all components are working properly
"""

from typing import Tuple, Optional
from logger import logger


def check_home_assistant_api(ha_api) -> Tuple[bool, dict]:
    """Test Home Assistant API connectivity and configuration with detailed information."""
    try:
        if not ha_api.token:
            return False, {'message': "No authentication token", 'details': {}}

        # Test getting current media and entity state
        import requests
        import time

        start_time = time.time()
        media = ha_api.get_current_media()
        response_time = int((time.time() - start_time) * 1000)  # ms

        # Get full entity state
        url = f"{ha_api.url}/api/states/{ha_api.entity}"
        response = ha_api.session.get(url, timeout=10)

        if response.status_code != 200:
            if response.status_code == 404:
                return False, {'message': f"Entity {ha_api.entity} not found", 'details': {}}
            else:
                return False, {'message': f"HTTP {response.status_code}", 'details': {}}

        entity_data = response.json()
        state = entity_data.get('state', 'unknown')
        attributes = entity_data.get('attributes', {})

        # Build detailed response
        details = {
            'url': ha_api.url,
            'entity': ha_api.entity,
            'state': state,
            'response_time_ms': response_time,
            'media': media if media else None,
            'attributes': {
                'friendly_name': attributes.get('friendly_name', 'Unknown'),
                'supported_features': attributes.get('supported_features'),
                'device_class': attributes.get('device_class'),
                'volume_level': attributes.get('volume_level'),
                'is_volume_muted': attributes.get('is_volume_muted'),
                'source': attributes.get('source'),
                'source_list': attributes.get('source_list', [])
            }
        }

        if media:
            message = f"Connected • Playing: {media.get('title', 'Unknown')}"
        else:
            message = f"Connected • Player {state}"

        return True, {'message': message, 'details': details}

    except Exception as e:
        return False, {'message': str(e), 'details': {}}


def check_youtube_api(yt_api, db=None) -> Tuple[bool, dict]:
    """Test YouTube API authentication and quota with detailed statistics."""
    # Check queue worker status (even if API check fails, we want to report worker status)
    import os
    worker_running = False
    worker_pid = None
    pid_file = '/tmp/youtube_thumbs_queue_worker.pid'
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                worker_pid = int(f.read().strip())
            os.kill(worker_pid, 0)  # Check if process exists
            worker_running = True
        except (OSError, ValueError):
            pass

    try:
        if not yt_api or not yt_api.youtube:
            # Return minimal details even on auth failure
            details = {
                'authenticated': False,
                'worker_running': worker_running,
                'worker_pid': worker_pid if worker_running else None,
                'quota': {},
                'queue': {},
                'performance': {},
                'api_stats': {}
            }
            return False, {'message': "Not authenticated", 'details': details}

        # v4.0.36: Check quota status FIRST - if exceeded, just report that and skip all API checks
        quota_recently_exceeded = False
        next_reset_str = None
        if db:
            try:
                from datetime import datetime, timedelta, timezone

                # Check for recent quota errors (same logic as queue_worker.py)
                cursor = db._conn.execute(
                    """
                    SELECT timestamp, error_message
                    FROM api_call_log
                    WHERE success = 0
                      AND (error_message LIKE '%quota%' OR error_message LIKE '%Quota%')
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                )
                row = cursor.fetchone()

                if row:
                    last_quota_error = dict(row)
                    error_time_str = last_quota_error.get('timestamp')

                    if error_time_str:
                        # Parse timestamp
                        if isinstance(error_time_str, str):
                            error_dt = datetime.fromisoformat(error_time_str.replace('Z', '+00:00'))
                        else:
                            error_dt = error_time_str

                        # Ensure error_dt has timezone
                        if error_dt.tzinfo is None:
                            error_dt = error_dt.replace(tzinfo=timezone.utc)

                        # Calculate last quota reset (midnight Pacific Time)
                        now_utc = datetime.now(timezone.utc)
                        pacific_offset = timedelta(hours=-8)
                        now_pacific = now_utc + pacific_offset
                        midnight_today_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
                        midnight_today_utc = midnight_today_pacific - pacific_offset

                        if now_utc < midnight_today_utc:
                            last_reset_utc = midnight_today_utc - timedelta(days=1)
                        else:
                            last_reset_utc = midnight_today_utc

                        # Calculate next reset
                        next_reset_utc = last_reset_utc + timedelta(days=1)
                        time_until_reset = next_reset_utc - now_utc
                        hours_until = int(time_until_reset.total_seconds() / 3600)
                        minutes_until = int((time_until_reset.total_seconds() % 3600) / 60)
                        next_reset_str = f"{hours_until}h {minutes_until}m"

                        # If quota error occurred AFTER last reset, quota is still exhausted
                        if error_dt > last_reset_utc:
                            quota_recently_exceeded = True
                            logger.debug(f"Quota exceeded - paused until midnight Pacific (in {next_reset_str})")
            except Exception as e:
                logger.debug(f"Error checking quota status: {e}")

        # If quota exceeded, report that and skip all API checks
        if quota_recently_exceeded:
            pause_msg = f"Quota exceeded - paused until midnight Pacific"
            if next_reset_str:
                pause_msg += f" (in {next_reset_str})"

            # Return early with quota pause message - no API check needed
            details = {
                'authenticated': True,  # We have auth object, just can't use it
                'worker_running': worker_running,
                'worker_pid': worker_pid if worker_running else None,
                'quota': {'exceeded': True, 'time_until_reset': next_reset_str},
                'queue': {},
                'performance': {},
                'api_stats': {}
            }
            return True, {'message': pause_msg, 'details': details}

        # Quota not exceeded - proceed with authentication test
        try:
            import time
            start_time = time.time()

            # Get channel info for authenticated user (minimal quota cost = 1 unit)
            request = yt_api.youtube.channels().list(
                part='snippet',
                mine=True,
                maxResults=1,
                fields='items(id,snippet(title))'
            )
            response = request.execute()

            response_time = int((time.time() - start_time) * 1000)  # ms

            # Log the API call
            if db:
                channel_name = response.get('items', [{}])[0].get('snippet', {}).get('title', 'Unknown')
                db.record_api_call('channels.list', success=True, quota_cost=1)
                db.log_api_call_detailed(
                    api_method='channels.list',
                    operation_type='auth_check',
                    query_params='mine=True',
                    quota_cost=1,
                    success=True,
                    results_count=len(response.get('items', [])),
                    context=f'startup_check (authenticated as: {channel_name})'
                )

            logger.debug(f"YouTube API authentication verified ({response_time}ms)")

        except Exception as e:
            logger.error(f"YouTube API authentication test failed: {e}")
            # Log the failed API call
            if db:
                db.record_api_call('channels.list', success=False, quota_cost=1, error_message=str(e))
                db.log_api_call_detailed(
                    api_method='channels.list',
                    operation_type='auth_check',
                    query_params='mine=True',
                    quota_cost=0,  # YouTube doesn't charge for failed auth
                    success=False,
                    error_message=str(e)[:500],
                    context='startup_check'
                )
            return False, {'message': f"Authentication test failed: {str(e)}", 'details': {
                'authenticated': False,
                'worker_running': worker_running,
                'worker_pid': worker_pid if worker_running else None,
                'quota': {},
                'queue': {},
                'performance': {},
                'api_stats': {}
            }}

        # Default details structure
        details = {
            'authenticated': True,
            'worker_running': worker_running,
            'worker_pid': worker_pid if worker_running else None,
            'quota': {},
            'queue': {},
            'performance': {},
            'api_stats': {}
        }

        # Get detailed statistics if database available
        if db:
            try:
                from datetime import datetime, timedelta, timezone

                # Get quota usage and call stats (24h)
                summary_data = db.get_api_call_summary(hours=24)
                summary = summary_data.get('summary', {})
                quota_used = summary.get('total_quota', 0) or 0
                total_calls = summary.get('total_calls', 0) or 0
                successful_calls = summary.get('successful_calls', 0) or 0
                failed_calls = summary.get('failed_calls', 0) or 0
                success_rate = (successful_calls / total_calls * 100) if total_calls > 0 else 0

                # Get queue statistics
                queue_stats = db.get_queue_statistics()

                # Get recent queue activity
                recent_activity = db.get_recent_queue_activity(limit=10)

                # Get queue performance metrics
                performance = db.get_queue_performance_metrics(hours=24)

                # Populate details
                details['quota'] = {
                    'used': quota_used,
                    'total': 10000,
                    'percent': (quota_used / 10000 * 100) if quota_used > 0 else 0,
                    'exceeded': quota_exceeded,
                    'time_until_reset': time_until_reset_str
                }

                details['queue'] = {
                    'total': queue_stats.get('total_items', 0),
                    'pending': queue_stats.get('pending', 0),
                    'processing': queue_stats.get('processing', 0),
                    'completed': queue_stats.get('completed', 0),
                    'failed': queue_stats.get('failed', 0),
                    'pending_searches': queue_stats.get('pending_searches', 0),
                    'pending_ratings': queue_stats.get('pending_ratings', 0)
                }

                details['performance'] = {
                    'items_processed_24h': performance.get('items_processed', 0),
                    'success_rate': performance.get('success_rate', 0),
                    'avg_processing_time': performance.get('avg_processing_time', 0)
                }

                details['api_stats'] = {
                    'total_calls_24h': total_calls,
                    'successful_calls': successful_calls,
                    'failed_calls': failed_calls,
                    'success_rate': success_rate,
                    'by_method': summary_data.get('by_method', [])
                }

                # Build status message
                if quota_exceeded:
                    message = f"⚠️ QUOTA EXCEEDED • Worker paused until midnight PT (in {time_until_reset_str})"
                    return False, {'message': message, 'details': details}
                else:
                    message = f"✓ Authenticated • Quota: {quota_used:,}/10,000 ({details['quota']['percent']:.1f}%)"
                    return True, {'message': message, 'details': details}

            except Exception as e:
                logger.debug(f"Error getting YouTube API statistics: {e}")
                pass

        # Fallback if no database stats available
        message = "✓ Authenticated" if worker_running else "✓ Authenticated • Worker not running"
        return True, {'message': message, 'details': details}

    except Exception as e:
        # Even on error, include worker status
        details = {
            'authenticated': False,
            'worker_running': worker_running,
            'worker_pid': worker_pid if worker_running else None,
            'quota': {},
            'queue': {},
            'performance': {},
            'api_stats': {}
        }
        return False, {'message': str(e), 'details': details}


def check_database(db) -> Tuple[bool, str]:
    """Test database connectivity and report statistics."""
    try:
        if not db.db_path.exists():
            return True, "Will be created on first use"

        # Test connection and get statistics
        with db._lock:
            # Count all videos
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings")
            total_videos = cursor.fetchone()['count']

            # Count rated videos
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'like'")
            liked = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'dislike'")
            disliked = cursor.fetchone()['count']

            # Count queue items from unified queue
            cursor = db._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN type = 'rating' THEN 1 ELSE 0 END) as ratings,
                    SUM(CASE WHEN type = 'search' THEN 1 ELSE 0 END) as searches
                FROM queue
                WHERE status = 'pending'
            """)
            queue_row = cursor.fetchone()
            total_queue = queue_row['total'] or 0
            pending_ratings = queue_row['ratings'] or 0
            pending_searches = queue_row['searches'] or 0

        # Build concise status
        parts = [f"{total_videos} videos", f"{liked}👍 {disliked}👎"]
        if total_queue > 0:
            parts.append(f"Queue: {total_queue} ({pending_searches}S/{pending_ratings}R)")

        return True, ", ".join(parts)

    except Exception as e:
        return False, str(e)


def run_startup_checks(ha_api, yt_api, db):
    """
    Run all startup checks and report status.

    Returns:
        Tuple of (all_ok, check_results) where check_results is a dict with:
        {'ha': (success, data), 'yt': (success, data), 'db': (success, message)}
    """
    all_ok = True
    results = []

    # Check Home Assistant API
    ha_ok, ha_data = check_home_assistant_api(ha_api)
    ha_msg = ha_data.get('message', 'Unknown') if isinstance(ha_data, dict) else ha_data
    results.append(("Home Assistant", ha_ok, ha_msg))
    all_ok = all_ok and ha_ok

    # Check YouTube API
    yt_ok, yt_data = check_youtube_api(yt_api, db)
    yt_msg = yt_data.get('message', 'Unknown') if isinstance(yt_data, dict) else yt_data
    results.append(("YouTube API", yt_ok, yt_msg))
    all_ok = all_ok and yt_ok

    # Check Database
    db_ok, db_msg = check_database(db)
    results.append(("Database", db_ok, db_msg))
    all_ok = all_ok and db_ok

    # v4.0.7: Removed deprecated cleanup_old_not_found() call
    # Not-found entries are now tracked in queue table, not video_ratings

    # Log concise summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Startup Health Check")
    logger.info("=" * 60)

    for component, ok, msg in results:
        status = "✓" if ok else "✗"
        logger.info(f"{status} {component}: {msg}")

    if all_ok:
        logger.info("✓ All systems operational")
    else:
        logger.warning("⚠ Some components have issues")

    logger.info("=" * 60)
    logger.info("")

    # v4.0.35: Return individual check results to avoid duplicate API calls
    check_results = {
        'ha': (ha_ok, ha_data),
        'yt': (yt_ok, yt_data),
        'db': (db_ok, db_msg)
    }

    return all_ok, check_results