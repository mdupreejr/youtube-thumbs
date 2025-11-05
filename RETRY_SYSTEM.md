# Pending Video Retry System

This document explains how the pending video retry system works, including both manual and automatic retry mechanisms.

## Overview

When YouTube API quota is exhausted or searches fail, unmatched videos are stored as "pending" in the database. The retry system provides two ways to process these pending videos:

1. **Manual Retry** - Click button on stats page to retry 1 video at a time
2. **Automatic Retry** - Background QuotaProber automatically retries after quota recovery

## Video States

Videos in the database can be in one of these states:

### ✓ Matched (`pending_match = 0`)
- Successfully found on YouTube
- Has real `yt_video_id` populated
- All YouTube metadata available
- Can be rated and tracked

### ⏳ Pending - Quota Exceeded (`pending_match = 1`, `pending_reason = 'quota_exceeded'`)
- Quota was exhausted during search attempt
- Only Home Assistant metadata available
- Will be automatically retried after quota recovery
- Can also be manually retried

### ✗ Pending - Not Found (`pending_match = 1`, `pending_reason = 'not_found'`)
- YouTube search completed but no match found
- Marked by retry system after failed search
- Won't be retried (no YouTube video exists)
- Cached in video_ratings to prevent repeated searches

### ❌ Pending - Search Failed (`pending_match = 1`, `pending_reason = 'search_failed'`)
- Search API call failed (network error, API error, etc.)
- Different from quota_exceeded
- Can be manually retried

## Manual Retry

### Location
Stats page (`/stats`) → "Pending Videos" section

### Button: 🔄 Retry 1 Video
- Processes **1 pending video** per click
- Shows real-time status message
- Displays results for 5 seconds before clearing

### Rate Limiting
- **30-second cooldown** between button presses
- Prevents accidental quota exhaustion
- Cooldown tracked via `/tmp/youtube_thumbs_last_retry.txt`

### Process Flow

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

### Configuration

No user configuration needed. Fixed settings:
- Batch size: 1 video
- Cooldown: 30 seconds
- Delay: 2 seconds between videos (only matters if batch_size > 1)

### Example Usage

**Scenario**: You have 10 pending videos from quota exhaustion

```
1. Click "🔄 Retry 1 Video"
   → Result: "Processed 1 pending video: 1 resolved, 0 failed, 0 not found"
   → Page reloads, pending count drops to 9

2. Wait 30 seconds (cooldown)

3. Click again
   → Result: "Processed 1 pending video: 0 resolved, 0 failed, 1 not found"
   → Page reloads, pending count drops to 8 (but not_found count increases)

4. Continue clicking to process remaining videos
```

## Automatic Retry (QuotaProber)

### How It Works

The QuotaProber is a background thread that:
1. Monitors quota status
2. Detects quota recovery
3. Automatically retries pending videos

### Trigger Conditions

QuotaProber **only runs** when:
- YouTube quota has been blocked (quotaExceeded error occurred)
- Quota cooldown timer expires (default: 12 hours)
- Recovery probe succeeds (test YouTube API call works)

**Important**: QuotaProber does NOT continuously process pending videos. It only activates after quota recovery.

### Check Interval

- **Runs every 5 minutes** (300 seconds)
- Checks if quota recovery probe should be attempted
- Only probes if quota is currently blocked

### Process Flow

1. **Quota blocked** → quotaExceeded error occurs
   - QuotaGuard sets cooldown timer (12 hours default)
   - All YouTube API calls blocked
   - New videos stored as pending

2. **Cooldown expires** → After 12 hours
   - QuotaProber attempts recovery probe
   - Sends test YouTube API search

3. **Probe succeeds** → Quota has recovered
   - QuotaGuard clears block
   - Triggers `_retry_pending_videos()`

4. **Retry batch processing**
   - Queries: `SELECT * FROM video_ratings WHERE pending_match = 1 AND pending_reason = 'quota_exceeded' LIMIT 1`
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

### Configuration Options

In addon **Configuration** tab:

#### `pending_video_retry_enabled`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable/disable automatic retry after quota recovery
- Set to `false` to only use manual retry

#### `pending_video_retry_batch_size`
- **Type**: Integer
- **Default**: `1`
- **Range**: 1-500
- **Description**: Max videos to retry per recovery cycle
- **Recommended**: Leave at 1 to avoid re-exhausting quota

#### `quota_cooldown_hours`
- **Type**: Integer
- **Default**: `12`
- **Range**: 1-168 (1 hour to 1 week)
- **Description**: Hours to wait before attempting quota recovery

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

## Comparison: Manual vs Automatic

| Feature | Manual Retry | Automatic Retry |
|---------|--------------|-----------------|
| **Trigger** | User clicks button | After quota recovery |
| **Batch Size** | 1 video | 1 video (configurable) |
| **Timing** | On-demand | Every 5 min (when quota blocked) |
| **Cooldown** | 30 seconds | 12 hours (quota cooldown) |
| **User Action** | Required | None (automatic) |
| **Best For** | Quick fixes, testing | Hands-off recovery |
| **Quota Safe** | Yes (1 at a time) | Yes (waits for recovery) |

## Retry Strategy Best Practices

### When to Use Manual Retry

1. **Testing** - Verify credentials and quota are working
2. **Small batches** - Process a few pending videos quickly
3. **Impatient** - Don't want to wait for automatic retry
4. **Control** - Want to see results immediately

### When to Use Automatic Retry

1. **Large batches** - Many pending videos (10+)
2. **Hands-off** - Set it and forget it
3. **Quota exhausted** - Wait for natural quota reset
4. **Overnight** - Let it process while you sleep

### Recommended Workflow

If you have pending videos:

1. **Check quota status** on Tests page
   - If API is working → Use manual retry
   - If quota exceeded → Wait for automatic retry

2. **For 1-5 pending videos** → Manual retry
   - Click button once per minute
   - Immediate feedback

3. **For 6+ pending videos** → Automatic retry
   - Wait for quota to recover (12 hours)
   - QuotaProber will process them automatically
   - Check Quota Prober logs tab to monitor progress

## Quota Management

### YouTube API Quota Limits

**Default quota**: 10,000 units per day

**Search cost**: 100 units per search

**Math**: 10,000 / 100 = **100 searches per day max**

### How Retry Affects Quota

- **Manual retry**: 1 search = 100 units
- **Automatic retry**: 1 search = 100 units (same cost)
- **Batch of 5**: 5 searches = 500 units
- **Batch of 50**: 5,000 units (half daily quota!)

### Why Batch Size = 1

Before v1.72.4, defaults were:
- Manual: 5 videos per click
- Automatic: 50 videos per recovery

**Problem**: Could re-exhaust quota immediately

**Solution**: Changed to 1 video at a time
- Manual: 1 video = 100 units (safe)
- Automatic: 1 video per recovery cycle (very safe)

### Quota Recovery Timeline

YouTube quotas reset at **midnight Pacific Time** daily.

Example timeline:
- **2:00 PM PST**: Quota exhausted (10,000 units used)
- **2:00 PM - 2:00 AM**: QuotaProber blocked, cooldown active
- **2:00 AM PST**: Cooldown expires (12 hours), probe attempted
- **2:00 AM - Midnight**: Probe fails (quota not reset yet)
- **Midnight PST**: Quota resets to 10,000 units
- **12:05 AM PST**: QuotaProber probe succeeds
- **12:05 AM PST**: Retry 1 pending video
- **Next probe at 12:10 AM**: If quota OK, retry another video

## Monitoring Retry Activity

### Stats Page

View pending video statistics:
- **Total Pending**: All unmatched videos
- **Quota Exceeded**: Videos blocked by quota
- **Not Found**: Videos with no YouTube match
- **Search Failed**: Videos where search errored

### Logs → Quota Prober Tab

Filter and view retry activity:
- **Period**: All time / Today / Last 7 days / Last 30 days
- **Event Type**: All / Probe / Retry / Success / Error / Recovery
- **Level**: All / INFO / WARNING / ERROR

### Example Queries

**Check retry success rate**:
- Go to Logs → Quota Prober
- Filter: Event Type = "Success"
- Count green ✅ entries

**Find errors**:
- Filter: Event Type = "Error"
- Review red ❌ entries for failure reasons

**Monitor automatic processing**:
- Filter: Event Type = "Retry"
- See batch processing runs and statistics

## Troubleshooting

### Manual Retry Shows "No pending videos"

**Cause**: All pending videos have `pending_reason != 'quota_exceeded'`

**Solutions**:
1. Check stats page for breakdown by reason
2. If all are "not_found", those won't be retried (no match exists)
3. If all are "search_failed", manually retry after fixing network/API issues

### Automatic Retry Not Running

**Cause**: Quota never blocked or cooldown not expired

**Check**:
1. Logs → Quota Prober tab
2. Look for "Quota restored!" message
3. If missing, quota was never blocked

**Solutions**:
- Use manual retry instead
- QuotaProber only runs after quota recovery, not continuously

### All Retries Failing

**Causes**:
1. Quota still exceeded (check Tests page)
2. Network issues (check internet connection)
3. API credentials expired (regenerate credentials.json)
4. Videos genuinely don't exist on YouTube

**Debug**:
1. Check main logs (not Quota Prober logs)
2. Look for "Manual retry:" or "Retrying match for:" entries
3. Check error messages

### Retry Says "Quota Exceeded" Immediately

**Cause**: You hit quota limit too fast

**Solutions**:
1. Wait 30 seconds between manual retries
2. Don't click button rapidly
3. Current batch_size=1 prevents this, but older versions with batch_size=5 could trigger it

## API Reference

### Manual Retry Endpoint

```http
POST /api/pending/retry?batch_size=1
```

**Query Parameters**:
- `batch_size` (optional): Number of videos to retry (default: 5, max: 50)

**Response** (success):
```json
{
  "success": true,
  "processed": 1,
  "resolved": 1,
  "failed": 0,
  "not_found": 0,
  "quota_blocked": false,
  "message": "Processed 1 pending videos: 1 resolved, 0 failed, 0 not found"
}
```

**Response** (rate limited):
```json
{
  "success": false,
  "error": "Please wait 30 seconds between retry attempts"
}
```

**HTTP Status Codes**:
- `200`: Success
- `429`: Too Many Requests (rate limited)
- `400`: Invalid batch_size parameter
- `500`: Server error

### Pending Summary Endpoint

```http
GET /api/pending/summary
```

**Response**:
```json
{
  "total": 10,
  "quota_exceeded": 7,
  "not_found": 2,
  "search_failed": 1,
  "unknown": 0
}
```

## Database Schema

### Pending Video Fields

Fields in `video_ratings` table related to pending videos:

```sql
-- Pending status
pending_match INTEGER DEFAULT 0  -- 0=matched, 1=pending
pending_reason TEXT              -- 'quota_exceeded', 'not_found', 'search_failed'

-- Home Assistant metadata (always populated)
ha_content_id TEXT               -- Placeholder ID (ha_hash:abc123)
ha_title TEXT                    -- Song title from HA
ha_artist TEXT                   -- Artist from HA
ha_duration INTEGER              -- Duration in seconds
ha_content_hash TEXT             -- SHA1 hash for matching

-- YouTube metadata (NULL when pending)
yt_video_id TEXT                 -- NULL until matched
yt_title TEXT                    -- NULL until matched
yt_channel TEXT                  -- NULL until matched
-- ... other yt_ fields NULL until matched

-- Match tracking
yt_match_pending INTEGER         -- Same as pending_match (v1.64.0+)
yt_match_attempts INTEGER        -- Number of match attempts
yt_match_last_attempt TIMESTAMP  -- Last attempt timestamp
```

### Example Records

**Pending (Quota Exceeded)**:
```sql
yt_video_id: NULL
ha_content_id: "ha_hash:a1b2c3d4e5f6"
ha_title: "New Song Title"
pending_match: 1
pending_reason: "quota_exceeded"
yt_match_attempts: 1
yt_match_last_attempt: "2025-01-15 14:30:00"
```

**Resolved**:
```sql
yt_video_id: "dQw4w9WgXcQ"
ha_content_id: NULL  -- Cleared after resolution
ha_title: "Never Gonna Give You Up"
pending_match: 0
pending_reason: NULL
yt_match_attempts: 1
```

## Version History

### v1.72.4 - Reduce Retry Rate (2025-01-15)
- Changed manual retry from 5 videos → 1 video
- Changed automatic retry from 50 videos → 1 video
- Updated delays from 10s → 60s between videos
- Improved logging visibility (DEBUG → INFO)

### v1.72.3 - Improve Retry Feedback (2025-01-15)
- Increased status message display time (2s → 5s)
- Only reload page if videos resolved
- Keep message visible if all failed

### v1.72.0 - Manual Retry Button (2025-01-15)
- Added manual retry button to stats page
- Added `/api/pending/retry` endpoint
- Added pending video statistics display
- 30-second rate limiting

### v1.51.0 - Automatic Retry (2024-12-XX)
- Added QuotaProber automatic retry system
- Added `pending_video_retry_enabled` config
- Added `pending_video_retry_batch_size` config
- Added retry metrics and logging

### v1.50.0 - Pending Video System (2024-12-XX)
- Added `pending_match` and `pending_reason` fields
- Added `ha_content_id` for pending placeholders
- Quota-blocked videos stored as pending

## See Also

- [README.md](README.md) - Main documentation
- [INSTALL.md](INSTALL.md) - Installation guide
- [config.json](config.json) - Configuration schema
- [quota_prober.py](quota_prober.py) - QuotaProber implementation
- [routes/data_api.py](routes/data_api.py) - Manual retry endpoint
