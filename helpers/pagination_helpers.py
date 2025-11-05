"""
Pagination helper utilities.

Provides reusable pagination logic to eliminate code duplication across routes.
"""
from typing import List, Union


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
    page_numbers = []

    if total_pages <= 10:
        # Show all pages if 10 or fewer
        page_numbers = list(range(1, total_pages + 1))
    else:
        # Show first, last, and pages around current
        page_numbers = [1]

        # Calculate range around current page
        start = max(2, current_page - 2)
        end = min(total_pages - 1, current_page + 2)

        # Add ellipsis before middle section if needed
        if start > 2:
            page_numbers.append('...')

        # Add middle section (pages around current)
        for p in range(start, end + 1):
            page_numbers.append(p)

        # Add ellipsis after middle section if needed
        if end < total_pages - 1:
            page_numbers.append('...')

        # Always show last page
        page_numbers.append(total_pages)

    return page_numbers
