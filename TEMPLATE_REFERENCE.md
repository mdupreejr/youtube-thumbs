# Quick Reference: Routes and Templates

## Summary Table

| Page | Route | Handler File | Function | Template | Builder | Status |
|------|-------|--------------|----------|----------|---------|--------|
| **Bulk Rating** | `/?tab=rating` | app.py | `index()` L506 | `index_server.html` | - | ✓ Custom |
| **Database** | `/data` | data_viewer_routes.py | `data_viewer()` L299 | `table_viewer.html` | DataViewerPageBuilder | ✓ Standard |
| **Rated Songs** | `/logs?tab=rated` | logs_routes.py | `logs_viewer()` L892 | `table_viewer.html` | LogsPageBuilder | ✓ Standard |
| **Matches** | `/logs?tab=matches` | logs_routes.py | `logs_viewer()` L892 | `table_viewer.html` | LogsPageBuilder | ✓ Standard |
| **Recent** | `/logs?tab=recent` | logs_routes.py | `logs_viewer()` L892 | `table_viewer.html` | LogsPageBuilder | ✓ Standard |
| **Errors** | `/logs?tab=errors` | logs_routes.py | `logs_viewer()` L892 | `table_viewer.html` | LogsPageBuilder | ✓ Standard |
| **API Calls** | `/logs/api-calls` | logs_routes.py | `api_calls_log()` L42 | `table_viewer.html` | ApiCallsPageBuilder | ✓ Standard |
| **Queue (Pending)** | `/logs/pending-ratings?tab=pending` | logs_routes.py | `pending_ratings_log()` L227 | `logs_queue.html` | - | ⚠️ Different |
| **Queue (History)** | `/logs/pending-ratings?tab=history` | logs_routes.py | `pending_ratings_log()` L227 | `logs_queue.html` | - | ⚠️ Different |
| **Queue (Errors)** | `/logs/pending-ratings?tab=errors` | logs_routes.py | `pending_ratings_log()` L227 | `logs_queue.html` | - | ⚠️ Different |
| **Queue (Stats)** | `/logs/pending-ratings?tab=statistics` | logs_routes.py | `pending_ratings_log()` L227 | `logs_queue.html` | - | ⚠️ Different |
| **Stats Overview** | `/stats` | stats_routes.py | `stats_page()` L37 | `stats.html` | - | ✓ Intentional |
| **Stats Analytics** | `/stats/analytics` | stats_routes.py | `stats_analytics_page()` L159 | `stats.html` | - | ✓ Intentional |
| **Stats API** | `/stats/api` | stats_routes.py | `stats_api_page()` L248 | `stats.html` | - | ✓ Intentional |
| **Stats Categories** | `/stats/categories` | stats_routes.py | `stats_categories_page()` L290 | `stats.html` | - | ✓ Intentional |
| **Stats Discovery** | `/stats/discovery` | stats_routes.py | `stats_discovery_page()` L331 | `stats.html` | - | ✓ Intentional |
| **Stats Liked** | `/stats/liked` | stats_routes.py | `stats_liked_page()` L374 | `table_viewer.html` | StatsPageBuilder | ✓ Standard |
| **Stats Disliked** | `/stats/disliked` | stats_routes.py | `stats_disliked_page()` L444 | `table_viewer.html` | StatsPageBuilder | ✓ Standard |
| **Queue Item Detail** | `/logs/pending-ratings/item/<id>` | logs_routes.py | `queue_item_detail_page()` L435 | `queue_item_detail.html` | - | ✓ Detail |
| **Database Admin** | `/db-admin` | data_viewer_routes.py | `database_admin_wrapper()` L393 | `database_admin.html` | - | ✓ Wrapper |

---

## Template Distribution

### table_viewer.html (STANDARD - 8 pages)
- Database
- Rated Songs
- Matches  
- Recent
- Errors
- API Calls
- Stats Liked Videos
- Stats Disliked Videos

### index_server.html (CUSTOM - 1 page)
- Bulk Rating

### logs_queue.html (SPECIALIZED - 4 variants)
- Queue Pending
- Queue History
- Queue Errors
- Queue Statistics

### stats.html (ANALYTICS - 5 pages)
- Stats Overview
- Stats Analytics
- Stats API
- Stats Categories
- Stats Discovery

### Specialty Templates
- queue_item_detail.html - Queue item detail drill-down
- database_admin.html - Wrapper for sqlite_web admin
- error.html - Error pages (referenced but not detailed here)

---

## Key Findings

### Inconsistencies
1. **Queue Pages** - Uses `logs_queue.html` instead of `table_viewer.html`
   - Affects: Pending, History, Errors, and Statistics tabs at `/logs/pending-ratings`
   - Impact: Visual consistency with other table pages
   - Recommendation: Refactor to use `table_viewer.html` with multi-tab support

### Intentional Differences
1. **Bulk Rating** - Uses `index_server.html`
   - Reason: Form-based interface, not a data table
   
2. **Stats Pages** - Use `stats.html`
   - Reason: Complex analytics dashboards with charts, not suitable for table_viewer

### Standard Pattern
- Most data viewing pages follow the `table_viewer.html` + PageBuilder pattern
- Provides consistent UI/UX across the application
- Enables filtering, sorting, pagination, and column management

