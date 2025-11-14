"""
Standardized empty state messages for consistent UX across the application.
"""

# Generic empty states
EMPTY_STATE_NO_DATA = {
    'icon': '📭',
    'title': 'No data found',
    'message': 'No records match your criteria.'
}

# Video-related empty states
EMPTY_STATE_NO_VIDEOS = {
    'icon': '📹',
    'title': 'No videos yet',
    'message': 'No videos have been added to the database yet.'
}

EMPTY_STATE_ALL_RATED = {
    'icon': '🎉',
    'title': 'All songs rated!',
    'message': "You've rated all your songs. Great job!"
}

EMPTY_STATE_NO_LIKED = {
    'icon': '👍',
    'title': 'No liked videos',
    'message': "You haven't liked any videos yet."
}

EMPTY_STATE_NO_DISLIKED = {
    'icon': '👎',
    'title': 'No disliked videos',
    'message': "You haven't disliked any videos yet."
}

# Error/log-related empty states
EMPTY_STATE_NO_ERRORS = {
    'icon': '✓',
    'title': 'No errors found',
    'message': 'System is running smoothly!'
}

EMPTY_STATE_NO_RATED_SONGS = {
    'icon': '📭',
    'title': 'No rated songs found',
    'message': 'Try adjusting your filters'
}

EMPTY_STATE_NO_MATCHES = {
    'icon': '🔍',
    'title': 'No matches found',
    'message': 'Try adjusting your filters'
}

# Queue-related empty states
EMPTY_STATE_QUEUE_EMPTY = {
    'icon': '✓',
    'title': 'Queue is empty',
    'message': 'All operations have been processed.'
}

EMPTY_STATE_NO_HISTORY = {
    'icon': '📭',
    'title': 'No history available',
    'message': 'No recently completed operations.'
}

EMPTY_STATE_NO_QUEUE_ERRORS = {
    'icon': '✓',
    'title': 'No errors',
    'message': 'All operations completing successfully.'
}

# API-related empty states
EMPTY_STATE_NO_API_CALLS = {
    'icon': '📊',
    'title': 'No API calls found',
    'message': 'No API calls have been logged yet, or none match your filters.'
}
