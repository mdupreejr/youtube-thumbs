# YouTube Thumbs Rating - Routes and Templates Summary

## Overview
This document maps all major pages in the YouTube Thumbs application to their route handlers and templates, identifying inconsistencies in template usage.

---

## 1. BULK RATING PAGE
**Purpose:** Server-side rendered bulk rating interface for rating multiple unrated videos

- **Route:** `GET /` with query parameter `tab=rating`
- **Route Handler File:** `/home/user/youtube-thumbs/app.py`
- **Route Handler Function:** `index()` (lines 506-589)
- **Template Used:** `index_server.html` (line 583)
- **Database Query:** `db.get_unrated_videos(page, limit=50)` (line 556)

### Details:
- This is the ONLY page that uses `index_server.html` template
- Has custom HTML/CSS for rendering unrated songs list
- Integrates rating buttons and form submission
- Includes connection tests on the "tests" tab
- Uses direct form submissions to `/rate-song` endpoint

---

## 2. DATABASE PAGE
**Purpose:** View and browse the video_ratings database table with column selection and sorting

- **Route:** `GET /data`
- **Route Handler File:** `/home/user/youtube-thumbs/routes/data_viewer_routes.py`
- **Route Handler Function:** `data_viewer()` (lines 299-390)
- **Template Used:** `table_viewer.html` (line 378)
- **Builder Pattern:** Uses `DataViewerPageBuilder` (line 319)
- **Database Query:** `_build_data_query()` (lines 159-249)

### Details:
- Features: Column selection, sorting, resizing
- Uses the standard `table_viewer.html` template
- Provides access to all video_ratings columns with SQL injection protection
- Includes column validation and sanitization

---

## 3. RATED SONGS PAGE
**Purpose:** Show a paginated list of songs that have been rated (liked or disliked)

- **Route:** `GET /logs` with query parameter `tab=rated`
- **Route Handler File:** `/home/user/youtube-thumbs/routes/logs_routes.py`
- **Route Handler Function:** `logs_viewer()` (lines 892-941)
- **Sub-builder Function:** `_create_rated_songs_page()` (lines 948-1043)
- **Template Used:** `table_viewer.html` (line 928)
- **Builder Pattern:** Uses `LogsPageBuilder` (line 956)
- **Database Query:** `_db.get_rated_songs()` (line 977)

### Details:
- Features: Time period filter, rating type filter (like/dislike)
- Columns: Time, Song, Artist, Rating, Plays, Video ID
- Shows relative time (e.g., "2 hours ago")
- Rating displayed as badges (👍 Like, 👎 Dislike)
- Uses the standard `table_viewer.html` template

---

## 4. MATCHES PAGE
**Purpose:** Show YouTube search match history - HA song titles matched to YouTube videos

- **Route:** `GET /logs` with query parameter `tab=matches`
- **Route Handler File:** `/home/user/youtube-thumbs/routes/logs_routes.py`
- **Route Handler Function:** `logs_viewer()` (lines 892-941)
- **Sub-builder Function:** `_create_matches_page()` (lines 1046-1153)
- **Template Used:** `table_viewer.html` (line 928)
- **Builder Pattern:** Uses `LogsPageBuilder` (line 1049)
- **Database Query:** `_db.get_match_history()` (line 1064)

### Details:
- Features: Time period filter
- Columns: Time, HA Song, YouTube Match, Duration, Plays
- Shows side-by-side comparison of HA metadata vs YouTube metadata
- Duration match quality indicator (green for good ±2s, amber for fair)
- Uses the standard `table_viewer.html` template

---

## 5. RECENT PAGE
**Purpose:** Show recently added videos to the database

- **Route:** `GET /logs` with query parameter `tab=recent`
- **Route Handler File:** `/home/user/youtube-thumbs/routes/logs_routes.py`
- **Route Handler Function:** `logs_viewer()` (lines 892-941)
- **Sub-builder Function:** `_create_recent_page()` (lines 1269-1325)
- **Template Used:** `table_viewer.html` (line 928)
- **Builder Pattern:** Uses `LogsPageBuilder` (line 1272)
- **Database Query:** `_db.get_recently_added(limit=25)` (line 1276)

### Details:
- Features: No filters
- Columns: Date Added, Title, Artist, Channel, Rating, Plays, Link
- Shows 25 most recently added videos
- Links directly to YouTube for each video
- Uses the standard `table_viewer.html` template

---

## 6. ERRORS PAGE
**Purpose:** Display application error logs from the error log file

- **Route:** `GET /logs` with query parameter `tab=errors`
- **Route Handler File:** `/home/user/youtube-thumbs/routes/logs_routes.py`
- **Route Handler Function:** `logs_viewer()` (lines 892-941)
- **Sub-builder Function:** `_create_errors_page()` (lines 1156-1266)
- **Template Used:** `table_viewer.html` (line 928)
- **Builder Pattern:** Uses `LogsPageBuilder` (line 1164)
- **Data Source:** Parses `/config/youtube_thumbs/errors.log` (line 628 in `parse_error_log()`)

### Details:
- Features: Time period filter, log level filter (ERROR, WARNING, INFO)
- Columns: Time, Level, Message
- Messages can be expanded to show full text (with "Show more" button)
- Level displayed as color-coded badges
- Uses the standard `table_viewer.html` template

---

## 7. API CALLS PAGE
**Purpose:** Display detailed YouTube API call logs with quota usage tracking

- **Route:** `GET /logs/api-calls`
- **Route Handler File:** `/home/user/youtube-thumbs/routes/logs_routes.py`
- **Route Handler Function:** `api_calls_log()` (lines 42-224)
- **Template Used:** `table_viewer.html` (line 212)
- **Builder Pattern:** Uses `ApiCallsPageBuilder` (line 72)
- **Database Query:** `_db.get_api_call_log()` (line 61)

### Details:
- Features: API method filter, success/failure filter, summary statistics
- Columns: Time, Method, Operation, Query, Quota, Status, Results, Context
- Shows 24-hour quota usage summary and breakdown by method/operation
- Method badges: 🔍 search, 📹 videos.list
- Quota costs highlighted in red for expensive calls (≥100)
- Uses the standard `table_viewer.html` template

---

## 8. QUEUE/PENDING RATINGS PAGE
**Purpose:** Comprehensive queue viewer with multiple tabs for pending, history, errors, and statistics

- **Route:** `GET /logs/pending-ratings` (with optional `tab` parameter)
- **Route Handler File:** `/home/user/youtube-thumbs/routes/logs_routes.py`
- **Route Handler Function:** `pending_ratings_log()` (lines 227-319)
- **Template Used:** `logs_queue.html` (line 309) **← DIFFERENT TEMPLATE**
- **Database Queries:**
  - Pending items: `_db.list_pending_queue_items()` (line 288)
  - History: `_db.list_queue_history()` (line 294)
  - Errors: `_db.list_queue_failed()` (line 299)
  - Statistics: `_db.get_queue_statistics()` (line 304)

### Queue Sub-tabs:

#### 8a. Pending Tab (tab=pending)
- Shows items awaiting processing
- Includes both search and rating queue items
- Sorted by requested_at (newest first)

#### 8b. History Tab (tab=history)
- Shows completed and failed items from recent history
- Limit: 200 items

#### 8c. Errors Tab (tab=errors)
- Shows only failed queue items
- Displays error messages and retry information

#### 8d. Statistics Tab (tab=statistics)
- Queue health metrics
- Recent activity timeline
- Performance metrics (24-hour window)

### Details:
- **INCONSISTENCY ALERT:** Uses `logs_queue.html` instead of `table_viewer.html`
- Queue items support expanding to see full details (modal dialog)
- Can drill down to individual queue item via `/logs/pending-ratings/item/<id>`
- Queue item detail page uses `queue_item_detail.html` template

---

## Additional Pages

### Queue Item Detail Page
- **Route:** `GET /logs/pending-ratings/item/<item_id>`
- **Route Handler:** `queue_item_detail_page()` (lines 435-607)
- **Template Used:** `queue_item_detail.html`
- **Purpose:** Full-page detailed view of a single queue item with API response debugging

### Database Admin Page
- **Route:** `GET /db-admin` (proxied to `/database`)
- **Route Handler:** `database_admin_wrapper()` (lines 393-413)
- **Template Used:** `database_admin.html`
- **Purpose:** Embeds sqlite_web admin interface with YouTube Thumbs navbar

### Stats Pages
- **Route:** `GET /stats` and sub-routes (`/stats/analytics`, `/stats/api`, `/stats/categories`, `/stats/discovery`, `/stats/liked`, `/stats/disliked`)
- **Route Handler File:** `/home/user/youtube-thumbs/routes/stats_routes.py`
- **Template Used:** `stats.html`
- **Purpose:** Various statistics and analytics views

---

## CONSISTENCY ANALYSIS

### Table Viewer Template Usage (STANDARD)
The following pages correctly use `table_viewer.html`:
1. ✓ Database Page (`/data`)
2. ✓ Rated Songs (`/logs?tab=rated`)
3. ✓ Matches (`/logs?tab=matches`)
4. ✓ Recent (`/logs?tab=recent`)
5. ✓ Errors (`/logs?tab=errors`)
6. ✓ API Calls (`/logs/api-calls`)
7. ✓ Liked Videos (`/stats/liked`)
8. ✓ Disliked Videos (`/stats/disliked`)

### INCONSISTENCIES FOUND

#### 1. Bulk Rating Page - USES DIFFERENT TEMPLATE
- **Page:** Bulk Rating (`/?tab=rating`)
- **Current Template:** `index_server.html`
- **Expected Template:** `index_server.html` (custom interface with form submission)
- **Status:** ✓ INTENTIONAL (custom interface, not a data table)
- **Reason:** Requires interactive form with file-style input, not a data table viewer

#### 2. Queue Pages - USES DIFFERENT TEMPLATE
- **Page:** Pending Ratings (`/logs/pending-ratings`)
- **Current Template:** `logs_queue.html`
- **Expected Template:** `table_viewer.html`
- **Status:** ⚠️ INCONSISTENCY FOUND
- **Issue:** Uses dedicated `logs_queue.html` instead of unified `table_viewer.html`
- **Reason for Difference:** Requires multi-tab interface with queue-specific functionality not in table_viewer
- **Recommendation:** Could be refactored to use `table_viewer.html` with multi-tab support

#### 3. Stats Pages - USE DIFFERENT TEMPLATE
- **Pages:** `/stats`, `/stats/analytics`, etc.
- **Current Template:** `stats.html`
- **Expected Template:** `table_viewer.html`
- **Status:** ✓ INTENTIONAL (custom analytics interface)
- **Reason:** Requires complex data visualization, charts, and multi-tab layout beyond table_viewer scope

#### 4. Database Admin - CUSTOM TEMPLATE
- **Page:** `/db-admin`
- **Current Template:** `database_admin.html`
- **Expected Template:** N/A (wrapper around external tool)
- **Status:** ✓ INTENTIONAL (embeds sqlite_web)

---

## table_viewer.html Template Overview

The `table_viewer.html` is the STANDARD template for data display pages in the application.

### Key Features:
- Responsive table layout with enhanced features
- Column sorting and resizing
- Column visibility toggle
- Pagination with page numbers
- Filter support (multiple filter dropdowns)
- Summary statistics panels
- Empty state messaging
- Modal dialogs for detailed views
- Clickable rows with event handling

### Key Components:
1. **Header Navigation** - Main tab navigation
2. **Filters** - Dynamic filter form (optional)
3. **Summary Statistics** - Stats cards with breakdowns (optional)
4. **Data Table** - Enhanced table with sorting/resizing
5. **Pagination** - Page navigation controls
6. **Modal** - Detail view modal dialog

### Template Variables:
```jinja2
{
    'page_config': {
        'title': str,
        'title_suffix': str,
        'nav_active': str,  # Active nav item
        'show_title': bool,
        'filters': [Filter],
        'empty_state': {icon, title, message},
        'storage_key': str,
        'enable_sorting': bool,
        'enable_resizing': bool,
        'enable_column_toggle': bool,
        'row_click_handler': str,
        'modal_api_url': str,
        'modal_title': str,
        'current_url': str,
        'back_link': str,
        'back_text': str
    },
    'table_data': {
        'columns': [TableColumn],
        'rows': [TableRow]
    },
    'pagination': {
        'current_page': int,
        'total_pages': int,
        'page_numbers': [int],
        'prev_url': str,
        'next_url': str,
        'page_url_template': str
    },
    'status_message': str,
    'summary_stats': {...},
    'ingress_path': str
}
```

---

## Page Builder Pattern Usage

All table_viewer pages use the PageBuilder pattern for consistency:

### Builders Used:
1. **DataViewerPageBuilder** - For `/data` page
2. **LogsPageBuilder** - For `/logs/*` pages
3. **StatsPageBuilder** - For `/stats/*` pages
4. **ApiCallsPageBuilder** - For `/logs/api-calls` page

### Builder Methods:
- `set_title()` - Set page title
- `add_filter()` - Add filter dropdown
- `set_table()` - Set table columns and rows
- `set_pagination()` - Configure pagination
- `set_empty_state()` - Customize empty state message
- `set_status_message()` - Add status text below title
- `build()` - Generate final page_config, table_data, pagination

---

## Recommendations for Consistency

### High Priority:
1. **Queue Pages** - Consider refactoring `/logs/pending-ratings` to use `table_viewer.html` with multi-tab support
   - Currently uses separate `logs_queue.html`
   - Could improve consistency across the application
   - Would require adding multi-tab rendering to table_viewer.html

### Medium Priority:
2. **Template Documentation** - Document which pages should use which templates
3. **Builder Consolidation** - Consider merging PageBuilder classes if possible

### Low Priority:
4. **Stats Pages** - Keep using `stats.html` for analytics (intentional complexity)
5. **Bulk Rating** - Keep using `index_server.html` for form-based interface

