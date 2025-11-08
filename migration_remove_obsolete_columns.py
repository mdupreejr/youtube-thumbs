#!/usr/bin/env python3
"""
Migration: Remove obsolete columns from video_ratings table.

Removes all legacy queue-related columns that are no longer needed since v4.0:
- yt_match_pending, yt_match_requested_at, yt_match_attempts, yt_match_last_attempt, yt_match_last_error
- rating_queue_pending, rating_queue_requested_at, rating_queue_attempts, rating_queue_last_attempt, rating_queue_last_error
- pending_reason

These were part of the old queue system. Now everything is handled by the unified queue table.

Run this ONCE after upgrading to v4.0.73+.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_database
from logger import logger


def remove_obsolete_columns():
    """Remove obsolete columns from video_ratings table."""
    db = get_database()

    logger.info("=" * 80)
    logger.info("MIGRATION: Removing obsolete columns from video_ratings")
    logger.info("=" * 80)

    # Check current schema
    with db._lock:
        cursor = db._conn.execute("PRAGMA table_info(video_ratings)")
        columns = {row[1]: row for row in cursor.fetchall()}

    obsolete_cols = [
        'yt_match_pending', 'yt_match_requested_at', 'yt_match_attempts',
        'yt_match_last_attempt', 'yt_match_last_error',
        'rating_queue_pending', 'rating_queue_requested_at', 'rating_queue_attempts',
        'rating_queue_last_attempt', 'rating_queue_last_error', 'pending_reason'
    ]

    # Check which obsolete columns exist
    existing_obsolete = [col for col in obsolete_cols if col in columns]

    if not existing_obsolete:
        logger.info("✓ No obsolete columns found. Migration not needed!")
        return

    logger.info(f"Found {len(existing_obsolete)} obsolete columns to remove:")
    for col in existing_obsolete:
        logger.info(f"  - {col}")

    # Count rows to migrate
    with db._lock:
        cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings")
        row_count = cursor.fetchone()['count']

    logger.info(f"\nMigrating {row_count} rows to new schema...")

    try:
        with db._lock:
            # SQLite doesn't support DROP COLUMN in older versions
            # So we need to: CREATE new table, COPY data, DROP old, RENAME new

            logger.info("Step 1: Creating new table with clean schema...")
            db._conn.execute("""
                CREATE TABLE video_ratings_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    yt_video_id TEXT NOT NULL UNIQUE,
                    ha_content_id TEXT,
                    ha_title TEXT NOT NULL,
                    ha_artist TEXT,
                    ha_app_name TEXT,
                    yt_title TEXT NOT NULL,
                    yt_channel TEXT,
                    yt_channel_id TEXT,
                    yt_description TEXT,
                    yt_published_at TIMESTAMP,
                    yt_category_id INTEGER,
                    yt_live_broadcast TEXT,
                    yt_location TEXT,
                    yt_recording_date TIMESTAMP,
                    ha_duration INTEGER,
                    yt_duration INTEGER,
                    yt_url TEXT NOT NULL,
                    rating TEXT DEFAULT 'none',
                    ha_content_hash TEXT,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date_last_played TIMESTAMP,
                    play_count INTEGER DEFAULT 1,
                    rating_score INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'ha_live'
                )
            """)

            logger.info("Step 2: Copying data from old table to new table...")
            db._conn.execute("""
                INSERT INTO video_ratings_new (
                    id, yt_video_id, ha_content_id, ha_title, ha_artist, ha_app_name,
                    yt_title, yt_channel, yt_channel_id, yt_description,
                    yt_published_at, yt_category_id, yt_live_broadcast, yt_location, yt_recording_date,
                    ha_duration, yt_duration, yt_url, rating, ha_content_hash,
                    date_added, date_last_played, play_count, rating_score, source
                )
                SELECT
                    id, yt_video_id, ha_content_id, ha_title, ha_artist, ha_app_name,
                    yt_title, yt_channel, yt_channel_id, yt_description,
                    yt_published_at, yt_category_id, yt_live_broadcast, yt_location, yt_recording_date,
                    ha_duration, yt_duration, yt_url, rating, ha_content_hash,
                    date_added, date_last_played, play_count, rating_score, source
                FROM video_ratings
            """)

            # Verify row count
            cursor = db._conn.execute("SELECT COUNT(*) as count FROM video_ratings_new")
            new_count = cursor.fetchone()['count']

            if new_count != row_count:
                raise Exception(f"Row count mismatch! Old: {row_count}, New: {new_count}")

            logger.info(f"✓ Verified: {new_count} rows copied successfully")

            logger.info("Step 3: Dropping old table...")
            db._conn.execute("DROP TABLE video_ratings")

            logger.info("Step 4: Renaming new table to video_ratings...")
            db._conn.execute("ALTER TABLE video_ratings_new RENAME TO video_ratings")

            logger.info("Step 5: Recreating indexes...")
            db._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_video_id ON video_ratings(yt_video_id)")
            db._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title)")
            db._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_channel_id ON video_ratings(yt_channel_id)")
            db._conn.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_category_id ON video_ratings(yt_category_id)")

            db._conn.commit()

        logger.info("=" * 80)
        logger.info(f"✓ Migration complete!")
        logger.info(f"  Removed {len(existing_obsolete)} obsolete columns")
        logger.info(f"  Migrated {row_count} rows successfully")
        logger.info("=" * 80)

        # Verify final schema
        with db._lock:
            cursor = db._conn.execute("PRAGMA table_info(video_ratings)")
            final_columns = {row[1] for row in cursor.fetchall()}

        remaining_obsolete = [col for col in obsolete_cols if col in final_columns]
        if remaining_obsolete:
            logger.warning(f"⚠ {len(remaining_obsolete)} obsolete columns still exist: {remaining_obsolete}")
        else:
            logger.info("✓ All obsolete columns have been removed!")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        logger.error("Attempting rollback...")
        try:
            with db._lock:
                db._conn.execute("DROP TABLE IF EXISTS video_ratings_new")
                db._conn.commit()
            logger.info("Rollback successful - database unchanged")
        except Exception as rollback_error:
            logger.error(f"Rollback failed: {rollback_error}")
            logger.error("DATABASE MAY BE IN INCONSISTENT STATE - RESTORE FROM BACKUP!")
        raise


if __name__ == '__main__':
    try:
        remove_obsolete_columns()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
