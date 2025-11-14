# Template Architecture - Quick Reference

## What You Have Now

```
Templates (7)
├── 6 Full Documents (each with complete <head>)
│   ├── index_server.html (31KB)
│   ├── stats.html (51KB)
│   ├── table_viewer.html (15KB)
│   ├── queue_item_detail.html (12KB)
│   ├── error.html (1KB)
│   └── database_admin.html (1.5KB)
│
└── 1 Shared Component (include, not extends)
    └── _navbar.html (1.4KB)

CSS (2 files)
├── common.css (644 lines) - ALL pages
└── stats.css (100+ lines) - ONLY stats.html

Pages with Inline Styles
├── index_server.html (140 lines)
├── queue_item_detail.html (scattered)
└── database_admin.html (24 lines)

Helper System (7 modules)
├── data_structures.py (TableColumn, TableCell, TableRow, TableData, PageConfig)
├── formatters.py (format_badge, format_time_ago, format_youtube_link, etc.)
├── filters.py (create_filter_option, create_period_filter, etc.)
├── sanitization.py (sanitize_html)
├── rendering.py (render_table_page, create_pagination_info)
├── table_helpers.py (build_video_table_rows)
└── __init__.py (re-exports all)
```

## What's Missing

```
Base Template - Each template duplicates:
├── <!DOCTYPE html>
├── <head> tags
├── <meta> tags
├── CSS links
├── <header> with logo
├── navbar include
└── closing tags

Component Includes - Only _navbar exists
Missing:
├── _header.html (header + navbar)
├── _tabs.html (unified tab navigation)
├── _metric-cards.html (unified stat cards)
├── _empty-state.html (unified empty state)
└── _pagination.html (unified pagination)

CSS Organization - Scattered styles
Current:
├── common.css (universal, good)
├── stats.css (page-specific, good)
├── index_server inline (140 lines)
├── queue_item_detail inline (scattered)
└── database_admin inline (24 lines)

Missing files:
├── index.css
├── queue-detail.css
└── database.css

Consistent Data Helpers - Only table_viewer uses them
Using PageConfig/TableData:
└── table_viewer.html (good!)

NOT using PageConfig/TableData:
├── index_server.html
└── stats.html
```

## Template Duplication Breakdown

### Every Template Has This (DUPLICATION!)
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Thumbs - ...</title>
    <link rel="stylesheet" href="{{ static_url('css/common.css') }}">
    <!-- Page-specific CSS here -->
</head>
<body>
    <div class="container">
        <header>
            <div class="header-left">
                <h1>YouTube Thumbs Rating</h1>
                {% set nav_active = '...' %}
                {% include '_navbar.html' %}
            </div>
        </header>
        <!-- PAGE CONTENT HERE -->
    </div>
</body>
</html>
```

## CSS Duplication

### stats.css has duplicate from common.css
```css
/* In common.css (line 484-514) */
.tab-navigation {
    display: flex;
    gap: 6px;
    margin-bottom: 15px;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 6px;
}

/* In stats.css (line 7-41) - DIFFERENT NAME, SAME PURPOSE */
.stats-tabs {
    display: flex;
    gap: 4px;
    padding: 8px;
    background: white;
    border-radius: 6px;
    margin-bottom: 12px;
    border: 1px solid #e2e8f0;
    overflow-x: auto;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

/* Result: Two ways to do tabs, different selectors */
```

### Metric Cards implemented 2 ways
```css
/* In stats.css */
.metrics-grid { /* Large dashboard cards */ }
.metric-card { /* 2em font, 700 weight */ }

/* In common.css */
.stat-cards-grid { /* Regular grid */ }
.stat-card { /* smaller cards */ }

/* Result: Two ways to do stat cards */
```

## UI Patterns Inconsistency

| Pattern | How 1 | How 2 | How 3 |
|---------|-------|-------|-------|
| **Tab Navigation** | index_server (inline) | stats (.stats-tabs CSS) | table_viewer (.tab-navigation CSS) |
| **Metric Cards** | stats (.metric-card) | table_viewer (.stat-card) | - |
| **Empty State** | stats.html | table_viewer.html | - |
| **Pagination** | index_server | table_viewer | - |
| **Data Building** | Direct dict | Complex Jinja | PageConfig class |

## Data Building Pattern Inconsistency

```python
# index_server.html (Direct rendering with dict)
render_template('index_server.html',
    current_tab='tests',
    ha_test={...},
    yt_test={...},
    db_test={...},
    metrics={...}
)

# stats.html (Direct rendering with complex dict)
render_template('stats.html',
    current_tab='overview',
    summary={...},
    rating_percentages={...},
    heatmap_data={...}
)

# table_viewer.html (Using helper classes) ← BETTER
render_template('table_viewer.html',
    page_config=PageConfig(...).to_dict(),
    table_data=TableData(...).to_dict(),
    pagination={...}
)
```

## Consolidation Strategy

### 1. Create Base Template (Eliminate Duplication)
```
6 templates × duplicate DOCTYPE/head/header
= 6 × ~10 lines of duplication
Solution: 1 base.html with {% block content %}
```

### 2. Merge CSS Selectors
```
.tab-navigation (common.css)
.stats-tabs (stats.css)
= 2 selectors for same purpose
Solution: 1 unified .tab-navigation
```

### 3. Standardize UI Patterns
```
Metric cards: .metric-card vs .stat-card
Solution: 1 unified .metric-card with size variants
```

### 4. Extend Helper System
```
table_viewer.html uses PageConfig (good!)
index_server.html builds dict (old way)
stats.html builds dict (old way)
Solution: Extend PageConfig to all pages
```

## Implementation Checklist

- [ ] Create /templates/base.html
- [ ] Create /templates/_header.html
- [ ] Update all 6 templates to extend base.html
- [ ] Move index_server inline CSS to /static/css/index.css
- [ ] Move database_admin inline CSS to /static/css/database.css
- [ ] Move queue_item_detail inline CSS to /static/css/queue-detail.css
- [ ] Consolidate .stats-tabs into .tab-navigation
- [ ] Consolidate .metric-card and .stat-card
- [ ] Create /helpers/template/page_config.py for all page types
- [ ] Update routes to use PageConfig instead of dict
- [ ] Create reusable component includes (_tabs.html, _metric-cards.html, etc.)
- [ ] Test all pages with new base template
- [ ] Document the new unified system

## Files to Change

| File | Changes |
|------|---------|
| `/templates/base.html` | Create new |
| `/templates/_header.html` | Create new |
| `/templates/index_server.html` | Change to extend base, remove inline CSS |
| `/templates/stats.html` | Change to extend base |
| `/templates/table_viewer.html` | Change to extend base |
| `/templates/queue_item_detail.html` | Change to extend base, remove inline CSS |
| `/templates/error.html` | Change to extend base |
| `/templates/database_admin.html` | Change to extend base, remove inline CSS |
| `/static/css/common.css` | Consolidate duplicate selectors |
| `/static/css/stats.css` | Merge into common.css or remove |
| `/static/css/index.css` | Create new |
| `/static/css/queue-detail.css` | Create new |
| `/static/css/database.css` | Create new |
| `/routes/*.py` | Update to use PageConfig for all |

## Current Status

Currently you have a **"50% unified"** system:
- Common CSS foundation (good)
- Shared navbar (good)
- Partial helper system (good for table_viewer, missing for others)
- No base template (duplication)
- Scattered inline styles (maintenance nightmare)
- Inconsistent patterns (3 ways to do tabs)

Target: **100% unified** system with:
- Base template (DRY)
- Component includes (reusable)
- Consolidated CSS (no duplicates)
- Universal helper system (all pages use PageConfig)
- Consistent patterns (1 way to do each thing)
