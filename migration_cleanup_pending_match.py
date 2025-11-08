#!/usr/bin/env python3
"""
Migration: Remove rows with pending_match=1 from video_ratings table.

These are remnants from the pre-v4.0.0 pending match system.
The queue system (v4.0+) handles unmatched videos differently, so these rows are obsolete.

Run this ONCE after upgrading to v4.0.67+.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_database
from logger import logger


def cleanup_pending_match_rows():
    """Remove all rows with pending_match=1 from video_ratings table."""
    db = get_database()

    logger.info("=" * 80)
    logger.info("MIGRATION: Cleaning up pending_match=1 rows from video_ratings")
    logger.info("=" * 80)

    # First, check if pending_match column even exists
    with db._lock:
        cursor = db._conn.execute("PRAGMA table_info(video_ratings)")
        columns = {row[1] for row in cursor.fetchall()}

    if 'pending_match' not in columns:
        logger.info("✓ Column 'pending_match' doesn't exist. Migration not needed!")
        return

    # Count how many rows have pending_match=1
    with db._lock:
        cursor = db._conn.execute("""
            SELECT COUNT(*) as count
            FROM video_ratings
            WHERE pending_match = 1
        """)
        pending_count = cursor.fetchone()['count']

    if pending_count == 0:
        logger.info("✓ No rows with pending_match=1. Migration already complete!")
        return

    logger.info(f"Found {pending_count} rows with pending_match=1")

    # Show sample of what will be deleted
    logger.info("\nSample of rows to be deleted (first 10):")
    with db._lock:
        cursor = db._conn.execute("""
            SELECT id, yt_video_id, ha_title, ha_artist, rating, play_count, date_added
            FROM video_ratings
            WHERE pending_match = 1
            ORDER BY date_added DESC
            LIMIT 10
        """)
        for row in cursor.fetchall():
            logger.info(f"  ID {row['id']}: '{row['ha_title']}' by {row['ha_artist']} - "
                       f"Rating: {row['rating']}, Plays: {row['play_count']}, "
                       f"YT ID: {row['yt_video_id'] or 'NULL'}")

    # Delete all pending_match=1 rows
    logger.info(f"\nDeleting {pending_count} rows...")

    try:
        with db._lock:
            cursor = db._conn.execute("""
                DELETE FROM video_ratings
                WHERE pending_match = 1
            """)
            db._conn.commit()
            deleted = cursor.rowcount

        logger.info("=" * 80)
        logger.info(f"✓ Migration complete!")
        logger.info(f"  Deleted: {deleted} rows with pending_match=1")
        logger.info("=" * 80)

        # Verify
        with db._lock:
            cursor = db._conn.execute("""
                SELECT COUNT(*) as count
                FROM video_ratings
                WHERE pending_match = 1
            """)
            remaining = cursor.fetchone()['count']

        if remaining > 0:
            logger.warning(f"⚠ {remaining} rows still have pending_match=1!")
        else:
            logger.info("✓ All pending_match=1 rows have been removed!")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == '__main__':
    try:
        cleanup_pending_match_rows()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
