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
import traceback
from datetime import datetime, timezone
from logging_helper import LoggingHelper, LogType
from database import get_database

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)
from youtube_api import get_youtube_api, set_database as set_youtube_api_database
from helpers.time_helpers import get_next_quota_reset_time
from helpers.api_helpers import check_quota_recently_exceeded
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
    # v4.0.5: Enhanced DEBUG logging for complete queue visibility
    logger.debug("Checking queue for next item...")

    # Check if quota was exceeded since last reset (midnight Pacific)
    if check_quota_recently_exceeded(db):
        logger.debug("Skipping queue processing - quota exceeded since last reset")
        return 'quota_recent'

    # Claim next item from unified queue
    item = db.claim_next_queue_item()
    if not item:
        logger.debug("Queue is empty - no items to process")
        return 'empty'

    queue_id = item['id']
    item_type = item['type']
    payload = item['payload']
    priority = item.get('priority', 'unknown')

    # v4.0.5: Log detailed queue item info at DEBUG level
    logger.debug(f"Claimed queue item #{queue_id} | Type: {item_type} | Priority: {priority}")
    logger.debug(f"Payload: {payload}")

    try:
        if item_type == 'rating':
            # Process rating
            video_id = payload['yt_video_id']
            rating = payload['rating']
            logger.info(f"Processing rating: {video_id} as {rating}")

            try:
                # v5.0.0: Check if already rated with same rating
                # This moves the "already rated" check from rating endpoint to queue worker
                existing_video = db.get_video(video_id)
                if existing_video and existing_video.get('rating') == rating:
                    # Already rated with same rating - just increment score locally
                    # No need to call YouTube API (it's idempotent anyway)
                    db.record_rating(video_id, rating)
                    db.mark_queue_item_completed(queue_id)
                    logger.info(f"✓ Already rated as {rating}, incremented score for {video_id}")
                else:
                    # New rating or changing rating - submit to YouTube
                    # YouTube API is idempotent - rating with same rating doesn't change anything
                    # This saves quota by not checking current rating first (1 unit saved per rating)
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
            artist = payload.get('ha_artist', '')
            album = payload.get('ha_album', '')

            # Build descriptive log message with available metadata
            search_info = f"'{title}'"
            metadata_parts = []
            if artist and artist not in ['Unknown', 'YouTube', '', None]:
                metadata_parts.append(f"artist: {artist}")
            if album and album not in ['Unknown', 'YouTube', '', None]:
                metadata_parts.append(f"album: {album}")

            if metadata_parts:
                search_info += f" ({', '.join(metadata_parts)})"

            logger.info(f"Processing search: {search_info}")

            # Build media dict from payload
            ha_media = {
                'title': payload['ha_title'],
                'artist': payload['ha_artist'],
                'album': payload['ha_album'],
                'content_id': payload['ha_content_id'],
                'duration': payload['ha_duration'],
                'app_name': payload['ha_app_name']
            }

            # v5.0.0: Check cache FIRST before searching (saves quota)
            # This moves cache checking from rating endpoint to queue worker
            from helpers.cache_helpers import find_cached_video
            from helpers.search_helpers import search_and_match_video
            from helpers.video_helpers import prepare_video_upsert
            import json

            video = find_cached_video(db, ha_media)
            api_debug_data = None

            if video and video.get('yt_video_id'):
                # Cache hit - skip YouTube search entirely
                logger.info(f"✓ Cache hit: '{title}' | YouTube ID: {video['yt_video_id']}")
                logger.debug("  → Skipped YouTube search due to cache hit")
            else:
                # Cache miss - search YouTube
                logger.debug(f"Cache miss for '{title}' - searching YouTube")

                # v4.0.64: Request API response data for debugging failed searches
                result = search_and_match_video(ha_media, yt_api, db, return_api_response=True)
                video, api_debug_data = result if result else (None, None)

            # Serialize API debug data for storage
            api_response_json = json.dumps(api_debug_data) if api_debug_data else None

            if video and video.get('yt_video_id'):
                video_id = video['yt_video_id']
                video_title = video.get('yt_title', title)
                artist = payload.get('ha_artist', '')
                logger.info(f"✓ Matched: '{video_title}' by {artist} | YouTube ID: {video_id}")

                # v4.0.0: Add matched video to video_ratings table
                try:
                    # Prepare full video data for insertion
                    video_data = prepare_video_upsert(video, ha_media, source='queue_search')
                    db.upsert_video(video_data)
                    logger.info(f"  → Added video {video_id} to video_ratings table")

                    # v4.0.33: Record play for newly matched videos (they were playing when search was queued)
                    # This fixes issue #68 - newly added videos showing play_count=0
                    db.record_play(video_id)
                    logger.debug(f"  → Recorded play for {video_id} (play_count incremented)")
                except Exception as e:
                    logger.error(f"  ✗ Failed to add video {video_id} to database: {e}")
                    db.mark_queue_item_failed(queue_id, f"Failed to add to database: {str(e)}", api_response_json)
                    return 'success'  # Continue processing other items

                # If there's a callback rating, enqueue it
                callback_rating = payload.get('callback_rating')
                if callback_rating:
                    db.enqueue_rating(video_id, callback_rating)
                    logger.info(f"  → Enqueued {callback_rating} rating for {video_id}")
                    logger.debug(f"Added rating to queue for {video_id}")

                db.mark_queue_item_completed(queue_id, api_response_json)
            else:
                db.mark_queue_item_failed(queue_id, "No matching video found", api_response_json)
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
        db.mark_queue_item_failed(queue_id, str(e))
        LoggingHelper.log_error_with_trace(f"Unexpected error processing {item_type}", e)
        return 'success'  # Continue processing other items


def main():
    """Main worker loop - simple and straightforward."""
    global running

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
        logger.debug(f"Queue worker PID file created: {pid_file}")

    except Exception as e:
        logger.error(f"Failed to create PID file: {e}")
        sys.exit(1)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Queue worker starting (1 item/min, ratings priority=1, searches priority=2)")

    # Initialize database
    db = get_database()

    # v4.0.30: Inject database into youtube_api for API call logging
    # This is critical - without it, queue worker API calls don't get logged!
    set_youtube_api_database(db)

    # v4.0.9: Reset any items stuck in 'processing' status (crash recovery)
    reset_count = db.reset_stale_processing_items()
    if reset_count > 0:
        logger.info(f"Crash recovery: Reset {reset_count} items from 'processing' to 'pending'")

    # v4.0.40: Delay loading YouTube API until first use to avoid authentication on startup
    # Only the main app should authenticate during startup checks
    yt_api = None

    while running:
        try:
            # v4.0.39: Check quota status FIRST - don't load YouTube API if quota exceeded
            if check_quota_recently_exceeded(db):
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

            # v4.0.40: Load YouTube API only when first needed (lazy initialization)
            # This prevents authentication log on startup - only main app authenticates
            if yt_api is None:
                try:
                    logger.debug("Loading YouTube API credentials for queue processing")
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
