# YouTube Thumbs - Home Assistant Add-on

Rate YouTube videos (👍/👎) for songs playing on your AppleTV through Home Assistant. Perfect for Lutron Pico remote integration or any automation that needs to rate music.

## Features

- 🎵 **Rate YouTube videos** - Like/dislike songs via REST API or Web UI
- ⚡ **Bulk Rating Interface** - Rate multiple unrated songs at once
- 🔍 **Smart video matching** - Automatic YouTube search with duration matching and caching
- 📊 **Statistics & Analytics** - Track playback stats, most played songs, and rating distribution
- 🛡️ **Quota protection** - Queue-based processing prevents quota exhaustion
- 💾 **SQLite database** - Local storage with comprehensive metadata tracking
- 📈 **API monitoring** - Detailed logging of all YouTube API calls and quota usage

## Quick Start

See **[INSTALL.md](INSTALL.md)** for complete installation and OAuth setup instructions.

### Basic Steps

1. Add this repository to Home Assistant
2. Install "YouTube Thumbs Rating" add-on
3. Copy `credentials.json` to `/addon_configs/XXXXXXXX_youtube_thumbs/`
4. Configure media player entity in add-on configuration
5. Start the add-on

**First run**: The add-on will automatically generate `token.json` and prompt you to authorize via the OAuth flow.

## Configuration

### Add-on Options

| Option | Default | Description |
|--------|---------|-------------|
| `media_player_entity` | (required) | Your AppleTV media player entity ID |
| `log_level` | INFO | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `search_max_results` | 25 | Max YouTube search results to fetch |
| `search_max_candidates` | 10 | Max duration-matched candidates to check |
| `debug_endpoints_enabled` | false | Enable debug API endpoints |

## Security Architecture

### Network Binding

As of **v5.5.0**, the addon binds to `127.0.0.1:21812` (localhost only) instead of `0.0.0.0:21812`. This prevents direct network access while maintaining full functionality:

- **Home Assistant automations** continue to work via `http://localhost:21812`
- **Web UI** remains accessible through Home Assistant's ingress proxy
- **Network attacks** are blocked since the port is not exposed to the network

This change improves security without breaking existing automations.

### Authentication Layers

1. **Network isolation**: Server only accepts localhost connections
2. **Supervisor authentication**: Automatic token-based authentication from Home Assistant
3. **OAuth credentials**: YouTube API access secured by OAuth 2.0 tokens

### Current Security Model

The addon currently relies on network binding for access control. Home Assistant automations use `rest_command` services that call `http://localhost:21812` endpoints. The localhost binding ensures only the Home Assistant host can access the API.

### Planned Enhancement (v6.0.0)

Future versions will transition to ingress-only access, removing the direct port binding entirely. This will require updating automations to use ingress URLs, providing an additional authentication layer through Home Assistant's ingress proxy system.

### Home Assistant Integration

Add REST commands to your `configuration.yaml`:

```yaml
rest_command:
  youtube_thumbs_up:
    url: "http://localhost:21812/thumbs_up"
    method: POST
    timeout: 30

  youtube_thumbs_down:
    url: "http://localhost:21812/thumbs_down"
    method: POST
    timeout: 30
```

Create automations to call these services:

```yaml
automation:
  - alias: "Lutron Pico - Thumbs Up"
    trigger:
      - platform: device
        device_id: your_pico_remote_id
        type: press
        subtype: button_1
    action:
      - service: rest_command.youtube_thumbs_up

  - alias: "Lutron Pico - Thumbs Down"
    trigger:
      - platform: device
        device_id: your_pico_remote_id
        type: press
        subtype: button_2
    action:
      - service: rest_command.youtube_thumbs_down
```

## Web Interface

Access via **OPEN WEB UI** button in the add-on page:

- **Tests** - System status with live health checks, queue worker status, quota usage, cache performance, and detailed metrics
- **Bulk Rating** - Rate multiple unrated songs at once with pagination
- **Stats** - Playback statistics, rating distribution, most played videos, and top channels
- **Database** - Browse and filter database tables (video ratings, queue, search cache)
- **Rated Songs** - View history of all rated videos with timestamps and ratings
- **Matches** - Browse matched videos showing search results and duration matching
- **Recent** - Recent activity log across all operations
- **Errors** - Error log for troubleshooting failed operations
- **API Calls** - Detailed YouTube API call history with quota tracking and costs
- **Queue** - View pending and processing queue items (searches and ratings)
- **DB Admin** - Full sqlite_web interface for advanced database queries and management

## How It Works

When you trigger a rating (via REST API or Web UI), the addon:
1. Fetches current media from Home Assistant
2. Checks database cache for exact match (content hash or title+duration)
3. If no cache hit: Queues search operation for background processing
4. Queue worker searches YouTube, filters by duration, and caches the match
5. Queues and processes the rating operation via YouTube API
6. Updates database with rating and metadata

**See [ARCHITECTURE.md](ARCHITECTURE.md#video-matching-system) for detailed matching algorithm and caching logic.**

### Queue Architecture

All YouTube API calls are processed through a unified queue system with automatic rate limiting and quota protection. The queue worker processes operations sequentially with 1-minute delays between API calls. Ratings are prioritized over searches.

**See [ARCHITECTURE.md](ARCHITECTURE.md#queue-system) for detailed queue architecture and implementation.**

## Quota Management

YouTube Data API v3 has a daily quota of **10,000 units** that resets at **midnight Pacific Time**. Common operations cost: Search (100 units), Rate video (50 units), Get details (1 unit).

When quota is exceeded, the queue worker automatically pauses until midnight Pacific. New requests continue to queue and will be processed after quota resets.

**See [ARCHITECTURE.md](ARCHITECTURE.md#quota-management) for detailed quota costs, monitoring, and management strategies.**

## API Endpoints

### Rate Current Song

- `POST /thumbs_up` - Rate currently playing song as like
- `POST /thumbs_down` - Rate currently playing song as dislike

### Direct Video Rating

- `POST /api/rate/<video_id>/like` - Rate specific YouTube video as like
- `POST /api/rate/<video_id>/dislike` - Rate specific YouTube video as dislike

### Health Monitoring (v5.20.0+)

- `GET /health` - Comprehensive health check with content verification
  - Returns detailed status of all components (database, YouTube API, queue worker, Home Assistant, endpoints)
  - Actually verifies endpoint content, not just HTTP status codes
  - Returns HTTP 200 if healthy, 503 if degraded/unhealthy
- `GET /health/simple` - Simple health check for load balancers (just checks DB connectivity)

### System Status
- `GET /metrics` - Prometheus-compatible metrics

### Data Access

- `GET /api/unrated?page=1` - Paginated list of unrated songs
- `GET /api/stats/summary` - Statistics summary

For complete API documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Database

All data is stored in SQLite database at `/config/youtube_thumbs/ratings.db`. The database includes tables for video ratings, queue operations, API call logs, and caching.

Access via **Database Admin** in the web interface or explore using the **Data Viewer** page.

**See [ARCHITECTURE.md](ARCHITECTURE.md#database-schema) for complete database schema and field documentation.**

## Troubleshooting

### No videos being rated

**Check credentials:**
```bash
# Verify files exist in addon_configs directory
ls -la /addon_configs/XXXXXXXX_youtube_thumbs/
# Should show: credentials.json and token.json
```

**Check queue worker:**
- Open add-on **Log** tab
- Look for `[QUEUE]` prefixed messages
- Worker processes one item from queue then waits 1 minute before starting the next item from the queue

### "No media currently playing"

- Verify media player is playing YouTube content on AppleTV
- Check `media_player_entity` in add-on configuration
- Test entity in Home Assistant Developer Tools

### OAuth/Authentication errors

- Ensure `credentials.json` is from Google Cloud Console
- Verify YouTube Data API v3 is enabled in your Google Cloud project
- Delete `token.json` and restart to re-authenticate

### Quota exceeded

- **Wait**: Quota automatically resets at midnight Pacific Time
- **Check usage**: View API Calls page in web UI
- **Optimize**: Reduce `search_max_results` in configuration

**Always check logs first**: Settings → Add-ons → YouTube Thumbs Rating → Log

## Security

- OAuth credentials stored in `/addon_configs/` (persistent across updates)
- Authentication via Home Assistant Supervisor token (automatic)
- Uses host networking (`host_network: true`) for seamless HA integration
- API bound to `127.0.0.1:21812` (localhost only - network access blocked)
- Web UI accessible through Home Assistant ingress proxy
- Database viewer bound to `127.0.0.1` by default (localhost only)
- ⚠️ **Never share your `credentials.json` or `token.json` files**

## Documentation

- **[INSTALL.md](INSTALL.md)** - Detailed installation and OAuth setup guide
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technical architecture, database schema, and implementation details

## Development Roadmap

### Code Quality Improvements

Based on comprehensive code review, the following tasks address critical technical debt and improve code maintainability.

---

#### Priority 1: Critical Fixes (Do First)

These issues cause bugs or major code quality problems that should be addressed immediately.

- [x] **Fix format string bugs in error logging**
  - File: `/routes/stats_routes.py`
  - Lines: 417, 508
  - Issue: Using `%s` placeholders with `.format()` instead of `{}`
  - Action: Replace `%s` with `{}` in format strings
  - Impact: Prevents potential logging errors and exceptions

- [x] **Create unified sorting helper function**
  - Create: `/helpers/sorting_helpers.py`
  - Action: Implement `sort_items(items, sort_by=None, sort_dir='asc', default_key=None)` function
  - Features: Handle None values, support nested keys, consistent sorting behavior
  - Impact: Single source of truth for all sorting operations

- [x] **Replace duplicate sorting implementations (18+ instances)**
  - **Phase 1**: `/routes/logs_routes_helpers.py` (7 instances)
    - Lines: 44-56, 97-109, 149-161, 203-214, 256-268, 310-321, 362-374
    - Functions: `format_errors()`, `format_recent()`, `format_queue()`, `format_api_calls()`, `format_rated_songs()`, `format_matches()`, `format_searches()`
  - **Phase 2**: `/routes/stats_routes.py` (2 instances)
    - Lines: 285-297, 458-470
    - Functions: Most played videos and top channels sorting
  - **Phase 3**: `/routes/logs_routes.py` (1 instance)
    - Line: 38-50
    - Function: Main logs route sorting
  - **Phase 4**: Search remaining files for additional sorting implementations
    - Use grep to find: `sort_by`, `sort_dir`, `reverse=` patterns
  - Action: Replace all with calls to new `sorting_helpers.sort_items()`
  - Impact: Eliminates inconsistent behavior, reduces ~200 lines of duplicate code

- [ ] **Standardize error handling across routes**
  - Files: All route files (`/routes/*.py`)
  - Issue: 25+ try-except blocks with inconsistent error handling patterns
  - Action: Create error handling decorator or helper function
  - Features: Consistent logging format, proper HTTP status codes, user-friendly error messages
  - Impact: Improved debugging and user experience

---

#### Priority 2: High Priority

These improvements significantly enhance code quality and maintainability.

- [x] **Consolidate video table building code**
  - Files: Multiple routes building similar video list tables
  - Affected: `/routes/logs_routes_helpers.py`, `/routes/stats_routes.py`
  - Action: Create `build_video_table()` helper in `/helpers/template_helpers.py`
  - Features: Consistent column structure, reusable table formatting
  - Impact: Reduces duplicate code, ensures consistent UI

- [x] **Remove unused CSS file**
  - File: `/static/css/stats_visualizations.css`
  - Issue: Not referenced in any template files
  - Action: Delete file or add to templates if needed
  - Verification: Search all `.html` files for references to this CSS
  - Impact: Reduces technical debt, cleaner codebase

- [x] **Consolidate row click navigation JavaScript**
  - Files: Multiple templates with duplicate `tr.clickable-row` handlers
  - Issue: 3+ duplicate implementations of the same functionality
  - Action: Use PageBuilder's `set_row_click_navigation()` method consistently
  - Alternative: Extract to shared JavaScript file in `/static/js/`
  - Impact: DRY principle, easier maintenance

- [x] **Add comprehensive sorting tests**
  - Create: `/tests/test_sorting_helpers.py`
  - Coverage: None handling, nested keys, ascending/descending, edge cases
  - Action: Write unit tests for new sorting helper
  - Impact: Prevents regression, documents expected behavior

---

#### Priority 3: Medium Priority

Nice-to-have improvements that enhance consistency and user experience.

- [ ] **Standardize empty state messages**
  - Files: All route handlers and templates
  - Issue: Inconsistent messaging when no data available
  - Action: Create standard empty state templates/messages
  - Examples: "No rated songs yet", "No errors found", "Queue is empty"
  - Impact: Better UX consistency

- [ ] **Add integration tests for sorting endpoints**
  - Create: `/tests/test_sorting_integration.py`
  - Coverage: Test all paginated endpoints with various sort parameters
  - Endpoints: `/errors`, `/recent`, `/queue`, `/rated`, `/matches`, stats pages
  - Impact: Ensures sorting works correctly across all pages

- [ ] **Document helper functions usage**
  - Update: `/CODE_ORGANIZATION.md`
  - Action: Add examples for new sorting helpers and error handling utilities
  - Include: When to use, parameters, return values, examples
  - Impact: Easier for contributors to use existing utilities

- [ ] **Audit and consolidate badge formatting**
  - Files: Multiple uses of `format_status_badge()` and `format_badge()`
  - Action: Ensure consistent use of existing helpers vs inline HTML
  - Review: All template files and helper functions
  - Impact: More consistent visual design

---

### Task Completion Workflow

When completing tasks:

1. Create feature branch: `git checkout -b task/sorting-helpers`
2. Implement changes with tests
3. Bump version in `/config.json` (PATCH for fixes, MINOR for features)
4. Run validation: `python -m py_compile <changed_files>`
5. Commit with format from `CLAUDE.md`
6. Push and verify in Home Assistant addon

### Estimated Impact

- **Lines of code reduced**: ~300+ (duplicate sorting + duplicate JS)
- **Bugs fixed**: 2 (format string errors)
- **Consistency improvements**: 18+ sorting implementations unified
- **Test coverage**: New unit and integration tests
- **Maintainability**: Significantly improved

---

## Contributing

Issues and pull requests welcome! Please include:
- Home Assistant version
- Add-on version
- Relevant log excerpts
- Steps to reproduce

## License

Provided as-is for personal use.
