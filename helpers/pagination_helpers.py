"""
Pagination helper utilities.

Provides reusable pagination logic to eliminate code duplication across routes.
"""
from typing import List, Union, Dict, Optional
from urllib.parse import urlencode


def generate_page_numbers(current_page: int, total_pages: int) -> List[Union[int, str]]:
    """
    Generate smart pagination numbers with ellipsis for large page counts.

    Logic:
    - If 10 or fewer pages: show all page numbers
    - If more than 10 pages: show first, last, and pages around current with ellipsis

    Args:
        current_page: Current page number (1-indexed)
        total_pages: Total number of pages

    Returns:
        List of page numbers and ellipsis strings
        Example: [1, '...', 8, 9, 10, 11, 12, '...', 50]

    Examples:
        >>> generate_page_numbers(1, 5)
        [1, 2, 3, 4, 5]

        >>> generate_page_numbers(10, 50)
        [1, '...', 8, 9, 10, 11, 12, '...', 50]

        >>> generate_page_numbers(1, 50)
        [1, 2, 3, '...', 50]

        >>> generate_page_numbers(50, 50)
        [1, '...', 48, 49, 50]
    """
    # Validate inputs
    if total_pages < 1:
        return [1]

    # Clamp current_page to valid range
    current_page = max(1, min(current_page, total_pages))

    if total_pages <= 10:
        # Show all pages if 10 or fewer
        return list(range(1, total_pages + 1))

    # For more than 10 pages, use smart pagination
    # Use a set to collect unique page numbers, then sort and add ellipsis
    pages = set()

    # Always include first and last page
    pages.add(1)
    pages.add(total_pages)

    # Add pages around current page
    start = max(1, current_page - 2)
    end = min(total_pages, current_page + 2)
    for p in range(start, end + 1):
        pages.add(p)

    # Convert to sorted list
    sorted_pages = sorted(pages)

    # Build result with ellipsis where there are gaps
    result = []
    for i, page in enumerate(sorted_pages):
        if i > 0 and sorted_pages[i] - sorted_pages[i-1] > 1:
            result.append('...')
        result.append(page)

    return result


def build_pagination_url(base_path: str, page: int, filters: Optional[Dict[str, str]] = None) -> str:
    """
    Build a pagination URL with query parameters.

    Args:
        base_path: Base URL path (e.g., '/logs/api-calls')
        page: Page number
        filters: Optional dictionary of filter parameters to include in the URL

    Returns:
        Complete URL with query parameters

    Examples:
        >>> build_pagination_url('/logs/api-calls', 2)
        '/logs/api-calls?page=2'

        >>> build_pagination_url('/logs/api-calls', 2, {'method': 'search'})
        '/logs/api-calls?page=2&method=search'

        >>> build_pagination_url('/logs/api-calls', 2, {'method': 'search', 'success': 'true'})
        '/logs/api-calls?page=2&method=search&success=true'
    """
    params = {'page': str(page)}
    
    # Add non-empty filter parameters
    if filters:
        for key, value in filters.items():
            if value is not None and value != '':
                params[key] = str(value)
    
    return f"{base_path}?{urlencode(params)}"
