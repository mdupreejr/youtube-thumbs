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

#### Process Flow

1. **User clicks button** → API call to `/api/pending/retry?batch_size=1`

2. **Rate limit check** → Enforces 30-second cooldown

3. **Get pending video** → Queries for 1 video with `pending_reason = 'quota_exceeded'`

4. **Check cache first** → Looks for match in database cache
   - If found: Resolve immediately (no API call)

5. **Search YouTube** → If not in cache, call YouTube Data API
   - **Success**: Resolve with YouTube data, mark as matched
   - **Not found**: Mark as `pending_reason = 'not_found'`
   - **Failed**: Increment failure count

6. **Display results** → Show message with statistics
   - Format: "Processed 1 pending video: X resolved, Y failed, Z not found"
   - Message stays visible for 5 seconds
   - Page reloads if video was resolved (updates counts)
   - 
#### Process Flow

1. **Quota blocked** → quotaExceeded error occurs
   - Queue paused until midnight Pacific Time
   - All YouTube API calls blocked
   - New videos stored as pending

2. **After midnight Pacific** → When quota resets
   - QuotaProber attempts recovery probe
   - Sends test YouTube API search

3. **Probe succeeds** → Quota has recovered
   - QuotaGuard clears block
   - Triggers `_retry_pending_videos()`

4. **Retry batch processing**
   - Queries: `SELECT * FROM video_ratings WHERE yt_match_pending = 1 AND pending_reason = 'quota_exceeded' LIMIT 1`
   - Processes **1 video per recovery cycle**
   - Logs: "Found 1 pending video(s) to retry after quota recovery"

5. **For each video:**
   - Log: "Retrying match for: {title} (duration: {dur}) [1/1]"
   - Check cache first (no API call)
   - If not cached, search YouTube
   - **Success**: "✓ Successfully matched: {title} → {video_id}"
   - **Not found**: "✗ No match found for: {title}"
   - **Error**: "Failed to retry pending video: {error}"

6. **Completion**
   - Log: "Pending video retry complete: X matched, Y not found, Z errors"
   - Record metrics for monitoring

### Logging

All QuotaProber activity is logged to `/config/youtube_thumbs/youtube_thumbs.log` and visible in the **Logs → Quota Prober** tab:

#### Event Categories

| Icon | Category | Description |
|------|----------|-------------|
| 🔍 | Probe | Quota recovery probe attempts |
| 🔄 | Retry | Batch retry processing |
| ✅ | Success | Successfully matched videos |
| ❌ | Error | Failed searches or errors |
| 🎉 | Recovery | Quota restored events |

#### Summary Statistics

The Quota Prober logs tab shows:
- **Probe Attempts**: Number of quota recovery probes
- **Recoveries**: Successful quota restorations
- **Retry Batches**: Number of batch processing runs
- **Videos Resolved**: Total videos successfully matched

#### Example Log Sequence

```
🎉 INFO  Quota restored! Starting automatic retry of pending videos...
🔄 INFO  Found 1 pending video(s) to retry after quota recovery (estimated time: 0.0 minutes)
🔍 INFO  Retrying match for: Never Gonna Give You Up (duration: 213) [1/1]
✅ INFO  ✓ Successfully matched: Never Gonna Give You Up → dQw4w9WgXcQ
📊 INFO  Pending video retry complete: 1 matched, 0 not found, 0 errors
```

### Comparison: Manual vs Automatic

| Feature | Manual Retry | Automatic Retry |
|---------|--------------|-----------------|
| **Trigger** | User clicks button | After quota recovery |
| **Batch Size** | 1 video | 1 video (configurable) |
| **Timing** | On-demand | Every 5 min (when quota blocked) |
| **Cooldown** | 30 seconds | Until midnight PT (quota reset) |
| **User Action** | Required | None (automatic) |
| **Best For** | Quick fixes, testing | Hands-off recovery |
| **Quota Safe** | Yes (1 at a time) | Yes (waits for recovery) |

### Retry Strategy Best Practices

#### When to Use Manual Retry

1. **Testing** - Verify credentials and quota are working
2. **Small batches** - Process a few pending videos quickly
3. **Impatient** - Don't want to wait for automatic retry
4. **Control** - Want to see results immediately

#### When to Use Automatic Retry

1. **Large batches** - Many pending videos (10+)
2. **Hands-off** - Set it and forget it
3. **Quota exhausted** - Wait for natural quota reset
4. **Overnight** - Let it process while you sleep

#### Recommended Workflow

If you have pending videos:

1. **Check quota status** on Tests page
   - If API is working → Use manual retry
   - If quota exceeded → Wait for automatic retry

2. **For 1-5 pending videos** → Manual retry
   - Click button once per minute
   - Immediate feedback

3. **For 6+ pending videos** → Automatic retry
   - Wait for quota to reset (midnight Pacific Time)
   - QuotaProber will process them automatically
   - Check Quota Prober logs tab to monitor progress

### Quota Management

#### YouTube API Quota Limits

**Default quota**: 10,000 units per day

**Search cost**: 100 units per search

**Math**: 10,000 / 100 = **100 searches per day max**

#### How Retry Affects Quota

- **Manual retry**: 1 search = 100 units
- **Automatic retry**: 1 search = 100 units (same cost)
- **Batch of 5**: 5 searches = 500 units
- **Batch of 50**: 5,000 units (half daily quota!)

#### Why Batch Size = 1

Before v1.72.4, defaults were:
- Manual: 5 videos per click
- Automatic: 50 videos per recovery

**Problem**: Could re-exhaust quota immediately

**Solution**: Changed to 1 video at a time
- Manual: 1 video = 100 units (safe)
- Automatic: 1 video per recovery cycle (very safe)

#### Quota Recovery Timeline

YouTube quotas reset at **midnight Pacific Time** daily.

Example timeline:
- **2:00 PM PST**: Quota exhausted (10,000 units used)
- **2:00 PM - Midnight**: Queue paused, waiting for quota reset
- **Midnight PST**: YouTube quota resets to 10,000 units
- **12:05 AM PST**: QuotaProber probe succeeds (quota restored)
- **12:05 AM PST**: Retry 1 pending video
- **Next probe at 12:10 AM**: If quota OK, retry another video

### Monitoring Retry Activity

#### Stats Page

View pending video statistics:
- **Total Pending**: All unmatched videos
- **Quota Exceeded**: Videos blocked by quota
- **Not Found**: Videos with no YouTube match
- **Search Failed**: Videos where search errored

#### Logs → Quota Prober Tab

Filter and view retry activity:
- **Period**: All time / Today / Last 7 days / Last 30 days
- **Event Type**: All / Probe / Retry / Success / Error / Recovery
- **Level**: All / INFO / WARNING / ERROR

