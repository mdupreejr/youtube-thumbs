"""
Data viewer route for browsing the video_ratings database table.
Extracted from app.py for better organization.
"""
import re
import types
import traceback
from flask import Blueprint, render_template, request, g
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)
from helpers.pagination_helpers import generate_page_numbers
from helpers.time_helpers import parse_timestamp
from helpers.validation_helpers import validate_page_param
from helpers.request_helpers import get_real_ip
from helpers.template_helpers import TableColumn, TableRow, TableCell, format_badge
from helpers.page_builder import DataViewerPageBuilder

bp = Blueprint('data_viewer', __name__)

# Global database reference (set by init function)
_db = None
_sqlite_web_available = False

def init_data_viewer_routes(database, sqlite_web_available=False):
    """Initialize data viewer routes with dependencies."""
    global _db, _sqlite_web_available
    _db = database
    _sqlite_web_available = sqlite_web_available


# ============================================================================
# DATA VIEWER CONSTANTS
# ============================================================================

_DATA_VIEWER_COLUMNS_MUTABLE = {
    'yt_video_id': 'Video ID',
    'ha_title': 'Title (HA)',
    'ha_artist': 'Artist (HA)',
    'ha_app_name': 'App Name',
    'yt_title': 'Title (YT)',
    'yt_channel': 'Channel',
    'yt_url': 'YouTube URL',
    'rating': 'Rating',
    'play_count': 'Play Count',
    'date_added': 'Date Added',
    'date_last_played': 'Last Played',
    'rating_score': 'Rating Score',
    'source': 'Source',
    'ha_duration': 'Duration (HA)',
    'yt_duration': 'Duration (YT)',
    'yt_published_at': 'Published',
    'yt_category_id': 'Category'
    # v4.0.0: Removed yt_match_pending, yt_match_attempts, pending_reason (schema fields removed)
}
DATA_VIEWER_COLUMNS = types.MappingProxyType(_DATA_VIEWER_COLUMNS_MUTABLE)

# SECURITY: Regex to validate SQL identifiers (alphanumeric and underscore only)
_SQL_IDENTIFIER_PATTERN = re.compile(r'^[a-z_][a-z0-9_]*$', re.IGNORECASE)

# Default columns to display if none selected
DEFAULT_DATA_VIEWER_COLUMNS = [
    'yt_video_id', 'ha_title', 'ha_artist',
    'rating', 'play_count', 'date_last_played'
]

# Data viewer pagination and validation constants
MAX_PAGE_NUMBER = 1_000_000  # Prevent excessive memory usage
DEFAULT_PAGE_SIZE = 50


# ============================================================================
# DATA VIEWER HELPER FUNCTIONS
# ============================================================================

def _sanitize_log_value(value: str, max_length: int = 50) -> str:
    """
    Sanitize values for logging to prevent log injection.

    Args:
        value: String value to sanitize
        max_length: Maximum length before truncation

    Returns:
        Sanitized string safe for logging
    """
    if not isinstance(value, str):
        value = str(value)

    # Remove newlines and control characters
    value = ''.join(char if char.isprintable() and char not in '\r\n' else '?' for char in value)

    # Truncate if too long
    if len(value) > max_length:
        value = value[:max_length] + '...'

    return value


def _validate_data_viewer_params(request_args):
    """
    Validate and sanitize data viewer parameters.

    Returns:
        Tuple of (page, sort_by, sort_order, selected_columns, columns_param, all_columns)
    """
    # Get query parameters with validation
    page, _ = validate_page_param(request_args)
    if not page or page > MAX_PAGE_NUMBER:
        page = 1

    sort_by = request_args.get('sort', 'date_last_played')
    sort_order = request_args.get('order', 'DESC')

    # Try to get from checkboxes first (getlist for multiple values)
    selected_columns = request_args.getlist('column')

    # If no checkboxes, try the columns parameter (for pagination links)
    if not selected_columns:
        columns_param = request_args.get('columns', ','.join(DEFAULT_DATA_VIEWER_COLUMNS))
        selected_columns = [c.strip() for c in columns_param.split(',') if c.strip()]

    # SECURITY: Validate ALL selected columns against whitelist to prevent SQL injection
    validated_columns = []
    for col in selected_columns:
        if col in DATA_VIEWER_COLUMNS:
            validated_columns.append(col)
        else:
            logger.warning(
                f"Attempted to select invalid column: "
                f"{_sanitize_log_value(col)} from {get_real_ip()}"
            )

    # Use validated columns or fallback to defaults
    if not validated_columns:
        validated_columns = DEFAULT_DATA_VIEWER_COLUMNS

    selected_columns = validated_columns

    # Create columns param for pagination links
    columns_param = ','.join(selected_columns)

    # Ensure valid sort column (SQL injection protection)
    if sort_by not in DATA_VIEWER_COLUMNS:
        logger.warning(
            f"Invalid sort column attempted: "
            f"{_sanitize_log_value(sort_by)} from {get_real_ip()}"
        )
        sort_by = 'date_last_played'

    # Ensure valid sort order (SQL injection protection)
    sort_order = sort_order.upper()
    if sort_order not in ['ASC', 'DESC']:
        logger.warning(
            f"Invalid sort order attempted: "
            f"{_sanitize_log_value(sort_order)} from {get_real_ip()}"
        )
        sort_order = 'DESC'

    return page, sort_by, sort_order, selected_columns, columns_param, DATA_VIEWER_COLUMNS


def _build_data_query(db, selected_columns, sort_by, sort_order, page, limit=DEFAULT_PAGE_SIZE):
    """
    Build and execute data query with pagination.

    SECURITY: Uses triple-layer protection against SQL injection:
    1. Input validation against whitelist (caller responsibility)
    2. Assertions to catch programming errors
    3. Explicit SQL identifier construction (no f-strings with user data)

    Args:
        db: Database instance
        selected_columns: List of column names (must be pre-validated)
        sort_by: Sort column name (must be pre-validated)
        sort_order: 'ASC' or 'DESC' (must be pre-validated)
        page: Page number
        limit: Number of results per page

    Returns:
        Tuple of (rows, total_count, total_pages, adjusted_page)

    Note: This function may adjust the page number if it exceeds total_pages.
    Always use the returned page value, not the input page value.
    """
    # SECURITY: Multi-layer validation to prevent SQL injection
    # Layer 1: Check all columns are in immutable whitelist
    if not all(col in DATA_VIEWER_COLUMNS for col in selected_columns):
        logger.error(f"SECURITY: Invalid columns in query: {selected_columns}")
        raise ValueError(f"Invalid columns passed to _build_data_query")

    if sort_by not in DATA_VIEWER_COLUMNS:
        logger.error(f"SECURITY: Invalid sort column: {sort_by}")
        raise ValueError(f"Invalid sort_by passed to _build_data_query")

    if sort_order not in ('ASC', 'DESC'):
        logger.error(f"SECURITY: Invalid sort order: {sort_order}")
        raise ValueError(f"Invalid sort_order passed to _build_data_query")

    # Layer 2: Validate SQL identifier format (defense in depth)
    for col in selected_columns:
        if not _SQL_IDENTIFIER_PATTERN.match(col):
            logger.error(f"SECURITY: Column name contains invalid characters: {col}")
            raise ValueError(f"Column name validation failed")

    if not _SQL_IDENTIFIER_PATTERN.match(sort_by):
        logger.error(f"SECURITY: Sort column contains invalid characters: {sort_by}")
        raise ValueError(f"Sort column validation failed")

    # Layer 3: Build SQL with properly quoted identifiers
    # Use double quotes for SQL identifiers (standard SQL)
    quoted_columns = []
    for col in selected_columns:
        # Escape any quotes (defense in depth - should never trigger after Layer 2)
        safe_col = col.replace('"', '""')
        quoted_columns.append('"' + safe_col + '"')

    select_clause = ', '.join(quoted_columns)

    # Quote sort column with same escaping
    safe_sort = sort_by.replace('"', '""')
    quoted_sort_by = '"' + safe_sort + '"'

    # SECURITY: Use database lock for thread safety
    with db._lock:
        # Get total count of distinct video IDs
        count_query = "SELECT COUNT(DISTINCT yt_video_id) as count FROM video_ratings"
        total_count = db._conn.execute(count_query).fetchone()['count']

        # Calculate pagination
        total_pages = (total_count + limit - 1) // limit
        page = max(1, min(page, total_pages if total_pages > 0 else 1))
        offset = (page - 1) * limit

        # SECURITY: Build query with parameterized LIMIT/OFFSET
        # Use explicit string building to avoid f-string injection risks
        # nosec B608 - select_clause and sort_order are validated against whitelist above
        data_query = (
            "SELECT " + select_clause + " "
            "FROM video_ratings "
            "WHERE rowid IN ("
            "  SELECT MAX(rowid) "
            "  FROM video_ratings "
            "  GROUP BY yt_video_id"
            ") "
            "ORDER BY " + quoted_sort_by + " " + sort_order + " "
            "LIMIT ? OFFSET ?"
        )

        cursor = db._conn.execute(data_query, (limit, offset))
        rows = cursor.fetchall()

    return rows, total_count, total_pages, page


def _format_data_rows(rows, selected_columns):
    """
    Format database rows for template display.

    Returns:
        List of formatted row dictionaries
    """
    formatted_rows = []
    for row in rows:
        formatted_row = {}
        for col in selected_columns:
            value = row[col]
            # Format specific column types
            if col == 'rating':
                if value == 'like':
                    formatted_row[col] = '👍 Like'
                elif value == 'dislike':
                    formatted_row[col] = '👎 Dislike'
                else:
                    formatted_row[col] = '➖ None'
            elif col in ['date_added', 'date_last_played', 'yt_published_at']:
                if value:
                    try:
                        dt = parse_timestamp(value)
                        formatted_row[col] = dt.strftime('%Y-%m-%d %H:%M')
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse timestamp '{value}' for column {col}: {e}")
                        formatted_row[col] = value
                else:
                    formatted_row[col] = '-'
            elif col == 'yt_url' and value:
                # Make URL clickable
                formatted_row[col] = value
                formatted_row[col + '_link'] = True
            elif value is None:
                formatted_row[col] = '-'
            else:
                formatted_row[col] = value
        formatted_rows.append(formatted_row)

    return formatted_rows


# ============================================================================
# DATA VIEWER ROUTES
# ============================================================================

@bp.route('/data')
def data_viewer() -> str:
    """
    Server-side rendered database viewer with column selection and sorting.
    Now uses the unified table_viewer.html template.
    """
    try:
        # Get ingress path for proper link generation
        ingress_path = g.ingress_path

        # Validate and parse request parameters
        page, sort_by, sort_order, selected_columns, columns_param, all_columns = \
            _validate_data_viewer_params(request.args)

        # Build and execute query
        rows, total_count, total_pages, page = _build_data_query(
            _db, selected_columns, sort_by, sort_order, page
        )

        # Use builder pattern for consistent page creation
        builder = DataViewerPageBuilder(ingress_path)
        builder.set_title_suffix(f'{total_count} records')
        builder.set_empty_state('📭', 'No data found', 'No records match your criteria.')
        builder.enable_table_features(sorting=True, resizing=True, column_toggle=True)

        # Create table columns based on selected columns
        columns = []
        for col_key in selected_columns:
            col_label = all_columns.get(col_key, col_key)
            # Make columns sortable and resizable
            column = TableColumn(col_key, col_label, sortable=True, resizable=True)
            columns.append(column)

        # Create table rows
        table_rows = []
        for row_data in rows:
            cells = []
            for col_key in selected_columns:
                value = row_data[col_key]
                
                # Format specific column types
                if col_key == 'rating':
                    if value == 'like':
                        html = format_badge('👍 Like', 'success')
                    elif value == 'dislike':
                        html = format_badge('👎 Dislike', 'error')
                    else:
                        html = format_badge('➖ None', 'default')
                    cells.append(TableCell(value or 'None', html))
                elif col_key == 'yt_url' and value:
                    # Make URL clickable
                    html = f'<a href="{value}" target="_blank" style="color: #2563eb;">🔗 Watch</a>'
                    cells.append(TableCell('YouTube Link', html))
                elif col_key in ['date_added', 'date_last_played', 'yt_published_at']:
                    if value:
                        try:
                            dt = parse_timestamp(value)
                            formatted_time = dt.strftime('%Y-%m-%d %H:%M')
                            cells.append(TableCell(formatted_time))
                        except (ValueError, TypeError):
                            cells.append(TableCell(value or '-'))
                    else:
                        cells.append(TableCell('-'))
                else:
                    # Default cell
                    display_value = str(value) if value is not None else '-'
                    cells.append(TableCell(display_value))
            
            table_rows.append(TableRow(cells))

        # Set table and pagination
        builder.set_table(columns, table_rows)
        builder.set_pagination(page, total_pages, sort_by, sort_order, columns_param)
        builder.set_status_message(f"Showing {len(table_rows)} of {total_count} records • Page {page}/{total_pages}")

        # Build and render
        page_config, table_data, pagination, status_message = builder.build()

        return render_template(
            'table_viewer.html',
            ingress_path=ingress_path,
            page_config=page_config.to_dict(),
            table_data=table_data.to_dict() if table_data and table_data.rows else None,
            pagination=pagination,
            status_message=status_message
        )

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering data viewer", e)
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading database viewer</h1><p>An internal error occurred. Please try again later.</p>", 500


@bp.route('/db-admin')
def database_admin_wrapper():
    """
    Database admin wrapper page that embeds sqlite_web with the navbar.

    This provides access to the sqlite_web admin interface while maintaining
    the YouTube Thumbs navigation context.
    """
    try:
        # Get ingress path from Home Assistant proxy
        ingress_path = g.ingress_path

        # Check if sqlite_web was successfully mounted
        if not _sqlite_web_available:
            error_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Database Admin - Not Available</title>
                <link rel="stylesheet" href="{ingress_path}/static/css/common.css">
            </head>
            <body>
                <div class="container">
                    <header>
                        <div class="header-left">
                            <h1>YouTube Thumbs Rating</h1>
                            <div class="nav-links">
                                <a href="{ingress_path}/?tab=tests">Tests</a>
                                <a href="{ingress_path}/?tab=rating">Bulk Rating</a>
                                <a href="{ingress_path}/stats">Stats</a>
                                <a href="{ingress_path}/data">Database</a>
                                <a href="{ingress_path}/logs?tab=rated">Rated Songs</a>
                                <a href="{ingress_path}/logs?tab=matches">Matches</a>
                                <a href="{ingress_path}/logs?tab=recent">Recent</a>
                                <a href="{ingress_path}/logs?tab=errors">Errors</a>
                                <a href="{ingress_path}/logs/api-calls">API Calls</a>
                                <a href="{ingress_path}/logs/pending-ratings">Queue</a>
                                <a href="{ingress_path}/db-admin" class="active">DB Admin</a>
                            </div>
                        </div>
                    </header>
                    <div class="error-container" style="margin-top: 2rem; padding: 2rem; background-color: #fff3cd; border: 1px solid #ffc107; border-radius: 4px;">
                        <h2 style="color: #856404; margin-top: 0;">Database Admin Not Available</h2>
                        <p style="color: #856404;">
                            The database admin interface could not be loaded because the <code>sqlite-web</code> package is not properly installed or initialized.
                        </p>
                        <p style="color: #856404;">
                            This typically happens when:
                        </p>
                        <ul style="color: #856404;">
                            <li>The addon was not built with the required dependencies</li>
                            <li>The sqlite-web package failed to install</li>
                            <li>There was an error during database initialization</li>
                        </ul>
                        <p style="color: #856404;">
                            <strong>Solution:</strong> Rebuild the addon to ensure all dependencies are installed correctly.
                        </p>
                        <p style="color: #856404;">
                            You can still view database records using the <a href="{ingress_path}/data">Database</a> tab.
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
            return error_html, 503

        return render_template(
            'database_admin.html',
            ingress_path=ingress_path
        )

    except Exception as e:
        LoggingHelper.log_error_with_trace("Error rendering database admin wrapper", e)
        return "<h1>Error loading database admin</h1><p>An internal error occurred. Please try again later.</p>", 500
