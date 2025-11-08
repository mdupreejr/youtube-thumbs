#!/bin/bash
# Script to identify and remove malformed rows from video_ratings table
# These are remnants from the old pending match system (pre-v4.0.0)

DB_PATH="/config/youtube_thumbs/ratings.db"

echo "=== Checking for malformed rows in video_ratings table ==="
echo ""

# Check for malformed rows
echo "Malformed row counts:"
sqlite3 "$DB_PATH" << 'EOF'
SELECT
    'Total malformed: ' || COUNT(*) as stat
FROM video_ratings
WHERE yt_video_id IS NULL
   OR yt_video_id = ''
   OR yt_video_id LIKE 'pending:%'
   OR yt_title IS NULL
   OR yt_title = '';

SELECT
    'NULL yt_video_id: ' || COUNT(*)
FROM video_ratings WHERE yt_video_id IS NULL;

SELECT
    'Empty yt_video_id: ' || COUNT(*)
FROM video_ratings WHERE yt_video_id = '';

SELECT
    'Pending prefix: ' || COUNT(*)
FROM video_ratings WHERE yt_video_id LIKE 'pending:%';

SELECT
    'Missing yt_title: ' || COUNT(*)
FROM video_ratings WHERE yt_title IS NULL OR yt_title = '';
EOF

echo ""
echo "=== Sample of malformed rows (first 10) ==="
sqlite3 "$DB_PATH" << 'EOF'
.headers on
.mode column
SELECT
    id, yt_video_id, ha_title, yt_title, rating, play_count, source
FROM video_ratings
WHERE yt_video_id IS NULL
   OR yt_video_id = ''
   OR yt_video_id LIKE 'pending:%'
   OR yt_title IS NULL
   OR yt_title = ''
LIMIT 10;
EOF

echo ""
echo "=== To delete malformed rows, run: ==="
echo "sqlite3 \"$DB_PATH\" \"DELETE FROM video_ratings WHERE yt_video_id IS NULL OR yt_video_id = '' OR yt_video_id LIKE 'pending:%' OR yt_title IS NULL OR yt_title = '';\""
echo ""
echo "=== To backup first, run: ==="
echo "cp \"$DB_PATH\" \"$DB_PATH.backup-\$(date +%Y%m%d-%H%M%S)\""
