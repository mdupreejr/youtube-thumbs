# Route Architecture Guide

## Overview

This project now uses a unified `BaseRouteHandler` architecture to ensure consistency across all routes. This prevents template/data mismatches, provides consistent error handling, and ensures all pages have required common data.

## Benefits

1. **Prevents Template Errors**: Validates required fields before rendering
2. **Consistent Data**: All pages get ingress_path, config, etc. automatically
3. **Unified Error Handling**: Consistent error pages and logging
4. **Type Safety**: Documents and validates data contracts
5. **DRY Principle**: No duplicate code across route handlers

## Architecture Components

### 1. BaseRouteHandler (`helpers/base_route_handler.py`)

The foundation class that all route handlers inherit from:

```python
from helpers.base_route_handler import BaseRouteHandler

class YourRouteHandler(BaseRouteHandler):
    def __init__(self, database, ha_api=None, yt_api=None):
        super().__init__(db=database, ha_api=ha_api, yt_api=yt_api)

    def your_route(self):
        # Your route logic here
        return self.render_page('template.html', data=data)
```

### 2. Key Methods

#### `render_page(template_name, validate=True, **data)`
- Automatically adds common data (ingress_path, config)
- Validates template requirements
- Handles errors gracefully

#### `ensure_dict_fields(dict, required_fields)`
- Ensures dictionary has all required fields with defaults
- Prevents AttributeError in templates

#### `handle_error(error, context)`
- Consistent error logging
- Returns appropriate error response (HTML or JSON)

#### `render_json(data, status_code)`
- Consistent JSON response structure
- Includes meta information

### 3. Template Requirements

Document what fields your templates expect:

```python
class TemplateRequirements:
    STATS_HTML = {
        'summary': {
            'total_videos': int,
            'total_plays': int,
            'liked': int,
            'disliked': int,
            'skipped': int,
            'unrated': int,
            'like_percentage': float
        },
        'current_tab': str,
        'ingress_path': str
    }
```

## Migration Guide

### Step 1: Create Your Handler Class

```python
from helpers.base_route_handler import BaseRouteHandler

class DataRouteHandler(BaseRouteHandler):
    def __init__(self, database):
        super().__init__(db=database)
```

### Step 2: Convert Route Functions to Methods

Before:
```python
@bp.route('/data')
def data_viewer():
    ingress_path = g.ingress_path
    # ... logic ...
    return render_template('data.html', ingress_path=ingress_path, data=data)
```

After:
```python
class DataRouteHandler(BaseRouteHandler):
    def data_viewer(self):
        # ... logic ...
        return self.render_page('data.html', data=data)
        # ingress_path added automatically!
```

### Step 3: Use Field Validation

```python
def stats_overview(self):
    summary = self.db.get_stats_summary()

    # Ensure all required fields exist
    self.ensure_dict_fields(summary, {
        'total_videos': 0,
        'total_plays': 0,
        'liked': 0,
        'disliked': 0,
        'like_percentage': 0  # Prevents AttributeError
    })

    return self.render_page('stats.html', summary=summary)
```

### Step 4: Initialize and Wire Routes

```python
# Global handler
_handler = None

def init_routes(database):
    global _handler
    _handler = DataRouteHandler(database)

# Route definitions
@bp.route('/data')
def data_viewer():
    return _handler.data_viewer()
```

## Common Patterns

### 1. Tab-Based Pages

```python
def dashboard(self):
    tab = request.args.get('tab', 'overview')

    if tab == 'overview':
        return self._render_overview()
    elif tab == 'stats':
        return self._render_stats()
    else:
        # Invalid tab
        return self._render_overview()
```

### 2. Paginated Lists

```python
def list_items(self):
    page = validate_page_param(request.args.get('page', '1'))
    items, total = self.db.get_items(page=page, per_page=50)

    # Calculate pagination
    total_pages = (total + 49) // 50

    return self.render_page('list.html',
        items=items,
        page=page,
        total_pages=total_pages
    )
```

### 3. Form Handling

```python
def handle_form(self):
    if request.method == 'POST':
        try:
            # Process form
            result = self.process_form(request.form)
            return self.render_json({'success': True, 'result': result})
        except ValidationError as e:
            return self.handle_error(e, "processing form")

    return self.render_page('form.html')
```

## Error Handling

### Automatic Error Pages

Errors are automatically caught and displayed consistently:

```python
def risky_operation(self):
    try:
        result = self.db.dangerous_query()
        return self.render_page('result.html', result=result)
    except Exception as e:
        # Automatic error page with logging
        return self.handle_error(e, "performing risky operation")
```

### Custom Error Pages

```python
def not_found(self):
    return self.render_error_page(
        error_message="Page not found",
        status_code=404
    )
```

## Testing

### Validate Template Data

```python
from helpers.base_route_handler import TemplateRequirements

def test_stats_data():
    data = handler._prepare_stats_data()
    errors = TemplateRequirements.validate_data('stats.html', data)
    assert not errors, f"Missing fields: {errors}"
```

## Checklist for New Routes

- [ ] Create handler class inheriting from BaseRouteHandler
- [ ] Initialize with required dependencies (db, apis, etc.)
- [ ] Use `self.render_page()` instead of `render_template()`
- [ ] Use `self.ensure_dict_fields()` for data validation
- [ ] Document template requirements in TemplateRequirements
- [ ] Use `self.handle_error()` for error handling
- [ ] Test that all required fields are present

## Benefits Over Old System

| Old System | New System |
|------------|------------|
| Manual ingress_path passing | Automatic common data |
| No field validation | Template requirements checked |
| Inconsistent error handling | Unified error pages |
| Duplicate code across routes | DRY with base class |
| Template/data mismatches | Validated contracts |
| Hard to maintain | Clear patterns |

## Example: Complete Route Handler

```python
from helpers.base_route_handler import BaseRouteHandler

class VideoRouteHandler(BaseRouteHandler):
    """Handler for video-related routes."""

    def __init__(self, database, youtube_api):
        super().__init__(db=database, yt_api=youtube_api)

    def video_list(self):
        """List all videos with pagination."""
        try:
            page = int(request.args.get('page', 1))
            videos, total = self.db.get_videos(page=page)

            # Ensure each video has required fields
            for video in videos:
                self.ensure_dict_fields(video, {
                    'id': None,
                    'title': 'Unknown',
                    'artist': 'Unknown',
                    'rating': None,
                    'play_count': 0
                })

            return self.render_page('videos.html',
                videos=videos,
                page=page,
                total_pages=(total + 49) // 50
            )
        except Exception as e:
            return self.handle_error(e, "loading videos")

    def video_detail(self, video_id):
        """Show video details."""
        try:
            video = self.db.get_video(video_id)
            if not video:
                return self.render_error_page("Video not found", status_code=404)

            return self.render_page('video_detail.html', video=video)
        except Exception as e:
            return self.handle_error(e, f"loading video {video_id}")
```

## Gradual Migration

You don't need to convert everything at once:

1. New routes should use BaseRouteHandler
2. Convert existing routes when they need fixes
3. High-traffic routes should be converted first
4. Leave working routes until convenient

The system is designed to work alongside existing routes during migration.