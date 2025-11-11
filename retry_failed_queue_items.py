#!/usr/bin/env python3
"""
Utility script to retry failed queue items.

This resets failed queue items back to 'pending' status so they can be retried.
Use this ONLY when you're confident the failures were temporary (e.g., quota issues).

For items that failed due to genuinely not finding matches, retrying will waste quota.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_database
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)


def retry_failed_items(error_filter=None, limit=None):
    """
    Reset failed queue items back to pending status.

    Args:
        error_filter: Only retry items with error messages containing this text
                     (e.g., "quota" to only retry quota-related failures)
        limit: Maximum number of items to retry (None = all matching items)
    """
    db = get_database()

    logger.info("=" * 80)
    logger.info("RETRY FAILED QUEUE ITEMS")
    logger.info("=" * 80)

    # Build query based on filters
    where_clause = "WHERE status = 'failed'"
    params = []

    if error_filter:
        where_clause += " AND last_error LIKE ?"
        params.append(f"%{error_filter}%")
        logger.info(f"Filter: Only items with errors containing '{error_filter}'")

    # Count how many will be retried
    with db._lock:
        count_query = f"SELECT COUNT(*) as count FROM queue {where_clause}"
        cursor = db._conn.execute(count_query, params)
        total_failed = cursor.fetchone()['count']

    if total_failed == 0:
        logger.info("✓ No failed items matching criteria. Nothing to retry!")
        return

    logger.info(f"Found {total_failed} failed items matching criteria")

    if limit:
        logger.info(f"Limiting retry to {limit} items")
        total_to_retry = min(total_failed, limit)
    else:
        total_to_retry = total_failed

    # Show sample of what will be retried
    logger.info("\nSample of items to retry (first 10):")
    with db._lock:
        sample_query = f"""
            SELECT id, type, last_error, requested_at, attempts
            FROM queue
            {where_clause}
            ORDER BY requested_at DESC
            LIMIT 10
        """
        cursor = db._conn.execute(sample_query, params)
        for row in cursor.fetchall():
            logger.info(f"  ID {row['id']}: {row['type']} | Attempts: {row['attempts']} | "
                       f"Error: {row['last_error'][:60]}...")

    # Ask for confirmation
    logger.info(f"\nAbout to retry {total_to_retry} failed queue items.")
    response = input("Continue? (yes/no): ").strip().lower()

    if response != 'yes':
        logger.info("Cancelled. No items were retried.")
        return

    # Reset items back to pending
    logger.info(f"\nResetting {total_to_retry} items to 'pending' status...")

    try:
        with db._lock:
            if limit:
                # Get IDs of items to retry (with limit)
                id_query = f"""
                    SELECT id FROM queue
                    {where_clause}
                    ORDER BY requested_at DESC
                    LIMIT {limit}
                """
                cursor = db._conn.execute(id_query, params)
                ids_to_retry = [row['id'] for row in cursor.fetchall()]

                # Reset those specific IDs
                placeholders = ','.join('?' * len(ids_to_retry))
                update_query = f"""
                    UPDATE queue
                    SET status = 'pending',
                        last_error = NULL,
                        last_attempt = NULL
                    WHERE id IN ({placeholders})
                """
                cursor = db._conn.execute(update_query, ids_to_retry)
            else:
                # Reset all matching items
                update_query = f"""
                    UPDATE queue
                    SET status = 'pending',
                        last_error = NULL,
                        last_attempt = NULL
                    {where_clause}
                """
                cursor = db._conn.execute(update_query, params)

            db._conn.commit()
            retried = cursor.rowcount

        logger.info("=" * 80)
        logger.info(f"✓ Successfully retried {retried} queue items!")
        logger.info(f"  Items have been reset to 'pending' status")
        logger.info(f"  Queue worker will process them within 60 seconds")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Failed to retry items: {e}")
        raise


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Retry failed queue items')
    parser.add_argument('--error-filter', type=str, help='Only retry items with errors containing this text (e.g., "quota")')
    parser.add_argument('--limit', type=int, help='Maximum number of items to retry')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt')

    args = parser.parse_args()

    # Override input() if --yes flag is provided
    if args.yes:
        import builtins
        builtins.input = lambda _: "yes"

    try:
        retry_failed_items(
            error_filter=args.error_filter,
            limit=args.limit
        )
    except Exception as e:
        logger.error(f"Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
