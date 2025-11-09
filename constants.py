"""
Common constants used across the YouTube Thumbs addon.
"""

# Values that are considered "false" for boolean environment variables
# Include empty string to handle unset or blank environment variables
FALSE_VALUES = {'false', '0', 'no', 'off', ''}

# YouTube API and matching constants
YOUTUBE_DURATION_OFFSET = 1  # YouTube reports 1 second more than Home Assistant

# YouTube category ID to name mapping
# Reference: https://developers.google.com/youtube/v3/docs/videoCategories/list
YOUTUBE_CATEGORIES = {
    1: 'Film & Animation',
    2: 'Autos & Vehicles',
    10: 'Music',
    15: 'Pets & Animals',
    17: 'Sports',
    19: 'Travel & Events',
    20: 'Gaming',
    22: 'People & Blogs',
    23: 'Comedy',
    24: 'Entertainment',
    25: 'News & Politics',
    26: 'Howto & Style',
    27: 'Education',
    28: 'Science & Technology',
    29: 'Nonprofits & Activism'
}