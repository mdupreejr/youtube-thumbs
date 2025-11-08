"""
Common constants used across the YouTube Thumbs addon.
"""

# Values that are considered "false" for boolean environment variables
# Include empty string to handle unset or blank environment variables
FALSE_VALUES = {'false', '0', 'no', 'off', ''}

# YouTube API and matching constants
YOUTUBE_DURATION_OFFSET = 1  # YouTube reports 1 second more than Home Assistant