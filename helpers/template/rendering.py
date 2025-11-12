"""
Rendering functions for the unified table viewer.

Provides utilities to render pages with the table_viewer.html template.
"""

from typing import Dict, Any, Optional
from flask import render_template
from .data_structures import PageConfig, TableData


def render_table_page(
    page_config: PageConfig,
    ingress_path: str,
    table_data: Optional[TableData] = None,
    pagination: Optional[Dict] = None,
    status_message: str = '',
    summary_stats: Optional[Dict] = None
):
    """
    Render table viewer page with consistent parameters.

    Consolidates 15+ identical render_template calls across route files.

    Args:
        page_config: PageConfig object with page configuration
        ingress_path: Ingress path for navigation
        table_data: Optional TableData object with table rows/columns
        pagination: Optional pagination dictionary
        status_message: Optional status message to display
        summary_stats: Optional summary statistics dictionary

    Returns:
        Rendered template response

    Example:
        builder = LogsPageBuilder('recent', ingress_path)
        builder.set_title('Recent Videos')
        page_config, table_data, pagination, status = builder.build()
        return render_table_page(page_config, ingress_path, table_data, pagination, status)
    """
    return render_template(
        'table_viewer.html',
        ingress_path=ingress_path,
        page_config=page_config.to_dict(),
        table_data=table_data.to_dict() if table_data and table_data.rows else None,
        pagination=pagination,
        status_message=status_message,
        summary_stats=summary_stats
    )


def create_pagination_info(page: int, per_page: int, total_count: int, base_url: str) -> Dict[str, Any]:
    """
    Create pagination information for the unified table template.

    Args:
        page: Current page number (1-based)
        per_page: Number of items per page
        total_count: Total number of items
        base_url: Base URL for pagination links

    Returns:
        Dictionary containing pagination information for the template
    """
    total_pages = (total_count + per_page - 1) // per_page

    if total_pages <= 1:
        return None

    # Generate page numbers to display
    page_numbers = []
    start_page = max(1, page - 2)
    end_page = min(total_pages, page + 2)

    if start_page > 1:
        page_numbers.append(1)
        if start_page > 2:
            page_numbers.append('...')

    for p in range(start_page, end_page + 1):
        page_numbers.append(p)

    if end_page < total_pages:
        if end_page < total_pages - 1:
            page_numbers.append('...')
        page_numbers.append(total_pages)

    return {
        'current_page': page,
        'total_pages': total_pages,
        'page_numbers': page_numbers,
        'prev_url': f"{base_url}?page={page-1}" if page > 1 else None,
        'next_url': f"{base_url}?page={page+1}" if page < total_pages else None,
        'page_url_template': f"{base_url}?page=PAGE_NUM"
    }


def create_status_message(items_count: int, total_count: int = None,
                         item_type: str = 'items') -> str:
    """
    Create a standardized status message for table displays.

    Args:
        items_count: Number of items currently displayed
        total_count: Total number of items available (if different from displayed)
        item_type: Type of items being displayed (e.g., 'songs', 'errors')

    Returns:
        Formatted status message
    """
    if total_count and total_count > items_count:
        return f"Showing {items_count:,} of {total_count:,} {item_type}"
    else:
        return f"Showing {items_count:,} {item_type}"
