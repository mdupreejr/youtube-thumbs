# YouTube Thumbs - Architecture Documentation

Technical details about the matching system, queue architecture, database schema, and internal workings.

## Table of Contents

- [Video Matching System](#video-matching-system)
- [Queue System](#queue-system)
- [Database Schema](#database-schema)
- [Content Hash Algorithm](#content-hash-algorithm)
- [Quota Management](#quota-management)

## Video Matching System

The addon uses a multi-stage matching system to find YouTube videos for songs playing on your Apple TV.

### 1. Cache Lookup (Instant, No API Calls)

When a new song is detected, the addon first checks the local database cache:

1. **Content Hash Lookup**: Calculates SHA1 hash of `title + duration + artist` and searches for exact match
   - Most flexible - handles minor formatting differences
   - Example: "Song Name" vs "Song Name " (trailing space) both match

2. **Title + Duration Lookup**: Searches for exact `ha_title` and `ha_duration` match
   - Fallback if content hash doesn't match
   - YouTube duration = HA duration ± 1 second tolerance

**Cache Hit**: Returns existing video immediately, increments play count, no YouTube API call needed.

### 2. YouTube Search (Queued for Processing)

If no cache match found, the search is **queued** for background processing:

1. **Queue search operation** with priority=2
2. **Background worker processes**: Cleans title, searches YouTube API, filters by duration
3. **Best match selected**: Highest quality title match with correct duration
4. **Stored in database**: Saved to video_ratings table for future cache hits

**Search Success**: Video matched and cached. Future plays use cache (no API calls).

## Queue System

As of v4.0.0, all YouTube API operations use a unified queue system for rate limiting, error handling, and monitoring.

### Queue Architecture

All YouTube API requests (searches and ratings) are processed through a single queue:

- **Unified queue table**: All operations stored in one `queue` table
- **Single background worker**: `queue_worker.py` process handles all API requests sequentially
- **1-minute rate limiting**: Mandatory 60-second delay between all API requests
- **Quota protection**: Auto-pauses until midnight Pacific when quota exceeded
- **Priority system**: Ratings (priority=1) processed before searches (priority=2)
- **Crash recovery**: Stuck 'processing' items reset to 'pending' on startup

### Queue States

Each queue item progresses through these states:

- `pending` → Waiting to be processed
- `processing` → Currently being handled by the worker
- `completed` → Successfully processed
- `failed` → Processing failed (includes error message and retry count)

### Web UI Queue Monitor

The Queue tab (`/logs/pending-ratings`) provides comprehensive monitoring with 4 sub-tabs:

1. **Pending**: Shows all queue items waiting to be processed
2. **History**: Last 200 completed and failed operations with timestamps
3. **Errors**: Failed operations with detailed error messages
4. **Statistics**: Queue performance metrics, success rates, processing stats

**Features**: Click any queue item for detailed modal view showing full request payloads, API responses, timestamps, and error messages.

## Database Schema

### video_ratings (Main Table)

**v4.0.0 Change**: Only stores **matched videos** with valid `yt_video_id`. Unmatched videos are tracked in the queue table until successfully matched.

**YouTube Metadata** (yt_* prefix):
- `yt_video_id` (TEXT, PRIMARY KEY) - YouTube video ID (e.g., "dQw4w9WgXcQ")
- `yt_title` (TEXT) - Official YouTube video title
- `yt_channel` (TEXT) - YouTube channel name
- `yt_channel_id` (TEXT) - YouTube channel ID
- `yt_duration` (INTEGER) - Video duration in seconds
- `yt_url` (TEXT) - Full YouTube URL
- `yt_published_at` (TIMESTAMP) - YouTube upload date
- `yt_category_id` (INTEGER) - YouTube category (10=Music, etc.)
- `yt_description`, `yt_live_broadcast`, `yt_location`, `yt_recording_date` - Additional metadata

**Home Assistant Metadata** (ha_* prefix):
- `ha_content_id` (TEXT) - Content ID from Home Assistant media player
- `ha_title` (TEXT, INDEXED) - Song title from HA
- `ha_artist` (TEXT) - Artist/channel from HA
- `ha_app_name` (TEXT) - Source app (e.g., "YouTube Music")
- `ha_duration` (INTEGER, INDEXED) - Song duration in seconds from HA
- `ha_content_hash` (TEXT, INDEXED) - SHA1 hash for duplicate detection (see algorithm below)

**Playback & Rating**:
- `rating` (TEXT) - User rating: 'like', 'dislike', or 'none'
- `rating_score` (INTEGER) - Net rating score (cumulative)
- `play_count` (INTEGER) - Number of times played
- `source` (TEXT) - How video was added: 'ha_live', 'queue_search', etc.
- `date_added` (TIMESTAMP) - When video was first added
- `date_last_played` (TIMESTAMP, INDEXED) - Most recent play

### queue (Unified Queue System)

Centralized queue for all YouTube API operations (searches and ratings).

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment queue item ID
- `type` (TEXT, INDEXED) - 'search' or 'rating'
- `priority` (INTEGER, INDEXED) - 1=ratings (first), 2=searches
- `status` (TEXT, INDEXED) - 'pending', 'processing', 'completed', 'failed'
- `payload` (TEXT) - JSON-encoded operation data (video ID, search terms, etc.)
- `requested_at` (TIMESTAMP, INDEXED) - When item was queued
- `attempts` (INTEGER) - Number of processing attempts
- `last_attempt` (TIMESTAMP) - Most recent processing attempt
- `last_error` (TEXT) - Error message if processing failed
- `completed_at` (TIMESTAMP) - When successfully processed

**Behavior**: All YouTube API requests flow through this queue. Single worker processes items sequentially with 1-minute delays. Failed items retain error message and attempt count for debugging.

### api_call_log (Detailed API Logging)

Logs every YouTube API call for debugging and analysis.

**Fields**:
- `id` (INTEGER, PRIMARY KEY)
- `timestamp` (TIMESTAMP, INDEXED) - When API call was made
- `api_method` (TEXT, INDEXED) - 'search', 'videos.list', 'videos.rate', etc.
- `operation_type` (TEXT) - High-level operation (e.g., 'search_video', 'get_rating')
- `query_params` (TEXT) - Query parameters sent to API
- `quota_cost` (INTEGER) - Quota units consumed
- `success` (BOOLEAN, INDEXED) - Whether call succeeded
- `error_message` (TEXT) - Error message if failed
- `results_count` (INTEGER) - Number of results returned
- `context` (TEXT) - Additional context (e.g., video title)

**Access**: View via `/logs/api-calls` web interface

### api_usage (Hourly Quota Tracking)

Tracks YouTube API usage by hour for quota management.

**Fields**:
- `date` (TEXT, PRIMARY KEY) - YYYY-MM-DD format
- `hour_00` through `hour_23` (INTEGER) - API quota units used per hour

**Behavior**: Records every YouTube API call. Enables quota usage analytics and hourly usage charts.

### search_results_cache (Search Result Cache)

Caches YouTube search results to avoid redundant API calls.

**Fields**:
- `yt_video_id` (TEXT, INDEXED) - YouTube video ID
- `yt_title` (TEXT, INDEXED) - Video title
- `yt_channel` (TEXT) - Channel name
- `yt_duration` (INTEGER, INDEXED) - Video duration in seconds
- `cached_at` (TIMESTAMP) - When cached
- `expires_at` (TIMESTAMP, INDEXED) - When expires (30-day TTL)

**Behavior**: Stores all videos from search results. Enables duration-based lookups without new API calls. Auto-cleans expired entries.

### stats_cache (Statistics Cache)

Caches pre-computed statistics for performance.

**Fields**:
- `cache_key` (TEXT, PRIMARY KEY) - Cache entry identifier
- `data` (TEXT) - JSON-encoded cached data
- `created_at` (TIMESTAMP) - When created
- `expires_at` (TIMESTAMP) - When expires (5-minute default TTL)

**Behavior**: Stores expensive calculations (e.g., stats page aggregates). Invalidated on startup and after data changes.

## Content Hash Algorithm

Enables fuzzy matching despite formatting differences:

```python
def get_content_hash(title, duration, artist=None):
    title_norm = (title or "").strip().lower()
    artist_norm = (artist or "").strip().lower()
    duration_str = str(duration or 0)

    combined = f"{title_norm}:{duration_str}:{artist_norm}"
    return hashlib.sha1(combined.encode('utf-8')).hexdigest()
```

**Why it works**:
- Lowercases everything → handles case differences
- Strips whitespace → handles spacing differences
- Includes duration → prevents matching different versions
- Optional artist → handles missing metadata

**Example matches** (same hash):
- "Never Gonna Give You Up" ≈ "never gonna give you up"
- "Song Name  " ≈ "Song Name" (trailing space)
- "Title - Artist" ≈ "Title - artist"

## Quota Management

### YouTube API Quota Limits

**Daily quota**: 10,000 units (resets midnight Pacific Time)

**Operation costs**:
- Search: 100 units
- Get video details: 1 unit
- Rate video: 50 units

**Max operations**: ~100 searches/day OR 200 ratings/day (or combinations)

### Queue-Based Rate Limiting

Conservative approach with mandatory 1-minute delays:

- **Processing rate**: 1 operation per minute (max 60/hour)
- **Priority**: Ratings processed before searches
- **Quota protection**: Worker pauses on quotaExceeded until midnight Pacific

### Quota Exhaustion Handling

**When quota exceeded**:
1. Queue worker detects quotaExceeded error from YouTube API
2. Worker pauses until midnight Pacific Time (when quota resets)
3. All new requests queued but not processed
4. Web UI shows quota exhausted status

**After midnight Pacific**:
1. YouTube quota automatically resets to 10,000 units
2. Queue worker resumes processing
3. All pending items processed sequentially (1 per minute)

### Monitoring

**Web Interface**:
- **Queue Tab** (`/logs/pending-ratings`): Real-time pending, history, errors, statistics
- **API Calls Tab** (`/logs/api-calls`): Detailed log of every API call with quota costs

**Log Files**:
- `/config/youtube_thumbs/youtube_thumbs.log` - Main application log
- `/config/youtube_thumbs/errors.log` - Error-only log
- `/config/youtube_thumbs/ratings.log` - Rating history
