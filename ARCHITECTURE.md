# YouTube Thumbs - Architecture Documentation

Technical details about the matching system, database schema, and internal workings.

## Table of Contents

- [Video Matching System](#video-matching-system)
- [Database Schema](#database-schema)
- [Content Hash Algorithm](#content-hash-algorithm)
- [Video States](#video-states)
- [Pending Video Retry](#pending-video-retry)

## Video Matching System

The addon uses a multi-stage matching system to find YouTube videos for songs playing on your Apple TV.

### 1. Cache Lookup (Instant, No API Calls)

When a new song is detected, the addon first checks the local database cache:

1. **Content Hash Lookup**: Calculates SHA1 hash of `title + duration + artist` and searches for exact match
   - Most flexible - handles minor formatting differences
   - Example: "Song Name" vs "Song Name " (trailing space) both match

2. **Title + Duration Lookup**: Searches for exact `ha_title` and `ha_duration` match
   - Fallback if content hash doesn't match
   - YouTube duration = HA duration + 1 second (YouTube rounds up)

**Cache Hit**: Returns existing video immediately, increments play count, no YouTube API call needed.

### 2. YouTube Search (API Call Required)

If no cache match found:

1. **Clean title**: Removes special characters, normalizes spacing
2. **Search YouTube**: Query YouTube Data API with cleaned title
3. **Filter by duration**: Only consider results where YouTube duration matches HA duration ± 1 second
4. **Select best match**: First result with exact duration match
5. **Store in database**: Save video metadata, mark as matched (`pending_match = 0`)

**Search Hit**: Video matched and cached for future plays.

### 3. Not Found Cache (Prevents Repeated Searches)

If YouTube search returns no results:

1. **Record in not_found_searches table**: Title + artist + duration + timestamp
2. **Cache duration**: 7 days (prevents searching again for same song)
3. **Future lookups**: Skip YouTube search if in not_found cache

**Not Found Hit**: Logged but no database entry created.

### 4. Quota Exceeded Handling

If YouTube quota is exhausted during search:

1. **Store as pending**: Creates database entry with `pending_match = 1`
2. **Use placeholder ID**: `ha_content_id = ha_hash:abc123` (content hash)
3. **Set pending_reason**: `quota_exceeded`
4. **Skip YouTube calls**: All future searches delayed until quota recovers
5. **Automatic retry**: After quota recovery, QuotaProber retries all pending videos

## Database Schema

### video_ratings (Main Table)

Primary table storing all video metadata, play history, ratings, and pending states.

**YouTube Metadata Fields** (yt_* prefix):
- `yt_video_id` (TEXT, PRIMARY KEY) - YouTube video ID (e.g., "dQw4w9WgXcQ")
  - NULL for pending videos awaiting YouTube match
  - Populated after successful match
- `yt_title` (TEXT) - Official YouTube video title
- `yt_channel` (TEXT) - YouTube channel name
- `yt_channel_id` (TEXT) - YouTube channel ID
- `yt_description` (TEXT) - Video description
- `yt_published_at` (TIMESTAMP) - YouTube upload date
- `yt_category_id` (INTEGER) - YouTube category (10=Music, etc.)
- `yt_live_broadcast` (TEXT) - Live stream status (none/upcoming/live/completed)
- `yt_location` (TEXT) - Geographic location if available
- `yt_recording_date` (TIMESTAMP) - Original recording date if available
- `yt_duration` (INTEGER) - YouTube video duration in seconds
- `yt_url` (TEXT) - Full YouTube URL

**Home Assistant Metadata Fields** (ha_* prefix):
- `ha_content_id` (TEXT) - Placeholder ID for pending videos
  - Format: `ha_hash:abc123` (SHA1 of title+duration+artist)
  - Used when `yt_video_id` is NULL (quota blocked)
  - Replaced with real `yt_video_id` after successful match
- `ha_title` (TEXT, INDEXED) - Song title from HA media player
- `ha_artist` (TEXT) - Artist/channel from HA media player
- `ha_app_name` (TEXT) - Source app (e.g., "YouTube Music")
- `ha_duration` (INTEGER, INDEXED) - Song duration in seconds from HA
- `ha_content_hash` (TEXT, INDEXED) - SHA1 hash for duplicate detection
  - Format: SHA1(lowercase(title) + duration + lowercase(artist))
  - Enables fuzzy matching across formatting differences

**Playback & Rating Fields**:
- `rating` (TEXT) - User rating: 'like', 'dislike', or 'none'
- `rating_score` (INTEGER) - Net rating score (likes - dislikes)
- `play_count` (INTEGER) - Number of times played
- `date_added` (TIMESTAMP) - When video was first added to database
- `date_last_played` (TIMESTAMP, INDEXED) - Most recent play timestamp

**Pending Video Fields**:
- `pending_match` (INTEGER) - Boolean flag (0=matched, 1=pending YouTube match)
  - Set to 1 when quota exhausted during search
  - Set to 0 after successful YouTube match
- `pending_reason` (TEXT) - Why video is pending
  - `quota_exceeded` - Quota was exhausted, retry after recovery
  - `not_found` - No YouTube match exists (marked by retry mechanism)
  - NULL - Not pending (successfully matched)
- `source` (TEXT) - How video was added
  - `ha_live` - Playing on Home Assistant media player
  - `import_youtube` - Imported from YouTube export
  - `manual` - Manually added

**Pending Rating Queue Fields**:
When rating fails due to quota/network issues, queued for retry:
- `yt_rating_pending` (TEXT) - Pending rating action: 'like', 'dislike', or NULL
- `yt_rating_requested_at` (TIMESTAMP) - When rating was first requested
- `yt_rating_attempts` (INTEGER) - Number of retry attempts
- `yt_rating_last_attempt` (TIMESTAMP) - Last retry attempt timestamp
- `yt_rating_last_error` (TEXT) - Last error message

**Example Records**:

```sql
-- Fully matched video (normal case)
yt_video_id: "dQw4w9WgXcQ"
ha_content_id: NULL
ha_title: "Never Gonna Give You Up"
yt_title: "Rick Astley - Never Gonna Give You Up (Official Video)"
pending_match: 0
pending_reason: NULL
rating: "like"
play_count: 5

-- Pending video (quota exhausted)
yt_video_id: NULL
ha_content_id: "ha_hash:a1b2c3d4e5f6"
ha_title: "Some New Song"
yt_title: NULL
pending_match: 1
pending_reason: "quota_exceeded"
rating: "none"
play_count: 1

-- Pending video marked as not found
yt_video_id: NULL
ha_content_id: "ha_hash:x9y8z7w6v5u4"
ha_title: "Obscure Local Recording"
yt_title: NULL
pending_match: 1
pending_reason: "not_found"
```

### not_found_searches (Search Cache)

Prevents repeatedly searching YouTube for songs that don't exist.

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment ID
- `title` (TEXT, INDEXED) - Song title that wasn't found
- `artist` (TEXT) - Artist name (can be NULL)
- `duration` (INTEGER) - Duration in seconds (can be NULL)
- `search_query` (TEXT) - Actual query sent to YouTube
- `content_hash` (TEXT, INDEXED) - SHA1 hash (title+duration+artist)
- `timestamp` (TIMESTAMP, INDEXED) - When search failed
- `expires_at` (TIMESTAMP, INDEXED) - When cache entry expires (timestamp + 7 days)

**Behavior**:
- Before searching YouTube, checks if title+duration+artist in this table
- If found and not expired, skips YouTube search (saves quota)
- Expired entries cleaned up automatically on addon startup
- Default expiration: 7 days

### import_history (Deduplication)

Tracks YouTube export imports to prevent duplicate entries.

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment ID
- `entry_id` (TEXT, UNIQUE) - Hash of import entry (timestamp + video_id + action)
- `source` (TEXT) - Import source ('youtube_export', 'manual', etc.)
- `yt_video_id` (TEXT) - YouTube video ID that was imported
- `action` (TEXT) - What was imported ('watch', 'like', 'dislike')
- `imported_at` (TIMESTAMP) - When import occurred

**Behavior**:
- Before importing a YouTube export entry, checks if `entry_id` already exists
- Prevents duplicate play counts and ratings from re-importing same file
- Used by import_youtube_export.py script

## Content Hash Algorithm

The content hash enables fuzzy matching despite formatting differences:

```python
def get_content_hash(title, duration, artist=None):
    # Normalize inputs
    title_norm = (title or "").strip().lower()
    artist_norm = (artist or "").strip().lower()
    duration_str = str(duration or 0)

    # Combine and hash
    combined = f"{title_norm}:{duration_str}:{artist_norm}"
    return hashlib.sha1(combined.encode('utf-8')).hexdigest()
```

**Why it works**:
- Lowercases everything (handles "Song Name" vs "song name")
- Strips whitespace (handles "Song  Name" vs "Song Name")
- Includes duration (prevents matching different versions)
- Optional artist (handles missing artist metadata)

**Example matches** (same hash):
- "Never Gonna Give You Up" / "never gonna give you up"
- "Song Name  " / "Song Name" (trailing space)
- "Title - Artist" / "Title - artist" (case difference)

## Video States

A video in the database can be in one of these states:

1. **✓ Matched** (`pending_match = 0`, `yt_video_id` populated)
   - Successfully found on YouTube
   - All YouTube metadata populated
   - Can be rated, played, tracked
   - Shows in all statistics

2. **⏳ Pending - Quota Exceeded** (`pending_match = 1`, `pending_reason = 'quota_exceeded'`)
   - Quota was exhausted when attempting to match
   - Only Home Assistant data available (no YouTube metadata)
   - Will be retried automatically after quota recovery
   - Shows in startup check as "pending (quota_exceeded)"

3. **✗ Pending - Not Found** (`pending_match = 1`, `pending_reason = 'not_found'`)
   - Searched YouTube but no match found
   - Marked by retry mechanism after failed search
   - Won't be retried again (no YouTube video exists)
   - Also added to `not_found_searches` table

4. **Not in Database** (no record)
   - In `not_found_searches` table only
   - YouTube search was attempted but failed
   - No database entry created to save space
   - Prevents future searches for 7 days

## Pending Video Retry

For complete documentation, see [RETRY_SYSTEM.md](RETRY_SYSTEM.md).

### Manual Retry

1. **Stats Page Button**: Click "🔄 Retry 1 Video" on stats page
2. **Rate Limiting**: 30-second cooldown between clicks
3. **Processing**: Processes 1 pending video per click
4. **Results**: Shows detailed statistics for 5 seconds

### Automatic Retry

1. **Quota Exhaustion**: New song plays, quota exceeded
   - Create video_ratings entry with `pending_match = 1`
   - Set `ha_content_id = ha_hash:abc123`
   - Set `pending_reason = 'quota_exceeded'`
   - Set `yt_video_id = NULL`

2. **Quota Recovery Detection**: QuotaProber checks every 5 minutes
   - Probes YouTube API with test search
   - If successful, clears quota guard

3. **Automatic Retry**: QuotaProber calls `_retry_pending_videos()`
   - Queries: `SELECT * FROM video_ratings WHERE pending_match = 1 AND pending_reason = 'quota_exceeded' LIMIT 1`
   - Processes 1 video per recovery cycle
   - For each pending video:
     - Search YouTube with ha_title + ha_duration + ha_artist
     - **If found**: Update with YouTube data, set `pending_match = 0`, populate `yt_video_id`
     - **If not found**: Set `pending_reason = 'not_found'`, add to `not_found_searches`

**Configuration**:
- `pending_video_retry_enabled` (default: true) - Enable/disable automatic retry
- `pending_video_retry_batch_size` (default: 1) - Max videos per retry to prevent re-exhausting quota

**Monitoring**:
- View activity in Logs → Quota Prober tab
- Event categories: probe, retry, success, error, recovery
- Summary statistics: probes, recoveries, retries, resolved
