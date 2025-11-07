#!/usr/bin/env python3
"""
Simple background queue worker - NO THREADS, NO COMPLEXITY.

This script runs as a separate process and processes queue items one at a time.
Runs independently of the Flask/Gunicorn web server.
"""
import time
import sys
import signal
from logger import logger
from database import get_database
from youtube_api import get_youtube_api
from quota_error import QuotaExceededError

# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logger.info(f"Queue worker received signal {signum}, shutting down...")
    running = False


def process_one_rating(db, yt_api):
    """
    Process ONE rating from the queue.

    Returns:
        'success': Processed a rating
        'empty': No ratings in queue
        'quota': Quota exceeded
    """
    # Get one pending rating
    pending = db.list_pending_ratings(limit=1)
    if not pending:
        return 'empty'

    job = pending[0]
    video_id = job['yt_video_id']
    rating = job['rating']

    logger.info(f"Processing rating: {video_id} as {rating}")

    try:
        success = yt_api.set_video_rating(video_id, rating)
        if success:
            db.record_rating(video_id, rating)
            db.mark_pending_rating(video_id, True)
            logger.info(f"Successfully rated {video_id} as {rating}")
        else:
            db.mark_pending_rating(video_id, False, "YouTube API returned False")
            logger.warning(f"YouTube API rejected rating for {video_id}")
        return 'success'

    except QuotaExceededError:
        # DON'T increment attempts for quota errors - it's a global condition, not this rating's fault
        logger.warning(f"YouTube quota exceeded while processing {video_id} - will retry when quota resets")
        logger.warning("Worker sleeping for 1 hour before checking quota again")
        return 'quota'

    except Exception as e:
        db.mark_pending_rating(video_id, False, str(e))
        logger.error(f"Failed to rate {video_id}: {e}")
        return 'success'  # Continue processing other items


def process_one_search(db, yt_api):
    """
    Process ONE search from the queue.

    Returns:
        'success': Processed a search
        'empty': No searches in queue
        'quota': Quota exceeded
    """
    # Atomically claim one search
    job = db.claim_pending_search()
    if not job:
        return 'empty'

    search_id = job['id']
    title = job['ha_title']

    logger.info(f"Processing search: {title}")

    try:
        # Build media dict
        ha_media = {
            'title': job['ha_title'],
            'artist': job['ha_artist'],
            'album': job['ha_album'],
            'content_id': job['ha_content_id'],
            'duration': job['ha_duration'],
            'app_name': job['ha_app_name']
        }

        # Search using the wrapper (includes caching)
        from helpers.search_helpers import search_and_match_video
        video = search_and_match_video(ha_media, yt_api, db)

        if video and video.get('yt_video_id'):
            video_id = video['yt_video_id']
            logger.info(f"Search found video {video_id} for '{title}'")

            # Mark search complete and enqueue callback rating if present
            callback_rating = job.get('callback_rating')
            db.mark_search_complete_with_callback(search_id, video_id, callback_rating)

            if callback_rating:
                logger.info(f"Enqueued {callback_rating} rating for {video_id}")
        else:
            db.mark_search_failed(search_id, "No matching video found")
            logger.warning(f"No video found for '{title}'")

        return 'success'

    except QuotaExceededError:
        db.mark_search_failed(search_id, "Quota exceeded - will retry")
        logger.warning("YouTube quota exceeded - worker sleeping for 1 hour")
        return 'quota'

    except Exception as e:
        db.mark_search_failed(search_id, str(e))
        logger.error(f"Search failed for '{title}': {e}")
        return 'success'  # Continue processing other items


def main():
    """Main worker loop - simple and straightforward."""
    global running

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info("Queue worker starting (SIMPLE MODE: 1 item per minute)")
    logger.info("This is a standalone process, not a thread")

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

            # Priority 1: Process ratings first (lightweight API calls)
            result = process_one_rating(db, yt_api)

            if result == 'quota':
                # Sleep 1 hour when quota exceeded
                logger.info("Sleeping for 1 hour due to quota limit")
                time.sleep(3600)
                continue
            elif result == 'success':
                # Processed a rating, sleep 60 seconds
                logger.debug("Rating processed, sleeping 60 seconds")
                time.sleep(60)
                continue

            # Priority 2: Process searches (only if no ratings pending)
            result = process_one_search(db, yt_api)

            if result == 'quota':
                # Sleep 1 hour when quota exceeded
                logger.info("Sleeping for 1 hour due to quota limit")
                time.sleep(3600)
                continue
            elif result == 'success':
                # Processed a search, sleep 60 seconds
                logger.debug("Search processed, sleeping 60 seconds")
                time.sleep(60)
                continue

            # Nothing in queue, sleep 60 seconds
            logger.debug("Queue empty, sleeping 60 seconds")
            time.sleep(60)

        except Exception as e:
            logger.error(f"Queue worker error: {e}")
            time.sleep(60)

    logger.info("Queue worker stopped")


if __name__ == '__main__':
    main()
