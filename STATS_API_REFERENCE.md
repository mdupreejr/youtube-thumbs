# Statistics API Reference

## Quick Reference

### Page Routes

| Route | Description |
|-------|-------------|
| `/stats` | Statistics dashboard page (HTML) |

### API Routes

All API routes return JSON in format:
```json
{
    "success": true,
    "data": { ... }
}
```

#### Summary Statistics
```
GET /api/stats/summary
```
Returns comprehensive summary including:
- total_videos
- total_plays
- liked (count)
- disliked (count)
- unrated (count)
- unique_channels
- avg_rating_score

**Example Response:**
```json
{
    "success": true,
    "data": {
        "total_videos": 150,
        "total_plays": 2500,
        "liked": 75,
        "disliked": 10,
        "unrated": 65,
        "unique_channels": 42,
        "avg_rating_score": 0.85
    }
}
```

#### Most Played Videos
```
GET /api/stats/most_played?limit=10
```
Parameters:
- `limit` (optional): Number of results, 1-100 (default: 10)

Returns array of videos ordered by play count.

**Example Response:**
```json
{
    "success": true,
    "data": [
        {
            "yt_video_id": "abc123",
            "ha_title": "Song Title",
            "yt_title": "Song Title - Artist",
            "ha_artist": "Artist Name",
            "yt_channel": "Channel Name",
            "play_count": 42,
            "rating": "like",
            "rating_score": 1
        }
    ]
}
```

#### Top Rated Videos
```
GET /api/stats/top_rated?limit=10
```
Parameters:
- `limit` (optional): Number of results, 1-100 (default: 10)

Returns array of videos ordered by rating score (excludes unrated).

#### Recent Activity
```
GET /api/stats/recent?limit=20
```
Parameters:
- `limit` (optional): Number of results, 1-100 (default: 20)

Returns recently played videos ordered by date_last_played.

#### Channel Statistics
```
GET /api/stats/channels?limit=10
```
Parameters:
- `limit` (optional): Number of results, 1-100 (default: 10)

**Example Response:**
```json
{
    "success": true,
    "data": [
        {
            "yt_channel": "Channel Name",
            "yt_channel_id": "UCxxx",
            "video_count": 15,
            "total_plays": 250,
            "avg_rating": 0.85
        }
    ]
}
```

#### Category Breakdown
```
GET /api/stats/categories
```
Returns video count by YouTube category.

**Example Response:**
```json
{
    "success": true,
    "data": [
        {
            "yt_category_id": 10,
            "count": 120
        },
        {
            "yt_category_id": 24,
            "count": 30
        }
    ]
}
```

**YouTube Category IDs:**
- 1: Film & Animation
- 2: Autos & Vehicles
- 10: Music
- 15: Pets & Animals
- 17: Sports
- 20: Gaming
- 22: People & Blogs
- 23: Comedy
- 24: Entertainment
- 26: Howto & Style
- 27: Education
- 28: Science & Technology

#### Timeline Statistics
```
GET /api/stats/timeline?days=7
```
Parameters:
- `days` (optional): Number of days to look back, 1-365 (default: 7)

Returns play count grouped by date.

**Example Response:**
```json
{
    "success": true,
    "data": [
        {
            "date": "2025-10-23",
            "play_count": 15
        },
        {
            "date": "2025-10-24",
            "play_count": 22
        }
    ]
}
```

## Error Responses

All endpoints return errors in format:
```json
{
    "success": false,
    "error": "Error message"
}
```

HTTP Status Codes:
- 200: Success
- 400: Bad request (invalid parameters)
- 500: Internal server error

## Testing Endpoints

Using curl:
```bash
# Summary
curl http://localhost:21812/api/stats/summary

# Most played (top 5)
curl http://localhost:21812/api/stats/most_played?limit=5

# Top rated (top 10)
curl http://localhost:21812/api/stats/top_rated?limit=10

# Recent activity
curl http://localhost:21812/api/stats/recent?limit=20

# Channels
curl http://localhost:21812/api/stats/channels?limit=10

# Categories
curl http://localhost:21812/api/stats/categories

# Timeline (last 30 days)
curl http://localhost:21812/api/stats/timeline?days=30
```

## Database Queries

All queries filter out unmatched videos:
```sql
WHERE pending_match = 0
```

This ensures only successfully matched YouTube videos are included in statistics.

## Performance Notes

- All list endpoints enforce limits (1-100)
- Timeline endpoint limits days (1-365)
- Summary endpoint uses single optimized query
- No N+1 query issues
- Results use existing database indexes
