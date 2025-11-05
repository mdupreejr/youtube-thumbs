"""
Data viewer route for browsing the video_ratings database table.
Extracted from app.py for better organization.
"""
import re
import types
import traceback
from flask import Blueprint, render_template, request
from logger import logger
from helpers.pagination_helpers import generate_page_numbers
from helpers.time_helpers import parse_timestamp
from helpers.validation_helpers import validate_page_param
from helpers.request_helpers import get_real_ip

bp = Blueprint('data_viewer', __name__)

# Global database reference (set by init function)
_db = None

def init_data_viewer_routes(database):
    """Initialize data viewer routes with dependencies."""
    global _db
    _db = database


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
    'yt_match_pending': 'Pending',
    'yt_match_attempts': 'Match Attempts',
    'ha_duration': 'Duration (HA)',
    'yt_duration': 'Duration (YT)',
    'yt_published_at': 'Published',
    'yt_category_id': 'Category',
    'pending_reason': 'Pending Reason'
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
            elif col == 'yt_match_pending':
                formatted_row[col] = '✓' if value == 1 else '✗'
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
    All processing done on server, no client-side JavaScript required.
    """
    try:
        # Get ingress path for proper link generation
        ingress_path = request.environ.get('HTTP_X_INGRESS_PATH', '')

        # Validate and parse request parameters
        page, sort_by, sort_order, selected_columns, columns_param, all_columns = \
            _validate_data_viewer_params(request.args)

        # Build and execute query
        rows, total_count, total_pages, page = _build_data_query(
            _db, selected_columns, sort_by, sort_order, page
        )

        # Format rows for display
        formatted_rows = _format_data_rows(rows, selected_columns)

        # Generate page numbers for pagination
        page_numbers = generate_page_numbers(page, total_pages)

        # Prepare template data
        template_data = {
            'ingress_path': ingress_path,
            'rows': formatted_rows,
            'selected_columns': selected_columns,
            'all_columns': all_columns,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'page': page,
            'total_pages': total_pages,
            'total_count': total_count,
            'columns_param': columns_param,
            'page_numbers': page_numbers
        }

        return render_template('data_viewer.html', **template_data)

    except Exception as e:
        logger.error(f"Error rendering data viewer: {e}")
        logger.error(traceback.format_exc())
        # SECURITY: Don't expose error details to user (information disclosure)
        return "<h1>Error loading database viewer</h1><p>An internal error occurred. Please try again later.</p>", 500
