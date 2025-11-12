# YouTube Thumbs - Code Organization

Documentation for developers working on the YouTube Thumbs Rating addon codebase.

## Table of Contents

- [Project Structure](#project-structure)
- [Route Architecture](#route-architecture)
- [Helper Functions](#helper-functions)
- [Template System](#template-system)
- [Database Operations](#database-operations)
- [Common Patterns](#common-patterns)

---

## Project Structure

```
youtube-thumbs/
├── app.py                      # Main Flask application
├── queue_worker.py             # Background queue processor
├── song_tracker.py             # AppleTV media monitoring
├── youtube_api.py              # YouTube API wrapper
├── homeassistant_api.py        # Home Assistant API wrapper
│
├── routes/                     # Flask route blueprints
│   ├── logs_routes.py          # Logs viewer (/logs)
│   ├── stats_routes.py         # Statistics pages (/stats)
│   ├── rating_routes.py        # Rating operations (/rate)
│   ├── data_viewer_routes.py   # Database viewer (/data)
│   ├── system_routes.py        # System utilities (/system)
│   └── data_api.py             # Data export API (/data/api)
│
├── database/                   # Database operations (modularized)
│   ├── __init__.py             # Main Database class
│   ├── connection.py           # Connection management
│   ├── queue_operations.py     # Queue table operations
│   ├── video_operations.py     # Video CRUD operations
│   ├── stats_operations.py     # Statistics queries
│   ├── logs_operations.py      # Log queries
│   ├── api_usage_operations.py # API usage tracking
│   ├── search_cache_operations.py # Search cache
│   └── stats_cache_operations.py  # Stats cache
│
├── helpers/                    # Utility functions
│   ├── template_helpers.py     # Template formatting & display utilities
│   ├── page_builder.py         # Builder pattern for page construction
│   ├── video_helpers.py        # Video metadata handling
│   ├── time_helpers.py         # Time/date formatting
│   ├── validation_helpers.py   # Input validation
│   ├── pagination_helpers.py   # Pagination utilities
│   ├── request_helpers.py      # Request handling utilities
│   ├── response_helpers.py     # Response formatting
│   ├── cache_helpers.py        # Cache lookup utilities
│   ├── api_helpers.py          # API utility functions
│   └── search_helpers.py       # Video search utilities
│
├── templates/                  # Jinja2 HTML templates
│   ├── table_viewer.html       # Unified table template (used by most pages)
│   ├── logs_queue.html         # Queue monitoring page
│   ├── stats_*.html            # Statistics page templates
│   ├── index_server.html       # Main dashboard
│   └── database_admin.html     # Database admin interface
│
└── static/                     # Static assets
    ├── css/
    │   ├── common.css          # Shared styles
    │   ├── stats.css           # Stats page styles
    │   └── stats_visualizations.css # Chart styles
    └── js/
        └── table-utils.js      # Table interaction utilities
```

---

## Route Architecture

### Blueprint Organization

All routes are organized into separate Flask blueprints for modularity:

**Initialization Pattern** (used in `app.py`):
```python
from routes.logs_routes import bp as logs_bp, init_logs_routes

# Initialize with dependencies
init_logs_routes(database)

# Register blueprint
app.register_blueprint(logs_bp)
```

### Route Blueprints

| Blueprint | Prefix | Description | File |
|-----------|--------|-------------|------|
| `logs_bp` | `/logs` | Logs viewer, API calls, queue monitor | `routes/logs_routes.py` |
| `stats_bp` | `/stats` | Statistics, analytics, categories | `routes/stats_routes.py` |
| `rating_bp` | `/rate` | Rating submission endpoints | `routes/rating_routes.py` |
| `data_viewer_bp` | `/data` | Database viewer, admin | `routes/data_viewer_routes.py` |
| `system_bp` | `/system` | System utilities, health checks | `routes/system_routes.py` |
| `data_api_bp` | `/data/api` | Data export API | `routes/data_api.py` |

---

## Helper Functions

### Template Helpers (`helpers/template_helpers.py`)

Centralized formatting and display utilities for consistent UI rendering.

#### Core Display Functions

##### `format_song_display(title: str, artist: str) -> str`

Formats song title and artist for consistent two-line display.

**Usage:**
```python
from helpers.template import format_song_display

# Creates formatted HTML
html = format_song_display("Bohemian Rhapsody", "Queen")
# Returns: '<strong>Bohemian Rhapsody</strong><br><span style="font-size: 0.85em; color: #64748b;">Queen</span>'
```

**Features:**
- Title displayed in bold
- Artist shown below in smaller, subdued font
- Handles missing/empty values (defaults to 'Unknown')
- XSS-safe (escapes HTML entities)

**Where Used:**
- Logs pages (rated songs, matches)
- Stats pages (liked/disliked videos)
- Data viewer tables

---

##### `format_status_badge(success: bool, success_text='✓ Success', failure_text='✗ Failed') -> str`

Formats success/failure status badges with consistent styling.

**Usage:**
```python
from helpers.template import format_status_badge

# Success badge (green)
badge = format_status_badge(True)
# Returns: '<span class="badge badge-success">✓ Success</span>'

# Failure badge (red)
badge = format_status_badge(False)
# Returns: '<span class="badge badge-error">✗ Failed</span>'

# Custom text
badge = format_status_badge(True, success_text='Completed', failure_text='Failed')
```

**Features:**
- Automatic color coding (success=green, failure=red)
- Customizable text for different contexts
- Consistent badge styling across application
- XSS-safe

**Where Used:**
- API call logs (success/failure status)
- Queue monitoring (operation status)
- Any boolean status display

---

##### `format_badge(text: str, badge_type: str = 'default') -> str`

Low-level badge formatter for custom badge types.

**Badge Types:**
- `'success'` - Green badge
- `'error'` - Red badge
- `'warning'` - Yellow badge
- `'info'` - Blue badge
- `'like'` - Thumbs up styling
- `'dislike'` - Thumbs down styling
- `'count'` - Count badge styling
- `'default'` - Neutral gray badge

**Usage:**
```python
from helpers.template import format_badge

format_badge('⏳ Pending', 'warning')
format_badge('🔍 search', 'info')
format_badge('❌ Error', 'error')
```

---

##### `format_youtube_link(video_id: str, title: str, icon: bool = True) -> str`

Creates properly formatted YouTube video links.

**Usage:**
```python
from helpers.template import format_youtube_link

# With icon
link = format_youtube_link('dQw4w9WgXcQ', 'Never Gonna Give You Up', icon=True)

# Without icon
link = format_youtube_link('dQw4w9WgXcQ', 'Song Title', icon=False)
```

---

##### `truncate_text(text: str, max_length: int = 80, suffix: str = '...') -> str`

Truncates long text with optional suffix.

**Usage:**
```python
from helpers.template import truncate_text

short = truncate_text("Very long error message...", max_length=50)
```

---

##### `format_time_ago(timestamp: str) -> str`

Formats timestamps as relative time (e.g., "2 hours ago").

**Usage:**
```python
from helpers.template import format_time_ago

relative = format_time_ago("2025-11-10T15:30:00")
# Returns: "2 hours ago" (relative to current time)
```

---

#### Data Structure Classes

##### `PageConfig`

Configuration object for page metadata (title, tabs, filters).

**Usage:**
```python
from helpers.template import PageConfig

config = PageConfig(title="Logs Viewer", page_type="logs")
config.add_tab("rated", "Rated Songs", "/logs?tab=rated", selected=True)
config.add_filter("period", "Time Period", filter_options)
```

---

##### `TableData`, `TableColumn`, `TableRow`, `TableCell`

Structured data classes for the unified table viewer template.

**Usage:**
```python
from helpers.template import TableData, TableColumn, TableRow, TableCell

# Define columns
columns = [
    TableColumn('song', 'Song', width='50%'),
    TableColumn('artist', 'Artist'),
    TableColumn('plays', 'Plays')
]

# Create rows
rows = []
for video in videos:
    cells = [
        TableCell('Song Title', '<strong>Song Title</strong>'),
        TableCell('Artist Name', style='color: #64748b;'),
        TableCell(42)
    ]
    rows.append(TableRow(cells))

# Create table
table = TableData(columns, rows)
```

---

### Page Builder Pattern (`helpers/page_builder.py`)

Builder classes for constructing pages with consistent structure.

#### Available Builders

- **`LogsPageBuilder`** - For logs pages (rated, matches, errors, recent)
- **`StatsPageBuilder`** - For statistics pages (liked/disliked videos)
- **`DataViewerPageBuilder`** - For database viewer pages
- **`ApiCallsPageBuilder`** - For API calls log pages

**Example:**
```python
from helpers.page_builder import LogsPageBuilder

builder = LogsPageBuilder('rated', ingress_path)
builder.add_filter('rating', 'Rating Type', filter_options)
builder.set_table(columns, rows)
builder.set_pagination(page, total_pages, page_numbers)
builder.set_status_message(f"Showing {count} items")

page_config, table_data, pagination, status_message = builder.build()
```

---

### Ingress Path Utility (Flask `g` Object)

**New in v4.5.0**: Centralized ingress path handling eliminates duplication across routes.

#### How It Works

**Setup** (`app.py`):
```python
from flask import g

@app.before_request
def inject_ingress_path():
    """
    Inject ingress_path into Flask's g object for all requests.
    This centralizes the ingress path retrieval.
    """
    g.ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
```

#### Usage in Routes

**Before (❌ Old Pattern - Duplicated 50+ times):**
```python
@bp.route('/logs')
def logs_viewer():
    ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')
    # ... rest of function
```

**After (✅ New Pattern - Use `g.ingress_path`):**
```python
from flask import g

@bp.route('/logs')
def logs_viewer():
    ingress_path = g.ingress_path
    # ... rest of function
```

#### Benefits

- **No Duplication**: Single source of truth for ingress path
- **Consistency**: Same retrieval method everywhere
- **Maintainability**: Change once to update everywhere
- **Cleaner Code**: Reduces boilerplate in every route

#### Migration Status

All route files have been migrated:
- ✅ `routes/logs_routes.py`
- ✅ `routes/stats_routes.py`
- ✅ `routes/data_viewer_routes.py`
- ✅ `routes/rating_routes.py`
- ✅ `app.py`

---

### Video Helpers (`helpers/video_helpers.py`)

Video metadata extraction and formatting.

**Key Functions:**
- `get_video_title(video)` - Extract title from video dict
- `get_video_artist(video)` - Extract artist from video dict
- `format_videos_for_display(videos)` - Format video list for templates
- `is_youtube_content(app_name)` - Check if content is from YouTube

---

### Time Helpers (`helpers/time_helpers.py`)

Time and date formatting utilities.

**Key Functions:**
- `format_relative_time(timestamp)` - Convert to "2 hours ago" format
- `format_duration(seconds)` - Convert seconds to "mm:ss" format
- `format_absolute_timestamp(timestamp)` - Format as readable date/time
- `parse_timestamp(timestamp)` - Parse various timestamp formats

---

### Validation Helpers (`helpers/validation_helpers.py`)

Input validation and sanitization.

**Key Functions:**
- `validate_page_param(request.args)` - Validate page number parameter
- `validate_youtube_video_id(video_id)` - Validate YouTube video ID format
- `sanitize_filename(filename)` - Sanitize filenames for security

---

## Template System

### Unified Table Viewer (`templates/table_viewer.html`)

**New in v4.4.0**: Replaces multiple template files with a single unified template.

**Replaced Templates** (removed in v4.5.0):
- ❌ `logs_viewer.html` (623 lines) - Now uses `table_viewer.html`
- ❌ `data_viewer.html` (340 lines) - Now uses `table_viewer.html`
- ❌ `logs_api_calls.html` (232 lines) - Now uses `table_viewer.html`

**Template Structure:**
```html
{% extends "base_template" %}

<!-- Page header with title and tabs -->
<!-- Filters section -->
<!-- Table with sortable columns -->
<!-- Pagination controls -->
<!-- Empty state message -->
```

**Usage in Routes:**
```python
return render_template(
    'table_viewer.html',
    ingress_path=g.ingress_path,
    page_config=page_config.to_dict(),
    table_data=table_data.to_dict(),
    pagination=pagination,
    status_message=status_message
)
```

---

## Database Operations

Database operations are modularized by domain in the `database/` directory.

### Database Class Architecture

**Main Class** (`database/__init__.py`):
- Coordinates all database operations
- Manages connection and locking
- Delegates to specialized mixins

**Specialized Mixins:**
- `VideoOperationsMixin` - Video CRUD operations
- `QueueOperationsMixin` - Queue management
- `StatsOperationsMixin` - Statistics queries
- `LogsOperationsMixin` - Log queries
- `ApiUsageOperationsMixin` - API usage tracking
- `SearchCacheOperationsMixin` - Search result caching
- `StatsCacheOperationsMixin` - Statistics caching

**Usage Pattern:**
```python
from database import get_database

db = get_database()

# Video operations
videos = db.get_rated_videos('like', page=1, per_page=50)

# Queue operations
db.queue_search_operation(title, artist, duration)

# Stats operations
stats = db.get_statistics_overview()
```

---

## Common Patterns

### Route Function Pattern

Standard structure for route functions:

```python
@bp.route('/example')
def example_route():
    """Route description."""
    try:
        # 1. Get ingress path from Flask g object
        ingress_path = g.ingress_path

        # 2. Validate input parameters
        page, error = validate_page_param(request.args)
        if error:
            return error

        # 3. Query database
        result = _db.get_data(page=page)

        # 4. Build page using builder pattern
        builder = LogsPageBuilder('tab_name', ingress_path)
        builder.set_table(columns, rows)
        builder.set_pagination(...)

        # 5. Build and render
        page_config, table_data, pagination, status = builder.build()

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict(),
            pagination=pagination,
            status_message=status
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        return error_response("Error message", 500)
```

### Security Patterns

**Input Validation:**
```python
# Always validate user input
page, error = validate_page_param(request.args)
if error:
    return error

# Sanitize strings
video_id = sanitize_video_id(request.args.get('video_id'))
```

**XSS Prevention:**
```python
# Use helper functions that escape HTML
html = format_song_display(title, artist)  # Automatically escapes

# Or manually escape
import html
safe_text = html.escape(user_input)
```

**SQL Injection Prevention:**
```python
# Always use parameterized queries
cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))

# Never concatenate SQL strings
# ❌ BAD: f"SELECT * FROM videos WHERE id = '{video_id}'"
```

---

## Code Style Guidelines

### Imports Organization

```python
# 1. Standard library imports
import os
import re
from datetime import datetime

# 2. Third-party imports
from flask import Blueprint, render_template, request, g

# 3. Local application imports
from logging_helper import LoggingHelper, LogType
from database import get_database
from helpers.template import format_badge

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)
```

### Function Documentation

```python
def function_name(param1: str, param2: int = 10) -> str:
    """
    Brief one-line description.

    Longer description if needed, explaining the purpose,
    behavior, and any important details.

    Args:
        param1: Description of param1
        param2: Description of param2 (default: 10)

    Returns:
        Description of return value

    Example:
        >>> function_name("test", 5)
        'result'
    """
    pass
```

### Error Handling

```python
try:
    # Risky operation
    result = operation()
except SpecificException as e:
    # Handle specific error
    logger.error(f"Specific error: {e}")
    return error_response("User-friendly message", 500)
except Exception as e:
    # Catch-all for unexpected errors
    logger.error(f"Unexpected error: {e}")
    import traceback
    logger.error(traceback.format_exc())
    return error_response("Internal error", 500)
```

---

## Recent Changes (v4.5.0)

### Code Cleanup

**Dead Code Removed:**
- Removed 6 obsolete `_handle_*_tab()` functions from `logs_routes.py` (280 lines)
- Deleted 5 unused template files (1,195 lines total)

**Duplication Eliminated:**
- Created centralized `g.ingress_path` utility (50+ instances consolidated)
- Added `format_song_display()` helper (eliminates inline HTML formatting)
- Added `format_status_badge()` helper (consolidates badge logic)

**Impact:**
- **-1,680 net lines** (~11% reduction)
- Improved maintainability
- More consistent code patterns
- Easier to update and debug

---

## Contributing Guidelines

When adding new features:

1. **Use existing helpers** - Check `helpers/` before writing custom formatting
2. **Follow patterns** - Match existing code structure and style
3. **Use `g.ingress_path`** - Never use `request.environ.get('HTTP_X_INGRESS_PATH')`
4. **Use builder pattern** - For pages with tables, use appropriate PageBuilder
5. **Document functions** - Add docstrings with examples
6. **Validate input** - Always validate and sanitize user input
7. **Handle errors** - Use try/except with proper logging
8. **Test changes** - Run syntax checks: `python3 -m py_compile file.py`

---

## Additional Resources

- **Architecture Documentation**: `ARCHITECTURE.md` - Database schema, queue system
- **Installation Guide**: `INSTALL.md` - Setup and configuration
- **Development Guide**: `CLAUDE.md` - Version management, commit format
- **Main README**: `README.md` - Project overview and features
