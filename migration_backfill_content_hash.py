#!/usr/bin/env python3
"""
CRITICAL MIGRATION: Backfill ha_content_hash for existing videos.

This fixes a critical bug where ha_content_hash was NULL for all videos,
causing content hash cache lookups to never work. This meant songs played
many times were never found in the cache and had to be searched again.

Run this ONCE after upgrading to v4.0.65.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_database
from helpers.video_helpers import get_content_hash
from logger import logger


def backfill_content_hashes():
    """Backfill ha_content_hash for all videos that have NULL ha_content_hash."""
    db = get_database()

    logger.info("=" * 80)
    logger.info("MIGRATION: Backfilling ha_content_hash for existing videos")
    logger.info("=" * 80)

    # Count how many need fixing
    with db._lock:
        cursor = db._conn.execute("""
            SELECT COUNT(*) as count
            FROM video_ratings
            WHERE ha_content_hash IS NULL
        """)
        total_null = cursor.fetchone()['count']

    if total_null == 0:
        logger.info("✓ No videos need ha_content_hash backfilled. Migration already complete!")
        return

    logger.info(f"Found {total_null} videos with NULL ha_content_hash")
    logger.info("Backfilling content hashes...")

    # Get all videos that need fixing
    with db._lock:
        cursor = db._conn.execute("""
            SELECT id, ha_title, ha_duration, ha_artist, yt_video_id
            FROM video_ratings
            WHERE ha_content_hash IS NULL
            ORDER BY id
        """)
        videos_to_fix = [dict(row) for row in cursor.fetchall()]

    updated_count = 0
    error_count = 0

    # Update each video
    for video in videos_to_fix:
        try:
            # Compute content hash
            content_hash = get_content_hash(
                video['ha_title'],
                video['ha_duration'],
                video['ha_artist']
            )

            # Update the row
            with db._lock:
                db._conn.execute("""
                    UPDATE video_ratings
                    SET ha_content_hash = ?
                    WHERE id = ?
                """, (content_hash, video['id']))
                db._conn.commit()

            updated_count += 1

            if updated_count % 100 == 0:
                logger.info(f"  Progress: {updated_count}/{total_null} videos updated...")

        except Exception as e:
            error_count += 1
            logger.error(f"  Failed to update video {video['yt_video_id']}: {e}")

    logger.info("=" * 80)
    logger.info(f"✓ Migration complete!")
    logger.info(f"  Updated: {updated_count} videos")
    if error_count > 0:
        logger.warning(f"  Errors: {error_count} videos failed")
    logger.info("=" * 80)

    # Verify
    with db._lock:
        cursor = db._conn.execute("""
            SELECT COUNT(*) as count
            FROM video_ratings
            WHERE ha_content_hash IS NULL
        """)
        remaining_null = cursor.fetchone()['count']

    if remaining_null > 0:
        logger.warning(f"⚠ {remaining_null} videos still have NULL ha_content_hash!")
    else:
        logger.info("✓ All videos now have ha_content_hash set!")


if __name__ == '__main__':
    try:
        backfill_content_hashes()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
