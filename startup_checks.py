"""
Startup checks to verify all components are working properly
"""

from typing import Tuple, Optional
from logger import logger


def check_home_assistant_api(ha_api) -> Tuple[bool, str]:
    """Test Home Assistant API connectivity and configuration."""
    try:
        logger.info("=" * 60)
        logger.info("STARTUP CHECK: Home Assistant API")
        logger.info("=" * 60)

        # Log configuration
        logger.info(f"URL: {ha_api.url}")
        logger.info(f"Entity: {ha_api.entity}")
        logger.info(f"Token present: {'Yes' if ha_api.token else 'No'}")

        if not ha_api.token:
            logger.error("✗ No authentication token found")
            return False, "No authentication token"

        # Test getting current media
        logger.info("Testing media player state...")
        media = ha_api.get_current_media()

        if media:
            logger.info(f"✓ API working - Media playing: '{media.get('title')}' by {media.get('artist')}")
            if media.get('duration'):
                logger.info(f"  Duration: {media.get('duration')}s")
            else:
                logger.warning(f"  ⚠ No duration available - tracking may not work")
            return True, "API working, media detected"
        else:
            # Try to get the state even if not playing
            import requests
            url = f"{ha_api.url}/api/states/{ha_api.entity}"
            response = ha_api.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                state = data.get('state', 'unknown')
                logger.info(f"✓ API working - Media player state: {state}")

                if state == 'unavailable':
                    logger.warning("  ⚠ Media player is unavailable - check if device is online")
                elif state in ['idle', 'paused', 'standby', 'off']:
                    logger.info(f"  Media player is {state} - start playing to track songs")
                else:
                    logger.info(f"  Media player state: {state}")

                return True, f"API working, player {state}"
            elif response.status_code == 404:
                logger.error(f"✗ Entity not found: {ha_api.entity}")
                logger.error("  Check your media_player_entity configuration")
                return False, f"Entity {ha_api.entity} not found"
            else:
                logger.error(f"✗ API error: HTTP {response.status_code}")
                return False, f"API error: HTTP {response.status_code}"

    except Exception as e:
        logger.error(f"✗ Home Assistant API check failed: {str(e)}")
        return False, str(e)


def check_youtube_api(yt_api, db=None) -> Tuple[bool, str]:
    """Test YouTube API authentication and quota."""
    try:
        logger.info("=" * 60)
        logger.info("STARTUP CHECK: YouTube API")
        logger.info("=" * 60)

        if not yt_api:
            logger.error("✗ YouTube API not initialized")
            return False, "API not initialized"

        if not yt_api.youtube:
            logger.error("✗ YouTube client not authenticated")
            return False, "Not authenticated"

        # Get detailed API usage from database if available
        api_calls_24h = 0
        quota_used_24h = 0
        failed_calls_24h = 0
        by_method = []
        last_quota_error = None

        if db:
            try:
                # Get 24-hour summary with detailed breakdown
                from datetime import datetime, timedelta
                summary_data = db.get_api_call_summary(hours=24)
                summary = summary_data.get('summary', {})
                api_calls_24h = summary.get('total_calls', 0)
                quota_used_24h = summary.get('total_quota', 0) or 0
                failed_calls_24h = summary.get('failed_calls', 0) or 0
                by_method = summary_data.get('by_method', [])

                # Find last quota error
                with db._lock:
                    cursor = db._conn.execute(
                        """
                        SELECT timestamp, error_message, api_method, quota_cost
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
            except Exception as e:
                logger.debug(f"Could not fetch API usage stats: {e}")

        # Check if quota is already known to be exceeded
        if last_quota_error:
            from helpers.time_helpers import format_relative_time
            error_time = last_quota_error.get('timestamp')
            if error_time:
                try:
                    from datetime import datetime
                    if isinstance(error_time, str):
                        error_dt = datetime.fromisoformat(error_time.replace('Z', '+00:00'))
                    else:
                        error_dt = error_time

                    # If quota error was recent (within last 12 hours), don't attempt API call
                    from datetime import timedelta, timezone
                    now = datetime.now(timezone.utc)
                    if (now - error_dt.replace(tzinfo=timezone.utc)) < timedelta(hours=12):
                        relative_time = format_relative_time(error_dt)

                        msg_parts = [
                            "❌ YouTube API quota exceeded (not attempting call)",
                            "",
                            f"Last quota error: {relative_time}",
                            f"  ({error_dt.strftime('%Y-%m-%d %H:%M:%S UTC')})",
                            "",
                            f"API usage (last 24h):",
                            f"  • Total calls: {api_calls_24h:,}",
                            f"  • Quota used: {quota_used_24h:,} / 10,000",
                            f"  • Failed calls: {failed_calls_24h}"
                        ]

                        # Show breakdown by method
                        if by_method:
                            msg_parts.append("")
                            msg_parts.append("Quota usage by method:")
                            for method in by_method[:5]:
                                quota = method.get('quota_used', 0) or 0
                                calls = method.get('call_count', 0)
                                method_name = method.get('api_method', 'unknown')
                                msg_parts.append(f"  • {method_name}: {calls} calls ({quota:,} quota)")

                        # Show quota reset info
                        from datetime import timezone, timedelta
                        now_utc = datetime.now(timezone.utc)
                        pacific_offset = timedelta(hours=-8)
                        now_pacific = now_utc + pacific_offset
                        tomorrow_pacific = (now_pacific + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                        time_until_reset = tomorrow_pacific - now_pacific
                        hours_until = int(time_until_reset.total_seconds() / 3600)
                        minutes_until = int((time_until_reset.total_seconds() % 3600) / 60)

                        msg_parts.append("")
                        msg_parts.append(f"Quota resets in: {hours_until}h {minutes_until}m")
                        msg_parts.append(f"  (Midnight Pacific Time)")
                        msg_parts.append("")
                        msg_parts.append("Wait for quota reset or increase your quota in Google Cloud Console.")

                        logger.info("Skipping YouTube API test - quota exceeded recently")
                        return False, "\n".join(msg_parts)
                except:
                    pass

        # Try a simple API call to verify authentication
        logger.info("Testing YouTube API authentication...")

        try:
            # Search for a short common video to test API
            request = yt_api.youtube.search().list(
                part='id',
                q='test',
                maxResults=1,
                type='video'
            )
            response = request.execute()

            if 'items' in response:
                logger.info("✓ YouTube API authenticated and working")
                logger.info("  API calls available - quota OK")
                quota_remaining = max(0, 10000 - quota_used_24h)

                msg_parts = [
                    "✓ API authenticated and working",
                    "",
                    f"API usage (last 24h):"
                ]

                if api_calls_24h > 0:
                    msg_parts.append(f"  • Total calls: {api_calls_24h:,}")
                    msg_parts.append(f"  • Quota used: {quota_used_24h:,} / 10,000")
                    msg_parts.append(f"  • Quota remaining: ~{quota_remaining:,}")

                    if failed_calls_24h > 0:
                        msg_parts.append(f"  • Failed calls: {failed_calls_24h}")

                    # Show top methods by quota usage
                    if by_method:
                        msg_parts.append("")
                        msg_parts.append("Top API methods by quota:")
                        for i, method in enumerate(by_method[:3]):
                            quota = method.get('quota_used', 0) or 0
                            calls = method.get('call_count', 0)
                            method_name = method.get('api_method', 'unknown')
                            msg_parts.append(f"  • {method_name}: {calls} calls ({quota:,} quota)")
                else:
                    msg_parts.append("  • No API calls in last 24 hours")
                    msg_parts.append("  • Daily quota: 10,000 units")

                return True, "\n".join(msg_parts)
            else:
                logger.warning("⚠ YouTube API returned unexpected response")
                msg_parts = [
                    "⚠️ API authenticated but response unexpected",
                    "",
                    f"API usage (last 24h):",
                    f"  • Calls: {api_calls_24h}",
                    f"  • Quota used: {quota_used_24h:,} / 10,000"
                ]
                return True, "\n".join(msg_parts)

        except Exception as api_error:
            error_str = str(api_error)
            if 'quota' in error_str.lower():
                # Single consolidated error message
                msg_parts = [
                    "❌ YouTube API quota exceeded",
                    "",
                    "Wait for quota reset or increase your quota in Google Cloud Console.",
                    ""
                ]

                # Show when quota was exceeded
                if last_quota_error:
                    from helpers.time_helpers import format_relative_time
                    error_time = last_quota_error.get('timestamp')
                    if error_time:
                        try:
                            if isinstance(error_time, str):
                                error_dt = datetime.fromisoformat(error_time.replace('Z', '+00:00'))
                            else:
                                error_dt = error_time
                            relative_time = format_relative_time(error_dt)
                            msg_parts.append(f"Last quota error: {relative_time}")
                            msg_parts.append(f"  ({error_dt.strftime('%Y-%m-%d %H:%M:%S UTC')})")
                            msg_parts.append("")
                        except:
                            pass

                # Show API usage breakdown
                msg_parts.append(f"API usage (last 24h):")
                msg_parts.append(f"  • Total calls: {api_calls_24h:,}")
                msg_parts.append(f"  • Quota used: {quota_used_24h:,} / 10,000")
                msg_parts.append(f"  • Failed calls: {failed_calls_24h}")

                # Show breakdown by method
                if by_method:
                    msg_parts.append("")
                    msg_parts.append("Quota usage by method:")
                    for method in by_method[:5]:
                        quota = method.get('quota_used', 0) or 0
                        calls = method.get('call_count', 0)
                        method_name = method.get('api_method', 'unknown')
                        msg_parts.append(f"  • {method_name}: {calls} calls ({quota:,} quota)")

                # Show quota reset info (Pacific Time = UTC-8 or UTC-7 during DST)
                from datetime import datetime, timezone, timedelta
                now_utc = datetime.now(timezone.utc)

                # Calculate Pacific time offset (PST = -8, PDT = -7)
                # Simplified: assume PST (UTC-8)
                pacific_offset = timedelta(hours=-8)
                now_pacific = now_utc + pacific_offset

                # Quota resets at midnight Pacific time
                tomorrow_pacific = (now_pacific + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                time_until_reset = tomorrow_pacific - now_pacific
                hours_until = int(time_until_reset.total_seconds() / 3600)
                minutes_until = int((time_until_reset.total_seconds() % 3600) / 60)

                msg_parts.append("")
                msg_parts.append(f"Quota resets in: {hours_until}h {minutes_until}m")
                msg_parts.append(f"  (Midnight Pacific Time)")

                return False, "\n".join(msg_parts)
            elif 'invalid' in error_str.lower() and 'credentials' in error_str.lower():
                return False, "❌ Invalid credentials - Re-run OAuth flow to refresh credentials"
            else:
                msg_parts = [
                    f"❌ API error: {error_str}",
                    "",
                    f"API usage (last 24h):",
                    f"  • Calls: {api_calls_24h}",
                    f"  • Quota used: {quota_used_24h:,}"
                ]
                return False, "\n".join(msg_parts)

    except Exception as e:
        logger.error(f"✗ YouTube API check failed: {str(e)}")
        return False, str(e)


def check_database(db) -> Tuple[bool, str]:
    """Test database connectivity and report statistics."""
    try:
        logger.info("=" * 60)
        logger.info("STARTUP CHECK: Database")
        logger.info("=" * 60)

        logger.info(f"Database path: {db.db_path}")

        if not db.db_path.exists():
            logger.warning("⚠ Database file doesn't exist yet - will be created on first use")
            return True, "Database will be created"

        # Test connection and get statistics
        with db._lock:
            # Count all videos
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings")
            total_videos = cursor.fetchone()['count']

            # Count matched videos (successfully found on YouTube)
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE yt_match_pending = 0")
            matched_videos = cursor.fetchone()['count']

            # Count pending videos (not yet matched to YouTube)
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE yt_match_pending = 1")
            pending_videos = cursor.fetchone()['count']

            # Get pending reason breakdown
            cursor = db._conn.execute("""
                SELECT pending_reason, COUNT(*) as count
                FROM video_ratings
                WHERE yt_match_pending = 1
                GROUP BY pending_reason
            """)
            pending_reasons = {row['pending_reason']: row['count'] for row in cursor.fetchall()}

            # Count rated videos breakdown
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'like' AND yt_match_pending = 0")
            liked_videos = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'dislike' AND yt_match_pending = 0")
            disliked_videos = cursor.fetchone()['count']

            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating = 'none' AND yt_match_pending = 0")
            unrated_videos = cursor.fetchone()['count']

            # Total plays
            cursor = db._conn.execute("SELECT SUM(play_count) as total FROM video_ratings WHERE yt_match_pending = 0")
            total_plays = cursor.fetchone()['total'] or 0

            # Unique channels
            cursor = db._conn.execute("SELECT COUNT(DISTINCT yt_channel_id) as count FROM video_ratings WHERE yt_match_pending = 0 AND yt_channel_id IS NOT NULL")
            unique_channels = cursor.fetchone()['count']

            # Count pending ratings queue (v1.50.0: now stored in video_ratings columns)
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings WHERE rating_queue_pending IS NOT NULL")
            pending_ratings = cursor.fetchone()['count']

            # Get recent videos (all videos, not just matched)
            cursor = db._conn.execute("""
                SELECT ha_title, date_last_played, yt_match_pending
                FROM video_ratings
                WHERE date_last_played IS NOT NULL
                ORDER BY date_last_played DESC
                LIMIT 3
            """)
            recent_videos = cursor.fetchall()

        logger.info("✓ Database connected and working")
        logger.info(f"  Total videos: {total_videos} ({matched_videos} matched, {pending_videos} unmatched)")

        # Show unmatched reason breakdown if there are unmatched videos
        if pending_videos > 0 and pending_reasons:
            reason_strs = []
            for reason, count in pending_reasons.items():
                reason_label = reason or 'unknown'
                reason_strs.append(f"{count} {reason_label}")
            logger.info(f"    Unmatched reasons: {', '.join(reason_strs)}")

        logger.info(f"  Ratings: {liked_videos} liked, {disliked_videos} disliked, {unrated_videos} unrated")
        logger.info(f"  Total plays: {total_plays:,} across {unique_channels} channels")

        # Show queue status (the ONLY pending operation)
        if pending_ratings > 0:
            logger.info(f"  Queue: {pending_ratings} rating(s) waiting to sync to YouTube")

        if recent_videos:
            logger.info("  Recent plays:")
            for video in recent_videos:
                logger.info(f"    - {video['ha_title'][:50]}")
        elif total_videos == 0:
            logger.info("  No videos tracked yet - play something to start tracking")
        else:
            logger.info("  No recent plays recorded")

        # Build comprehensive status message
        pending_str = f"{pending_videos} unmatched"
        if pending_videos > 0 and pending_reasons:
            # Add most common pending reason
            top_reason = max(pending_reasons.items(), key=lambda x: x[1])
            reason_label = top_reason[0] or 'unknown'
            if len(pending_reasons) == 1:
                pending_str = f"{pending_videos} unmatched ({reason_label})"
            else:
                pending_str = f"{pending_videos} unmatched ({top_reason[1]} {reason_label}, {len(pending_reasons)-1} other)"

        status_parts = [
            f"Videos: {total_videos} total, {matched_videos} matched, {pending_str}",
            f"Ratings: {liked_videos}👍 {disliked_videos}👎 {unrated_videos}⭐",
            f"Activity: {total_plays:,} plays across {unique_channels} channels"
        ]
        if pending_ratings > 0:
            status_parts.append(f"Sync Queue: {pending_ratings} rating{'s' if pending_ratings != 1 else ''} waiting to sync")

        return True, "DB OK:\n" + "\n".join(status_parts)

    except Exception as e:
        logger.error(f"✗ Database check failed: {str(e)}")
        return False, str(e)


def run_startup_checks(ha_api, yt_api, db) -> bool:
    """Run all startup checks and report status."""
    logger.info("")
    logger.info("░" * 60)
    logger.info("░         YouTube Thumbs - Startup Health Check          ░")
    logger.info("░" * 60)
    logger.info("")

    all_ok = True
    results = []

    # Check Home Assistant API
    ha_ok, ha_msg = check_home_assistant_api(ha_api)
    results.append(("Home Assistant API", ha_ok, ha_msg))
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
                logger.info(f"  Cleaned up {deleted} old not-found cache entries")
        except AttributeError:
            logger.warning("Database cleanup method not available - old entries may accumulate")
        except Exception as e:
            # Don't fail startup for cleanup errors but make them visible
            logger.warning(f"Failed to cleanup not-found cache: {e}")

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("STARTUP CHECK SUMMARY")
    logger.info("=" * 60)

    for component, ok, msg in results:
        status = "✓" if ok else "✗"
        logger.info(f"{status} {component}: {msg}")

    if all_ok:
        logger.info("")
        logger.info("✓ All systems operational - addon ready!")
        logger.info("")
    else:
        logger.info("")
        logger.warning("⚠ Some components have issues - check logs above")
        logger.info("")

    logger.info("=" * 60)
    logger.info("")

    return all_ok