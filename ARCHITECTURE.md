# YouTube Thumbs - Architecture Documentation

Technical overview of the matching system, queue architecture, and database schema.

## Video Matching System

### 1. Cache Lookup (Instant)
1. **Content Hash**: SHA1 of `title + duration + artist` for fuzzy matching
2. **Title + Duration**: Exact match with strict duration rules (exact or +1 second only)

### 2. YouTube Search (Queued)
On cache miss, searches are queued with priority=2 for background processing.

## Queue System

**Single unified queue** for all YouTube API operations:
- **Rate limiting**: 1 operation per minute (60/hour max)
- **Priority**: Ratings (1) before searches (2)
- **Quota protection**: Auto-pauses until midnight Pacific when quota exceeded
- **Crash recovery**: Resets stuck 'processing' items on startup

**States**: `pending` → `processing` → `completed` / `failed`

**Web UI** (`/logs/pending-ratings`): Monitor pending items, history, errors, and statistics.

## Database Schema

### video_ratings
Stores **matched videos only** with YouTube and Home Assistant metadata.

**Key fields**:
- `yt_video_id` (PK), `yt_title`, `yt_channel`, `yt_duration`, `yt_url`
- `ha_content_hash` (indexed), `ha_title` (indexed), `ha_artist`, `ha_duration` (indexed)
- `rating`, `rating_score`, `play_count`, `date_last_played` (indexed)

### queue
Centralized queue for all API operations.

**Fields**: `id` (PK), `type`, `priority` (indexed), `status` (indexed), `payload`, `requested_at` (indexed), `attempts`, `last_error`, `completed_at`

### api_call_log
Detailed logging of every YouTube API call.

**Fields**: `id` (PK), `timestamp` (indexed), `api_method` (indexed), `operation_type`, `query_params`, `quota_cost`, `success` (indexed), `error_message`, `results_count`, `context`

### api_usage
Tracks hourly quota usage by date.

**Fields**: `date` (PK), `hour_00` through `hour_23`

### search_results_cache
Caches YouTube search results (30-day TTL).

**Fields**: `yt_video_id` (indexed), `yt_title` (indexed), `yt_duration` (indexed), `yt_channel`, `cached_at`, `expires_at` (indexed)

### stats_cache
Pre-computed statistics cache (5-minute default TTL).

**Fields**: `cache_key` (PK), `data` (JSON), `created_at`, `expires_at`

## Content Hash Algorithm

```python
def get_content_hash(title, duration, artist=None):
    title_norm = (title or "").strip().lower()
    artist_norm = (artist or "").strip().lower()
    duration_str = str(duration or 0)
    combined = f"{title_norm}:{duration_str}:{artist_norm}"
    return hashlib.sha1(combined.encode('utf-8')).hexdigest()
```

Enables fuzzy matching by normalizing case and whitespace while including duration for accuracy.

## Quota Management

**Daily limit**: 10,000 units (resets midnight Pacific)

**Operation costs**:
- Search: 100 units (~100 searches/day)
- Get details: 1 unit
- Rate video: 50 units (~200 ratings/day)

### YouTube Duration Offset

**Critical**: YouTube reports durations **+1 second** longer than Home Assistant due to different rounding methods.

**Implementation**: `YOUTUBE_DURATION_OFFSET = 1` (constants.py). Matching accepts exact duration OR +1s ONLY.

**Code references**:
- `constants.py`: Defines offset constant
- `youtube_api.py:319`: Duration matching logic
- `helpers/search_helpers.py:139`: Cache lookup with tolerance=1

### Quota Exhaustion

On quota exceeded: Worker pauses until midnight Pacific, queues continue accepting requests, web UI shows quota status. Processing resumes automatically after midnight reset.

### Monitoring

- **Queue Tab**: Real-time queue monitoring at `/logs/pending-ratings`
- **API Calls Tab**: Detailed API call history at `/logs/api-calls`
- **Log files**: `youtube_thumbs.log`, `errors.log`, `ratings.log`
