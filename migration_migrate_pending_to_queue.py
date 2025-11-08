#!/usr/bin/env python3
"""
Migration: Move rows with yt_match_pending=1 from video_ratings to queue.

These are songs that were detected but never matched to YouTube videos.
Instead of leaving them cluttering the video_ratings table, we should
queue them for proper YouTube search and matching.

Run this ONCE to clean up the video_ratings table.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_database
from logger import logger


def migrate_pending_to_queue():
    """Move all rows with yt_match_pending=1 from video_ratings to queue."""
    db = get_database()

    logger.info("=" * 80)
    logger.info("MIGRATION: Moving yt_match_pending=1 rows to queue")
    logger.info("=" * 80)

    # First, check if yt_match_pending column even exists
    with db._lock:
        cursor = db._conn.execute("PRAGMA table_info(video_ratings)")
        columns = {row[1] for row in cursor.fetchall()}

    if 'yt_match_pending' not in columns:
        logger.info("✓ Column 'yt_match_pending' doesn't exist. Migration not needed!")
        return

    # Count how many rows have yt_match_pending=1
    with db._lock:
        cursor = db._conn.execute("""
            SELECT COUNT(*) as count
            FROM video_ratings
            WHERE yt_match_pending = 1
        """)
        pending_count = cursor.fetchone()['count']

    if pending_count == 0:
        logger.info("✓ No rows with yt_match_pending=1. Migration already complete!")
        return

    logger.info(f"Found {pending_count} rows with yt_match_pending=1")

    # Show sample of what will be migrated
    logger.info("\nSample of rows to be migrated (first 10):")
    with db._lock:
        cursor = db._conn.execute("""
            SELECT id, ha_title, ha_artist, ha_duration, play_count, date_added
            FROM video_ratings
            WHERE yt_match_pending = 1
            ORDER BY date_added DESC
            LIMIT 10
        """)
        for row in cursor.fetchall():
            logger.info(f"  ID {row['id']}: '{row['ha_title']}' by {row['ha_artist'] or 'Unknown'} "
                       f"({row['ha_duration']}s) - Plays: {row['play_count']}")

    # Migrate to queue
    logger.info(f"\nMigrating {pending_count} rows to queue...")

    try:
        # Fetch all pending rows
        with db._lock:
            cursor = db._conn.execute("""
                SELECT
                    ha_title,
                    ha_artist,
                    ha_app_name,
                    ha_content_id,
                    ha_duration
                FROM video_ratings
                WHERE yt_match_pending = 1
            """)
            pending_rows = cursor.fetchall()

        # Add each to the queue
        queued_count = 0
        skipped_count = 0

        for row in pending_rows:
            # Skip if missing required fields
            if not row['ha_title'] or not row['ha_duration']:
                logger.debug(f"Skipping row without title/duration: {row['ha_title']}")
                skipped_count += 1
                continue

            # Create media dict for queue
            media = {
                'title': row['ha_title'],
                'artist': row['ha_artist'],
                'album': None,  # Not stored in old schema
                'content_id': row['ha_content_id'],
                'duration': row['ha_duration'],
                'app_name': row['ha_app_name'] or 'YouTube'
            }

            try:
                db.enqueue_search(media)
                queued_count += 1
                if queued_count % 10 == 0:
                    logger.info(f"  Queued {queued_count}/{pending_count}...")
            except Exception as e:
                logger.warning(f"Failed to enqueue '{row['ha_title']}': {e}")
                skipped_count += 1

        logger.info(f"✓ Queued {queued_count} items for YouTube search")
        if skipped_count > 0:
            logger.warning(f"⚠ Skipped {skipped_count} items (missing data or errors)")

        # Delete migrated rows from video_ratings
        logger.info(f"\nDeleting {pending_count} migrated rows from video_ratings...")

        with db._lock:
            cursor = db._conn.execute("""
                DELETE FROM video_ratings
                WHERE yt_match_pending = 1
            """)
            db._conn.commit()
            deleted = cursor.rowcount

        logger.info("=" * 80)
        logger.info(f"✓ Migration complete!")
        logger.info(f"  Queued for search: {queued_count} items")
        logger.info(f"  Deleted from video_ratings: {deleted} rows")
        logger.info(f"  Skipped: {skipped_count} items")
        logger.info("=" * 80)

        # Verify
        with db._lock:
            cursor = db._conn.execute("""
                SELECT COUNT(*) as count
                FROM video_ratings
                WHERE yt_match_pending = 1
            """)
            remaining = cursor.fetchone()['count']

        if remaining > 0:
            logger.warning(f"⚠ {remaining} rows still have yt_match_pending=1!")
        else:
            logger.info("✓ All yt_match_pending=1 rows have been migrated to queue!")

        # Show queue status
        with db._lock:
            cursor = db._conn.execute("""
                SELECT COUNT(*) as count
                FROM queue
                WHERE status = 'pending' AND type = 'search'
            """)
            queue_count = cursor.fetchone()['count']

        logger.info(f"✓ Queue now has {queue_count} pending search items")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == '__main__':
    try:
        migrate_pending_to_queue()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
