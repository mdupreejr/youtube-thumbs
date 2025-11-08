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
3. **Filter by duration**: Only consider results where YouTube duration matches HA duration + 1 second
4. **Select best match**: Select the highest quality title match with the correct duration.
5. **Store in database**: Save yt information in the video_ratings table.

**Search Hit**: Video matched and cached for future plays.

### 3. Quota Exceeded Handling

## Centralized Queue System

As of v3.44.0, all YouTube API operations use a unified queue system for better rate limiting, error handling, and monitoring.

### Queue Architecture

All YouTube API requests (searches and ratings) are processed through a single queue table with these features:

- **Unified queue table**: All operations stored in one `queue` table
- **Single background worker**: One `queue_worker.py` process handles all API requests
- **1-minute rate limiting**: Mandatory delay between all API requests
- **Quota exhaustion handling**: Auto-pauses until midnight Pacific when quota exceeded
- **Database persistence**: All operations stored until processed
- **Priority system**: Ratings (priority=1) processed before searches (priority=2)

### Queue States

Each queue item progresses through these states:

- `pending`: Waiting to be processed
- `processing`: Currently being handled by the worker
- `completed`: Successfully processed
- `failed`: Processing failed (with error message)

### Web UI Queue Management

The queue system provides a comprehensive web interface accessible in Home Assistant:

#### Queue Tab Features

1. **Pending Items**: Shows all queue items waiting to be processed
2. **History**: Displays completed and failed operations with timestamps
3. **Error Monitoring**: Tracks failed operations with detailed error messages
4. **Real-time Status**: Visual indicators for queue item states
5. **Detailed View**: Click any item to view full request payloads, API responses, timestamps

#### Queue Statistics

- Overall queue metrics (total, pending, processing, completed, failed)
- Per-type statistics (search vs rating operations)
- Processing rates and success rates over time periods
- Worker health monitoring with last activity timestamps

### Migration from Legacy Queues

The system automatically migrates from the legacy queue structure:

- `search_queue` table entries → `queue` table with `type='search'`
- `video_ratings` rating queue fields → `queue` table with `type='rating'`
- Legacy tables maintained for backward compatibility during transition

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

### api_usage (API Quota Tracking)

Tracks YouTube API usage by hour for quota management.

**Fields**:
- `date` (TEXT, PRIMARY KEY) - Date in YYYY-MM-DD format
- `hour_00` through `hour_23` (INTEGER) - API quota units used per hour
- `timestamp` (TIMESTAMP) - Last update timestamp

**Behavior**:
- Records every YouTube API call with quota cost (search=100, videos.list=1)
- Enables quota usage analytics and trends

### api_call_log (Detailed API Logging)

Detailed log of every YouTube API call for debugging and analysis.

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment ID
- `timestamp` (TIMESTAMP, INDEXED) - When API call was made
- `api_method` (TEXT, INDEXED) - API method called (search, videos.list, etc.)
- `operation_type` (TEXT) - High-level operation (search_video, get_video_details, etc.)
- `query_params` (TEXT) - Query parameters sent to API
- `quota_cost` (INTEGER) - Quota units consumed
- `success` (BOOLEAN, INDEXED) - Whether call succeeded
- `error_message` (TEXT) - Error message if failed
- `results_count` (INTEGER) - Number of results returned
- `context` (TEXT) - Additional context (e.g., video title)

**Behavior**:
- Logs every YouTube API interaction
- Enables analysis of API call patterns
- Helps identify quota waste
- Accessible via /logs/api-calls web interface

### queue (Unified Queue System)

Centralized queue for all YouTube API operations (searches and ratings).

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment queue item ID
- `type` (TEXT, INDEXED) - Queue item type: 'search' or 'rating'
- `priority` (INTEGER, INDEXED) - Processing priority (1=ratings, 2=searches)
- `status` (TEXT, INDEXED) - Current status: 'pending', 'processing', 'completed', 'failed'
- `payload` (TEXT) - JSON-encoded operation data (video ID, search terms, etc.)
- `requested_at` (TIMESTAMP, INDEXED) - When item was added to queue
- `attempts` (INTEGER) - Number of processing attempts
- `last_attempt` (TIMESTAMP) - Most recent processing attempt
- `last_error` (TEXT) - Error message if processing failed
- `completed_at` (TIMESTAMP) - When item was successfully processed

**Behavior**:
- All YouTube API requests flow through this queue (no direct API calls)
- Single worker process handles items sequentially with 1-minute delays
- Automatic retry logic for failed operations
- Quota exhaustion pauses queue until midnight Pacific time
- Web UI provides real-time visibility into queue status and history

### search_results_cache (Search Result Cache)

Caches YouTube search results to avoid redundant API calls.

**Fields**:
- `id` (INTEGER, PRIMARY KEY) - Auto-increment ID
- `yt_video_id` (TEXT, INDEXED) - YouTube video ID
- `yt_title` (TEXT, INDEXED) - Video title
- `yt_channel` (TEXT) - Channel name
- `yt_duration` (INTEGER, INDEXED) - Video duration in seconds
- `cached_at` (TIMESTAMP) - When video was cached
- `expires_at` (TIMESTAMP, INDEXED) - When cache entry expires
- Additional YouTube metadata fields

**Behavior**:
- Stores all videos from search results (not just matched ones)
- 30-day TTL (configurable)
- Enables duration-based lookups without new API calls
- Automatically cleans expired entries

### stats_cache (Statistics Cache)

Caches pre-computed statistics for improved performance.

**Fields**:
- `cache_key` (TEXT, PRIMARY KEY) - Cache entry identifier (e.g., 'stats_page')
- `data` (TEXT) - JSON-encoded cached data
- `created_at` (TIMESTAMP) - When cache entry was created
- `expires_at` (TIMESTAMP) - When cache entry expires

**Behavior**:
- Stores expensive statistics calculations (e.g., main stats page data)
- Default 5-minute TTL for stats page
- Reduces database queries for frequently accessed stats
- Automatically invalidated on startup
- JSON-serialized Python objects for flexible data storage

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

### Quota Exhaustion Handling

#### Process Flow

1. **Quota exceeded error occurs**
   - Queue worker detects quotaExceeded error from YouTube API
   - Queue worker pauses until midnight Pacific Time (when quota resets)
   - All YouTube API operations blocked
   - New rating/search requests are queued but not processed

2. **Queue continues accepting requests**
   - Users can still call thumbs_up/thumbs_down endpoints
   - Requests are added to queue with status='pending'
   - Endpoints return 503 status with "Quota exceeded" message
   - No API calls are attempted while quota is exhausted

3. **After midnight Pacific Time**
   - YouTube quota automatically resets to 10,000 units
   - Queue worker attempts next queue item
   - If successful, queue processing resumes normally
   - All pending items processed sequentially with 1-minute delays

4. **Queue processes all items**
   - Worker processes queue items in priority order (ratings first, then searches)
   - Each item processed with mandatory 1-minute delay
   - Failed items marked with error message and retry count
   - Successful items marked as completed

### Queue Monitoring

All queue activity is visible through the web interface and logged to `/config/youtube_thumbs/youtube_thumbs.log`:

- **Queue Tab**: Real-time view of pending, processing, completed, and failed items
- **Queue Stats**: Processing rates, success rates, error counts
- **API Call Logs**: Detailed log of every YouTube API call with quota costs and errors

### Quota Management

#### YouTube API Quota Limits

**Default quota**: 10,000 units per day

**Common operation costs**:
- Search: 100 units per search
- Get video details: 1 unit per video
- Rate video: 50 units per rating

**Math**: 10,000 / 100 = **100 searches per day max**

#### Queue-Based Rate Limiting

The addon uses a queue system with mandatory 1-minute delays between all YouTube API calls:

- **Search operations**: Queued with priority=2, processed after ratings
- **Rating operations**: Queued with priority=1, processed first
- **Processing rate**: Maximum 60 operations per hour (1 per minute)
- **Quota protection**: Worker pauses on quotaExceeded until midnight Pacific Time

This conservative approach ensures quota is never exhausted through rapid API calls.

#### Quota Recovery Timeline

YouTube quotas reset at **midnight Pacific Time** daily.

Example timeline:
- **2:00 PM PST**: Quota exhausted (10,000 units used)
- **2:00 PM - Midnight**: Queue worker paused, all API calls blocked
- **Midnight PST**: YouTube quota automatically resets to 10,000 units
- **12:01 AM PST**: Queue worker attempts next item
- **12:01 AM PST**: If successful, queue processing resumes
- **12:02 AM PST**: Next item processed (1-minute delay enforced)

### Queue Monitoring

#### Web Interface

The web interface provides comprehensive queue monitoring:

- **Queue Tab**: View all pending, processing, completed, and failed queue items
- **Queue Stats**: Processing rates, success rates, worker health
- **API Call Logs**: Every YouTube API call logged with quota costs and errors

#### Database Tables

Queue data is stored across several tables:

- **queue**: All pending YouTube API operations
- **api_call_log**: Detailed log of every API call
- **api_usage**: Hourly quota usage tracking

