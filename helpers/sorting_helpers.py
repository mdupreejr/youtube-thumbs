"""
Unified sorting helper for consistent table sorting across all pages.
"""

def sort_table_data(data: list, sort_by: str, sort_dir: str, sort_key_map: dict, numeric_keys: set = None) -> list:
    """
    Sort table data consistently across all table pages.

    Args:
        data: List of dicts to sort
        sort_by: Column name to sort by
        sort_dir: 'asc' or 'desc'
        sort_key_map: Map of column names to data keys
        numeric_keys: Set of keys that should be treated as numbers

    Returns:
        Sorted list (modifies in place)
    """
    if numeric_keys is None:
        numeric_keys = {'play_count', 'attempts', 'quota_cost', 'results_count', 'yt_duration'}

    sort_key = sort_key_map.get(sort_by, list(sort_key_map.values())[0] if sort_key_map else '')
    reverse = (sort_dir == 'desc')

    if sort_key in numeric_keys:
        # Numeric sort
        data.sort(key=lambda x: int(x.get(sort_key) or 0), reverse=reverse)
    elif sort_key == 'success':
        # Boolean sort
        data.sort(key=lambda x: x.get(sort_key) or False, reverse=reverse)
    else:
        # String sort (case-insensitive)
        def sort_fn(x):
            val = x.get(sort_key)
            if val is None:
                return ''
            if isinstance(val, str):
                return val.lower()
            return str(val)
        data.sort(key=sort_fn, reverse=reverse)

    return data
