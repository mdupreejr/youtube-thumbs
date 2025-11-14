"""
Startup checks to verify all components are working properly
"""

from typing import Tuple, Optional
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)


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
                'quota': {
                    'exceeded': True,
                    'time_until_reset': next_reset_str,
                    'used': 10000,  # Assume quota fully used when exceeded
                    'total': 10000,
                    'percent': 100.0
                },
                'queue': {},
                'performance': {},
                'api_stats': {}
            }
            return True, {'message': pause_msg, 'details': details}

        # Quota not exceeded - verify authentication without API call
        # Check if token file exists and has valid credentials
        token_valid = False
        try:
            import os
            token_file = 'token.json'
            if os.path.exists(token_file):
                # Token file exists - credentials should be valid
                # Actual auth errors will be caught on first real API call (search/rating)
                token_valid = True
                logger.debug("YouTube API token file exists - authentication assumed valid")
            else:
                logger.warning("YouTube API token file not found - authentication may be required")
        except Exception as e:
            logger.error(f"Error checking token file: {e}")

        if not token_valid:
            return False, {'message': "Token file not found - please authenticate", 'details': {
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

                # Calculate time until next reset if not already calculated
                if next_reset_str is None:
                    now_utc = datetime.now(timezone.utc)

                    # Determine Pacific Time offset based on DST
                    # DST in Pacific Time runs from 2nd Sunday in March to 1st Sunday in November
                    # During DST (PDT): UTC-7, Standard (PST): UTC-8
                    # For simplicity, we'll check if we're in the DST period
                    month = now_utc.month
                    if 3 <= month <= 11:
                        # Rough DST check (March through November)
                        # More precise would check exact DST transition dates
                        if month > 3 and month < 11:
                            # Definitely DST (April through October)
                            pacific_offset = timedelta(hours=-7)
                        elif month == 3:
                            # March: DST starts 2nd Sunday, approximate as after March 10
                            if now_utc.day >= 10:
                                pacific_offset = timedelta(hours=-7)
                            else:
                                pacific_offset = timedelta(hours=-8)
                        else:  # November
                            # November: DST ends 1st Sunday, approximate as before Nov 7
                            if now_utc.day < 7:
                                pacific_offset = timedelta(hours=-7)
                            else:
                                pacific_offset = timedelta(hours=-8)
                    else:
                        # December through February: Standard time
                        pacific_offset = timedelta(hours=-8)

                    now_pacific = now_utc + pacific_offset
                    midnight_today_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
                    midnight_today_utc = midnight_today_pacific - pacific_offset

                    if now_utc < midnight_today_utc:
                        last_reset_utc = midnight_today_utc - timedelta(days=1)
                    else:
                        last_reset_utc = midnight_today_utc

                    next_reset_utc = last_reset_utc + timedelta(days=1)
                    time_until_reset = next_reset_utc - now_utc
                    hours_until = int(time_until_reset.total_seconds() / 3600)
                    minutes_until = int((time_until_reset.total_seconds() % 3600) / 60)
                    next_reset_str = f"{hours_until}h {minutes_until}m"

                # Populate details
                details['quota'] = {
                    'used': quota_used,
                    'total': 10000,
                    'percent': (quota_used / 10000 * 100) if quota_used > 0 else 0,
                    'exceeded': quota_recently_exceeded,
                    'time_until_reset': next_reset_str
                }

                # Check queue pause state
                pause_file = '/tmp/youtube_thumbs_queue_paused'
                queue_paused = os.path.exists(pause_file)

                details['queue'] = {
                    'total': queue_stats.get('total_items', 0),
                    'pending': queue_stats.get('pending', 0),
                    'processing': queue_stats.get('processing', 0),
                    'completed': queue_stats.get('completed', 0),
                    'failed': queue_stats.get('failed', 0),
                    'pending_searches': queue_stats.get('pending_searches', 0),
                    'pending_ratings': queue_stats.get('pending_ratings', 0),
                    'paused': queue_paused
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
                if quota_recently_exceeded:
                    message = f"⚠️ QUOTA EXCEEDED • Worker paused until midnight PT (in {next_reset_str})"
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


def check_database(db) -> Tuple[bool, dict]:
    """Test database connectivity and report detailed statistics for all tables."""
    try:
        if not db.db_path.exists():
            return True, {
                'message': "Will be created on first use",
                'details': {}
            }

        # Test connection and get statistics
        with db._lock:
            # Get database file size
            import os
            db_size_bytes = os.path.getsize(db.db_path)
            db_size_mb = db_size_bytes / (1024 * 1024)

            # Build table statistics
            tables_info = []

            # 1. video_ratings table
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings")
            total_videos = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'like'")
            liked = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'dislike'")
            disliked = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating IS NULL")
            unrated = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT MAX(date_last_played) as last_updated FROM video_ratings")
            video_last_updated = cursor.fetchone()['last_updated']

            tables_info.append({
                'name': 'video_ratings',
                'label': '📹 Video Ratings',
                'count': total_videos,
                'details': f"{liked} liked, {disliked} disliked, {unrated} unrated",
                'last_updated': video_last_updated
            })

            # 2. queue table
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM queue")
            total_queue = cursor.fetchone()['count']

            cursor = db._conn.execute("""
                SELECT
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM queue
            """)
            queue_stats = cursor.fetchone()

            cursor = db._conn.execute("SELECT MAX(requested_at) as last_updated FROM queue")
            queue_last_updated = cursor.fetchone()['last_updated']

            tables_info.append({
                'name': 'queue',
                'label': '📋 Queue',
                'count': total_queue,
                'details': f"{queue_stats['pending'] or 0} pending, {queue_stats['completed'] or 0} completed, {queue_stats['failed'] or 0} failed",
                'last_updated': queue_last_updated
            })

            # 3. api_call_log table
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM api_call_log")
            total_api_calls = cursor.fetchone()['count']

            cursor = db._conn.execute("""
                SELECT
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed
                FROM api_call_log
            """)
            api_stats = cursor.fetchone()

            cursor = db._conn.execute("SELECT MAX(timestamp) as last_updated FROM api_call_log")
            api_last_updated = cursor.fetchone()['last_updated']

            tables_info.append({
                'name': 'api_call_log',
                'label': '📊 API Call Log',
                'count': total_api_calls,
                'details': f"{api_stats['successful'] or 0} successful, {api_stats['failed'] or 0} failed",
                'last_updated': api_last_updated
            })

            # 4. api_usage table (hourly aggregate)
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM api_usage")
            total_api_usage_days = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT MAX(date) as last_date FROM api_usage")
            api_usage_last_date = cursor.fetchone()['last_date']

            tables_info.append({
                'name': 'api_usage',
                'label': '⏱️ API Usage (Hourly)',
                'count': total_api_usage_days,
                'details': f"{total_api_usage_days} days tracked",
                'last_updated': api_usage_last_date
            })

            # 5. search_results_cache table
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM search_results_cache")
            total_cached = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT MAX(cached_at) as last_cached FROM search_results_cache")
            cache_last_updated = cursor.fetchone()['last_cached']

            cursor = db._conn.execute("SELECT COUNT(*) as count FROM search_results_cache WHERE expired = 0")
            valid_cache = cursor.fetchone()['count']

            tables_info.append({
                'name': 'search_results_cache',
                'label': '💾 Search Cache',
                'count': total_cached,
                'details': f"{valid_cache} valid, {total_cached - valid_cache} expired",
                'last_updated': cache_last_updated
            })

            # 6. stats_cache table
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM stats_cache")
            total_stats_cache = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT MAX(cached_at) as last_cached FROM stats_cache")
            stats_cache_last_updated = cursor.fetchone()['last_cached']

            tables_info.append({
                'name': 'stats_cache',
                'label': '📈 Stats Cache',
                'count': total_stats_cache,
                'details': f"{total_stats_cache} cached entries",
                'last_updated': stats_cache_last_updated
            })

        # Build concise summary message
        parts = [f"{total_videos} videos", f"{liked}👍 {disliked}👎"]
        if queue_stats['pending'] and queue_stats['pending'] > 0:
            parts.append(f"Queue: {queue_stats['pending']}")

        return True, {
            'message': ", ".join(parts),
            'details': {
                'db_path': str(db.db_path),
                'db_size_mb': round(db_size_mb, 2),
                'tables': tables_info
            }
        }

    except Exception as e:
        return False, {'message': str(e), 'details': {}}


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
    db_ok, db_data = check_database(db)
    db_msg = db_data.get('message', 'Unknown') if isinstance(db_data, dict) else db_data
    results.append(("Database", db_ok, db_msg))
    all_ok = all_ok and db_ok


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
        'db': (db_ok, db_data)
    }

    return all_ok, check_results