#!/usr/bin/env python3
"""
Migration: Add api_response_data column to queue table.

This column stores YouTube API response data for debugging failed searches.
Run this ONCE after upgrading to v4.0.64+.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_database
from logger import logger


def add_api_response_column():
    """Add api_response_data column to queue table if it doesn't exist."""
    db = get_database()

    logger.info("=" * 80)
    logger.info("MIGRATION: Adding api_response_data column to queue table")
    logger.info("=" * 80)

    # Check if column already exists
    with db._lock:
        cursor = db._conn.execute("PRAGMA table_info(queue)")
        columns = {row[1] for row in cursor.fetchall()}

    if 'api_response_data' in columns:
        logger.info("✓ Column api_response_data already exists. Migration already complete!")
        return

    logger.info("Adding api_response_data column to queue table...")

    try:
        with db._lock:
            db._conn.execute("""
                ALTER TABLE queue
                ADD COLUMN api_response_data TEXT
            """)
            db._conn.commit()

        logger.info("=" * 80)
        logger.info("✓ Migration complete! Column api_response_data added to queue table.")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == '__main__':
    try:
        add_api_response_column()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
