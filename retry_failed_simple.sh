#!/bin/bash
# Simple script to retry failed queue items using sqlite3 directly
# Run this from the Home Assistant add-on console

DB_PATH="/config/youtube_thumbs/ratings.db"

echo "==================================================================="
echo "RETRY FAILED QUEUE ITEMS"
echo "==================================================================="

# Count failed items
FAILED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM queue WHERE status = 'failed';")

if [ "$FAILED_COUNT" -eq 0 ]; then
    echo "✓ No failed items to retry!"
    exit 0
fi

echo "Found $FAILED_COUNT failed queue items"
echo ""
echo "Sample of items to retry (first 10):"
sqlite3 "$DB_PATH" << 'EOF'
.headers on
.mode column
SELECT id, type, attempts, substr(last_error, 1, 60) as error
FROM queue
WHERE status = 'failed'
ORDER BY requested_at DESC
LIMIT 10;
EOF

echo ""
echo "This will reset ALL $FAILED_COUNT failed items back to 'pending' status."
echo "The queue worker will retry them within 60 seconds."
echo ""

# Perform the retry
echo "Resetting failed items to pending..."
RETRIED=$(sqlite3 "$DB_PATH" << 'EOF'
UPDATE queue
SET status = 'pending',
    last_error = NULL,
    last_attempt = NULL
WHERE status = 'failed';
SELECT changes();
EOF
)

echo "==================================================================="
echo "✓ Successfully retried $RETRIED queue items!"
echo "  Items have been reset to 'pending' status"
echo "  Queue worker will process them within 60 seconds"
echo "==================================================================="
