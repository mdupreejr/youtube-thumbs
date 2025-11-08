-- Cleanup incomplete migration
-- Just drop the empty video_ratings_new table
DROP TABLE IF EXISTS video_ratings_new;
