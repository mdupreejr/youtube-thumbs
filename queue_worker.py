#!/usr/bin/env python3
"""
Simple background queue worker - NO THREADS, NO COMPLEXITY.

This script runs as a separate process and processes queue items one at a time.
Runs independently of the Flask/Gunicorn web server.
ONLY ONE instance of this worker should run at a time (enforced by PID lock).
"""
import time
import sys
import os
import signal
from logger import logger
from database import get_database
from youtube_api import get_youtube_api
from quota_error import (
    QuotaExceededError,
    VideoNotFoundError,
    AuthenticationError,
    NetworkError,
    InvalidRequestError,
    YouTubeAPIError
)

# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logger.info(f"Queue worker received signal {signum}, shutting down...")
    running = False

    # Clean up PID file
    pid_file = '/tmp/youtube_thumbs_queue_worker.pid'
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
            logger.info("PID file removed")
    except Exception as e:
        logger.warning(f"Failed to remove PID file: {e}")


def get_last_quota_reset_time():
    """
    Calculate when quota last reset (midnight Pacific Time).
    YouTube API quota resets at midnight Pacific Time (UTC-8 or UTC-7 during DST).

    Returns:
        datetime: The last quota reset time in UTC
    """
    from datetime import datetime, timedelta, timezone

    # Get current time in UTC
    now_utc = datetime.now(timezone.utc)

    # Convert to Pacific Time (simplified: assume PST = UTC-8)
    # TODO: Handle PST/PDT transition properly
    pacific_offset = timedelta(hours=-8)
    now_pacific = now_utc + pacific_offset

    # Get midnight today in Pacific Time
    midnight_today_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert back to UTC
    midnight_today_utc = midnight_today_pacific - pacific_offset

    # If current time is before today's reset, use yesterday's reset
    if now_utc < midnight_today_utc:
        last_reset_utc = midnight_today_utc - timedelta(days=1)
    else:
        last_reset_utc = midnight_today_utc

    return last_reset_utc


def get_next_quota_reset_time():
    """
    Calculate when quota will next reset (midnight Pacific Time).

    Returns:
        datetime: The next quota reset time in UTC
    """
    from datetime import datetime, timedelta, timezone

    last_reset = get_last_quota_reset_time()
    next_reset = last_reset + timedelta(days=1)
    return next_reset


def check_quota_recently_exceeded(db):
    """
    Check if quota was exceeded since the last quota reset.
    YouTube API quota resets at midnight Pacific Time, so any quota error
    since the last reset means we should skip API calls until the next reset.

    Returns:
        bool: True if quota exceeded since last reset, False otherwise
    """
    try:
        from datetime import datetime, timezone

        with db._lock:
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

            if not row:
                return False

            last_quota_error = dict(row)
            error_time_str = last_quota_error.get('timestamp')

            if not error_time_str:
                return False

            # Parse timestamp
            if isinstance(error_time_str, str):
                error_dt = datetime.fromisoformat(error_time_str.replace('Z', '+00:00'))
            else:
                error_dt = error_time_str

            # Ensure error_dt has timezone
            if error_dt.tzinfo is None:
                error_dt = error_dt.replace(tzinfo=timezone.utc)

            # Get last quota reset time
            last_reset = get_last_quota_reset_time()
            next_reset = get_next_quota_reset_time()

            # If quota error occurred AFTER last reset, quota is still exhausted
            if error_dt > last_reset:
                now = datetime.now(timezone.utc)
                time_until_reset = next_reset - now
                hours_until = int(time_until_reset.total_seconds() / 3600)
                minutes_until = int((time_until_reset.total_seconds() % 3600) / 60)

                logger.info(f"Quota exceeded since last reset - skipping API call")
                logger.info(f"Quota will reset in {hours_until}h {minutes_until}m (midnight Pacific Time)")
                return True

            return False

    except Exception as e:
        logger.debug(f"Error checking quota status: {e}")
        return False  # If we can't check, allow the attempt


def process_next_item(db, yt_api):
    """
    Process the next item from the unified queue (rating or search).
    The queue automatically prioritizes ratings (priority=1) over searches (priority=2).

    Returns:
        'success': Processed an item
        'empty': Queue is empty
        'quota': Quota exceeded during processing
        'quota_recent': Quota exceeded recently (no attempt made)
    """
    # Check if quota was exceeded since last reset (midnight Pacific)
    if check_quota_recently_exceeded(db):
        logger.debug("Skipping queue processing - quota exceeded since last reset")
        return 'quota_recent'

    # Claim next item from unified queue
    item = db.claim_next_queue_item()
    if not item:
        return 'empty'

    queue_id = item['id']
    item_type = item['type']
    payload = item['payload']

    try:
        if item_type == 'rating':
            # Process rating
            video_id = payload['yt_video_id']
            rating = payload['rating']
            logger.info(f"Processing rating: {video_id} as {rating}")

            try:
                # Check current rating first to avoid unnecessary API calls
                current_rating = yt_api.get_video_rating(video_id)

                if current_rating == rating:
                    # Already rated with desired rating - mark as complete
                    logger.info(f"✓ Video {video_id} already rated as {rating} - marking complete")
                    db.record_rating(video_id, rating)
                    db.mark_queue_item_completed(queue_id)
                else:
                    # Needs rating - attempt the API call
                    success = yt_api.set_video_rating(video_id, rating)
                    if success:
                        db.record_rating(video_id, rating)
                        db.mark_queue_item_completed(queue_id)
                        logger.info(f"✓ Successfully rated {video_id} as {rating}")
                    else:
                        # API returned False (unexpected - should raise exception instead)
                        error_msg = "YouTube API returned False (unexpected)"
                        logger.error(f"✗ {error_msg} for {video_id}")
                        db.mark_queue_item_failed(queue_id, error_msg)

            except QuotaExceededError:
                # Re-raise quota errors to outer handler (will sleep until midnight)
                raise

            except VideoNotFoundError as e:
                # Video doesn't exist - permanent error, don't retry
                error_msg = f"Video not found: {video_id}"
                logger.warning(f"✗ {error_msg} - marking as permanently failed")
                db.mark_queue_item_failed(queue_id, error_msg)
                # Don't return quota error - continue processing

            except AuthenticationError as e:
                # CRITICAL: Authentication failed - stop processing entirely
                error_msg = f"YouTube authentication failed: {str(e)}"
                logger.error(f"CRITICAL: {error_msg}")
                logger.error("Stopping queue worker - fix authentication before restarting")
                db.mark_queue_item_failed(queue_id, error_msg)
                # Re-raise to stop the worker
                raise

            except NetworkError as e:
                # Transient network error - mark as failed and will retry later
                error_msg = f"Network error: {str(e)}"
                logger.warning(f"✗ {error_msg} for {video_id} - will retry")
                db.mark_queue_item_failed(queue_id, error_msg)
                # Continue processing other items

            except InvalidRequestError as e:
                # Invalid request - permanent error, don't retry
                error_msg = f"Invalid request: {str(e)}"
                logger.error(f"✗ {error_msg} for {video_id} - marking as permanently failed")
                db.mark_queue_item_failed(queue_id, error_msg)
                # This indicates a bug - we should see this in logs

            except YouTubeAPIError as e:
                # Generic YouTube API error - mark as failed and will retry
                error_msg = f"YouTube API error: {str(e)}"
                logger.error(f"✗ {error_msg} for {video_id}")
                db.mark_queue_item_failed(queue_id, error_msg)

        elif item_type == 'search':
            # Process search
            title = payload['ha_title']
            logger.info(f"Processing search: {title}")

            # Build media dict from payload
            ha_media = {
                'title': payload['ha_title'],
                'artist': payload['ha_artist'],
                'album': payload['ha_album'],
                'content_id': payload['ha_content_id'],
                'duration': payload['ha_duration'],
                'app_name': payload['ha_app_name']
            }

            # Search using the wrapper (includes caching)
            from helpers.search_helpers import search_and_match_video
            from helpers.video_helpers import prepare_video_upsert
            video = search_and_match_video(ha_media, yt_api, db)

            if video and video.get('yt_video_id'):
                video_id = video['yt_video_id']
                logger.info(f"✓ Search found video {video_id} for '{title}'")

                # v4.0.0: Add matched video to video_ratings table
                try:
                    # Prepare full video data for insertion
                    video_data = prepare_video_upsert(video, ha_media, source='queue_search')
                    db.upsert_video(video_data)
                    logger.info(f"  → Added video {video_id} to video_ratings table")
                except Exception as e:
                    logger.error(f"  ✗ Failed to add video {video_id} to database: {e}")
                    db.mark_queue_item_failed(queue_id, f"Failed to add to database: {str(e)}")
                    return 'success'  # Continue processing other items

                # If there's a callback rating, enqueue it
                callback_rating = payload.get('callback_rating')
                if callback_rating:
                    db.enqueue_rating(video_id, callback_rating)
                    logger.info(f"  → Enqueued {callback_rating} rating for {video_id}")

                db.mark_queue_item_completed(queue_id)
            else:
                db.mark_queue_item_failed(queue_id, "No matching video found")
                logger.warning(f"✗ No video found for '{title}'")

        else:
            logger.error(f"Unknown queue item type: {item_type}")
            db.mark_queue_item_failed(queue_id, f"Unknown item type: {item_type}")

        return 'success'

    except QuotaExceededError:
        # Quota exceeded - mark failed and sleep until midnight Pacific
        error_msg = "Quota exceeded - will retry when quota resets"
        db.mark_queue_item_failed(queue_id, error_msg)
        logger.warning(f"YouTube quota exceeded during processing - will sleep until midnight Pacific")
        return 'quota'

    except AuthenticationError as e:
        # CRITICAL: Authentication failed - this should have been caught earlier
        error_msg = f"CRITICAL: YouTube authentication failed: {str(e)}"
        db.mark_queue_item_failed(queue_id, str(e))
        logger.error(error_msg)
        logger.error("Stopping queue worker - fix authentication before restarting")
        # Re-raise to stop worker
        raise

    except Exception as e:
        # Unexpected error - log with full context and continue processing
        error_msg = f"Unexpected error processing {item_type}"
        logger.error(f"{error_msg}: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.mark_queue_item_failed(queue_id, str(e))
        return 'success'  # Continue processing other items


def main():
    """Main worker loop - simple and straightforward."""
    global running
    from datetime import datetime, timezone

    # Ensure only ONE queue worker runs at a time
    pid_file = '/tmp/youtube_thumbs_queue_worker.pid'

    try:
        # Check if PID file exists
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                old_pid = int(f.read().strip())

            # Check if process is still running
            try:
                os.kill(old_pid, 0)  # Check if process exists
                logger.error(f"Queue worker already running (PID {old_pid}). Exiting to prevent duplicate workers.")
                sys.exit(1)
            except OSError:
                # Process doesn't exist, remove stale PID file
                logger.warning(f"Removing stale PID file (process {old_pid} no longer exists)")
                os.remove(pid_file)

        # Write our PID to file
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"Queue worker PID file created: {pid_file}")

    except Exception as e:
        logger.error(f"Failed to create PID file: {e}")
        sys.exit(1)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Queue worker starting (UNIFIED QUEUE MODE: 1 item per minute)")
    logger.info("This is a standalone process, not a thread")
    logger.info("ONLY ONE queue worker runs - enforced by PID lock")
    logger.info("Processing from unified queue (ratings priority=1, searches priority=2)")

    # Initialize database and YouTube API
    db = get_database()

    while running:
        try:
            # Get YouTube API instance
            try:
                yt_api = get_youtube_api()
            except Exception as e:
                logger.error(f"Failed to get YouTube API: {e}")
                time.sleep(60)
                continue

            # Process next item from unified queue (automatically prioritized)
            result = process_next_item(db, yt_api)

            if result == 'quota' or result == 'quota_recent':
                # Quota exceeded - sleep until midnight Pacific (quota reset time)
                next_reset = get_next_quota_reset_time()
                now = datetime.now(timezone.utc)
                time_until_reset = (next_reset - now).total_seconds()

                # Add a small buffer to ensure we're past the reset time
                time_until_reset += 60  # 1 minute buffer

                hours = int(time_until_reset / 3600)
                minutes = int((time_until_reset % 3600) / 60)

                logger.info(f"Quota exceeded - sleeping until midnight Pacific ({hours}h {minutes}m)")
                time.sleep(time_until_reset)
                continue

            elif result == 'success':
                # Processed an item, sleep 60 seconds before next
                logger.debug("Item processed, sleeping 60 seconds")
                time.sleep(60)
                continue

            elif result == 'empty':
                # Queue is empty, sleep 60 seconds
                logger.debug("Queue empty, sleeping 60 seconds")
                time.sleep(60)
                continue

        except Exception as e:
            logger.error(f"Queue worker error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            time.sleep(60)

    # Clean up PID file on normal exit
    pid_file = '/tmp/youtube_thumbs_queue_worker.pid'
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
            logger.info("PID file removed on shutdown")
    except Exception as e:
        logger.warning(f"Failed to remove PID file on shutdown: {e}")

    logger.info("Queue worker stopped")


if __name__ == '__main__':
    main()
