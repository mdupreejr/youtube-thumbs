-- Manual cleanup script
-- Run this with: sqlite3 /data/youtube_thumbs.db < manual_cleanup.sql

-- Step 1: Drop the empty video_ratings_new table (leftover from failed migration)
DROP TABLE IF EXISTS video_ratings_new;

-- Step 2: Drop obsolete columns from video_ratings table
ALTER TABLE video_ratings DROP COLUMN IF EXISTS yt_match_pending;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS yt_match_requested_at;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS yt_match_attempts;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS yt_match_last_attempt;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS yt_match_last_error;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS rating_queue_pending;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS rating_queue_requested_at;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS rating_queue_attempts;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS rating_queue_last_attempt;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS rating_queue_last_error;
ALTER TABLE video_ratings DROP COLUMN IF EXISTS pending_reason;

-- Done! Check the result with:
-- PRAGMA table_info(video_ratings);
