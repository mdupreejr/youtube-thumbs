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


def check_youtube_api(yt_api) -> Tuple[bool, str]:
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
                return True, "API authenticated and working"
            else:
                logger.warning("⚠ YouTube API returned unexpected response")
                return True, "API authenticated but response unexpected"

        except Exception as api_error:
            error_str = str(api_error)
            if 'quota' in error_str.lower():
                logger.error("✗ YouTube API quota exceeded")
                logger.error("  Wait for quota reset or increase your quota in Google Cloud Console")
                return False, "Quota exceeded"
            elif 'invalid' in error_str.lower() and 'credentials' in error_str.lower():
                logger.error("✗ YouTube API credentials invalid or expired")
                logger.error("  Re-run OAuth flow to refresh credentials")
                return False, "Invalid credentials"
            else:
                logger.error(f"✗ YouTube API error: {error_str}")
                return False, f"API error: {error_str}"

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
        logger.info(f"  Total videos: {total_videos} ({matched_videos} matched, {pending_videos} pending)")

        # Show pending reason breakdown if there are pending videos
        if pending_videos > 0 and pending_reasons:
            reason_strs = []
            for reason, count in pending_reasons.items():
                reason_label = reason or 'unknown'
                reason_strs.append(f"{count} {reason_label}")
            logger.info(f"    Pending reasons: {', '.join(reason_strs)}")

        logger.info(f"  Ratings: {liked_videos} liked, {disliked_videos} disliked, {unrated_videos} unrated")
        logger.info(f"  Total plays: {total_plays:,} across {unique_channels} channels")

        if pending_ratings > 0:
            logger.info(f"  Pending ratings to sync: {pending_ratings}")

        if recent_videos:
            logger.info("  Recent plays:")
            for video in recent_videos:
                logger.info(f"    - {video['ha_title'][:50]}")
        elif total_videos == 0:
            logger.info("  No videos tracked yet - play something to start tracking")
        else:
            logger.info("  No recent plays recorded")

        # Build comprehensive status message
        pending_str = f"{pending_videos} pending"
        if pending_videos > 0 and pending_reasons:
            # Add most common pending reason
            top_reason = max(pending_reasons.items(), key=lambda x: x[1])
            reason_label = top_reason[0] or 'unknown'
            if len(pending_reasons) == 1:
                pending_str = f"{pending_videos} pending ({reason_label})"
            else:
                pending_str = f"{pending_videos} pending ({top_reason[1]} {reason_label}, {len(pending_reasons)-1} other)"

        status_parts = [
            f"{total_videos} total ({matched_videos} matched, {pending_str})",
            f"Ratings: {liked_videos}👍 {disliked_videos}👎 {unrated_videos}⭐",
            f"{total_plays:,} plays",
            f"{unique_channels} channels"
        ]
        if pending_ratings > 0:
            status_parts.append(f"{pending_ratings} pending sync")

        return True, "DB OK: " + " • ".join(status_parts)

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
    yt_ok, yt_msg = check_youtube_api(yt_api)
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