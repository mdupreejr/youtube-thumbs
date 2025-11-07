"""
Startup checks to verify all components are working properly
"""

from typing import Tuple, Optional
from logger import logger


def check_home_assistant_api(ha_api) -> Tuple[bool, str]:
    """Test Home Assistant API connectivity and configuration."""
    try:
        if not ha_api.token:
            return False, "No authentication token"

        # Test getting current media
        media = ha_api.get_current_media()

        if media:
            return True, f"Connected, playing: {media.get('title', 'Unknown')}"
        else:
            # Try to get the state even if not playing
            import requests
            url = f"{ha_api.url}/api/states/{ha_api.entity}"
            response = ha_api.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                state = data.get('state', 'unknown')
                return True, f"Connected, player {state}"
            elif response.status_code == 404:
                return False, f"Entity {ha_api.entity} not found"
            else:
                return False, f"HTTP {response.status_code}"

    except Exception as e:
        return False, str(e)


def check_youtube_api(yt_api, db=None) -> Tuple[bool, str]:
    """Test YouTube API authentication and quota."""
    try:
        if not yt_api or not yt_api.youtube:
            return False, "Not authenticated"

        # Check queue worker status
        import os
        worker_running = False
        pid_file = '/tmp/youtube_thumbs_queue_worker.pid'
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                os.kill(pid, 0)  # Check if process exists
                worker_running = True
            except (OSError, ValueError):
                pass

        # Check for quota exceeded status
        if db:
            try:
                from datetime import datetime, timedelta, timezone

                # Get quota usage and call stats
                summary_data = db.get_api_call_summary(hours=24)
                summary = summary_data.get('summary', {})
                quota_used = summary.get('total_quota', 0) or 0
                total_calls = summary.get('total_calls', 0) or 0

                # Get queue size
                with db._lock:
                    cursor = db._conn.execute(
                        "SELECT COUNT(*) as count FROM queue WHERE status = 'pending'"
                    )
                    queue_size = cursor.fetchone()['count']

                # Find last quota error
                with db._lock:
                    cursor = db._conn.execute(
                        """
                        SELECT timestamp FROM api_call_log
                        WHERE success = 0
                          AND (error_message LIKE '%quota%' OR error_message LIKE '%Quota%')
                        ORDER BY timestamp DESC
                        LIMIT 1
                        """
                    )
                    row = cursor.fetchone()

                    if row:
                        error_time = row['timestamp']
                        if isinstance(error_time, str):
                            error_dt = datetime.fromisoformat(error_time.replace('Z', '+00:00'))
                        else:
                            error_dt = error_time

                        if error_dt.tzinfo is None:
                            error_dt = error_dt.replace(tzinfo=timezone.utc)

                        # Check if error was since last quota reset
                        now_utc = datetime.now(timezone.utc)
                        pacific_offset = timedelta(hours=-8)
                        now_pacific = now_utc + pacific_offset
                        midnight_today_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
                        last_reset_utc = midnight_today_pacific - pacific_offset

                        if now_utc < last_reset_utc:
                            last_reset_utc -= timedelta(days=1)

                        if error_dt > last_reset_utc:
                            return False, f"Quota exceeded ({quota_used:,}/10,000 used), worker paused until midnight PT"

                # Build status message
                worker_status = "running" if worker_running else "NOT RUNNING"
                msg_parts = [f"Authenticated, quota: {quota_used:,}/10,000 (24h)"]

                if queue_size > 0 and not worker_running:
                    msg_parts.append(f"⚠️ WARNING: Queue worker {worker_status}! {queue_size} items pending")
                elif queue_size > 0:
                    msg_parts.append(f"Worker: {worker_status}, processing {queue_size} items")
                else:
                    msg_parts.append(f"Worker: {worker_status}")

                if total_calls == 0 and queue_size > 0:
                    msg_parts.append("⚠️ No API calls in 24h but queue has items - check worker logs")

                return True, "\n".join(msg_parts)

            except Exception:
                pass

        return True, "Authenticated"

    except Exception as e:
        return False, str(e)


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


def run_startup_checks(ha_api, yt_api, db) -> bool:
    """Run all startup checks and report status."""
    all_ok = True
    results = []

    # Check Home Assistant API
    ha_ok, ha_msg = check_home_assistant_api(ha_api)
    results.append(("Home Assistant", ha_ok, ha_msg))
    all_ok = all_ok and ha_ok

    # Check YouTube API
    yt_ok, yt_msg = check_youtube_api(yt_api, db)
    results.append(("YouTube API", yt_ok, yt_msg))
    all_ok = all_ok and yt_ok

    # Check Database
    db_ok, db_msg = check_database(db)
    results.append(("Database", db_ok, db_msg))
    all_ok = all_ok and db_ok

    # Cleanup old not-found cache entries (silently)
    if db_ok:
        try:
            deleted = db.cleanup_old_not_found(days=2)
            if deleted > 0:
                logger.debug(f"Cleaned up {deleted} old not-found cache entries")
        except Exception:
            pass  # Don't log cleanup errors

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

    return all_ok