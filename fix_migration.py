#!/usr/bin/env python3
"""
Emergency migration fix script for v4.0.47
Completes the video_ratings table migration if it was interrupted.
"""
import sqlite3
from pathlib import Path

def fix_migration():
    """Complete the interrupted migration."""
    # Try both possible database locations
    db_paths = [
        Path('/data/youtube_thumbs.db'),
        Path('/config/youtube_thumbs/youtube_thumbs.db')
    ]

    db_path = None
    for path in db_paths:
        if path.exists():
            db_path = path
            break

    if not db_path:
        print("❌ Database not found")
        return

    print(f"Found database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check what tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'video_ratings%'")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Tables found: {tables}")

    if 'video_ratings' in tables and 'video_ratings_new' in tables:
        print("\n⚠️  Both tables exist - migration was interrupted")

        # Check row counts
        cursor.execute("SELECT COUNT(*) FROM video_ratings")
        old_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM video_ratings_new")
        new_count = cursor.fetchone()[0]

        print(f"  video_ratings: {old_count} rows")
        print(f"  video_ratings_new: {new_count} rows")

        if new_count == old_count:
            print("\n✓ Data copied successfully, completing migration...")

            # Complete the migration
            cursor.execute("DROP TABLE video_ratings")
            cursor.execute("ALTER TABLE video_ratings_new RENAME TO video_ratings")

            # Recreate indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_video_id ON video_ratings(yt_video_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_title ON video_ratings(ha_title)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_channel_id ON video_ratings(yt_channel_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_yt_category_id ON video_ratings(yt_category_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_hash ON video_ratings(ha_content_hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_video_ratings_ha_content_id ON video_ratings(ha_content_id)")

            conn.commit()
            print("✓ Migration completed successfully!")
        else:
            print("\n❌ Data mismatch - manual intervention required")

    elif 'video_ratings' in tables and 'video_ratings_new' not in tables:
        print("\n✓ Migration already completed (or never started)")

        # Check if old columns still exist
        cursor.execute("PRAGMA table_info(video_ratings)")
        columns = {row[1] for row in cursor.fetchall()}

        deprecated = {'yt_match_pending', 'rating_queue_pending', 'pending_reason'}
        has_deprecated = any(col in columns for col in deprecated)

        if has_deprecated:
            print("⚠️  Deprecated columns still present - migration needs to run again")
        else:
            print("✓ Schema is clean")

    conn.close()

if __name__ == '__main__':
    fix_migration()
