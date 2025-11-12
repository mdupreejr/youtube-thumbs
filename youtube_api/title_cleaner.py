"""
Title cleaning and sanitization utilities for YouTube search.

This module provides functions to clean, sanitize, and simplify video titles
for optimal YouTube search results.
"""

import re
import unicodedata
from typing import Optional, List
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)


# v4.0.61: Optimized string processing constants
NOISE_WORDS = frozenset([
    'FULL', 'HD', 'HQ', '4K', '8K', 'OFFICIAL',
    'NEW', 'EXCLUSIVE', 'PREMIERE', 'ORIGINAL',
])

# Regex patterns compiled once for better performance
EMOJI_PATTERN = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251]+')
SPECIAL_CHARS_PATTERN = re.compile(r'[^\w\s\-\'\"]+')


def sanitize_title(title: str) -> str:
    """
    Sanitize and validate title for security.

    Handles Unicode normalization, type validation, and length checks to prevent
    normalization attacks and DoS via excessive length.

    Args:
        title: Raw title string from user input

    Returns:
        Sanitized title string

    Raises:
        ValueError: If title is not a string
    """
    # SECURITY: Validate input type
    if not isinstance(title, str):
        raise ValueError("Title must be a string")

    # SECURITY: Normalize Unicode FIRST to prevent normalization attacks
    # NFC (Canonical Decomposition, followed by Canonical Composition) is the standard form
    title = unicodedata.normalize('NFC', title)

    # SECURITY: Validate length AFTER normalization to prevent length bypass attacks
    # YouTube video titles are limited to ~100 chars, but allow 500 for safety
    MAX_TITLE_LENGTH = 500
    if len(title) > MAX_TITLE_LENGTH:
        logger.warning(f"Title exceeds maximum length ({len(title)} > {MAX_TITLE_LENGTH}), truncating")
        title = title[:MAX_TITLE_LENGTH]

    return title.strip()


def clean_title(title: str) -> str:
    """
    Remove noise from title: emojis, special chars, noise words, suffixes.

    Args:
        title: Title to clean

    Returns:
        Cleaned title string
    """
    # v4.0.61: OPTIMIZED - Use regex for emoji/special char removal (2-3x faster)
    # Remove emojis first
    clean = EMOJI_PATTERN.sub('', title)
    # Remove special characters, keeping alphanumeric, spaces, hyphens, quotes
    clean = SPECIAL_CHARS_PATTERN.sub(' ', clean)

    # Split on pipe character and take the first part (main title)
    # This handles cases like "Song Title | Additional Info"
    if '|' in clean:
        parts = clean.split('|')
        clean = parts[0].strip()
        # If the first part is too short, use the whole thing
        if len(clean) < 10 and len(parts) > 1:
            clean = ' '.join(p.strip() for p in parts[:2])

    # v4.0.61: OPTIMIZED - Use class constant for noise words (no recreation on each call)
    words = clean.split()
    words = [w for w in words if w.upper() not in NOISE_WORDS]
    clean = ' '.join(words)

    # Remove common suffixes that might interfere with search
    suffixes_to_remove = [
        ' (Official Video)', ' (Official Audio)', ' (Lyric Video)', ' (Lyrics Video)',
        ' (Audio)', ' (Video)',
        ' [Official Video]', ' [Official Audio]', ' [Lyric Video]', ' [Audio]', ' [Video]',
    ]
    for suffix in suffixes_to_remove:
        if clean.endswith(suffix):
            clean = clean[:-len(suffix)].strip()
            break

    return clean


def extract_artist_name(title: str) -> Optional[str]:
    """
    Extract artist name from possessive form ("Artist's Song").
    v4.0.61: Extracted to reduce cyclomatic complexity.

    Args:
        title: Title string to extract from

    Returns:
        Artist name if found and valid, None otherwise
    """
    if "'s " not in title:
        return None

    potential_artist = title.split("'s ")[0]
    if len(potential_artist) < 30:
        return potential_artist
    return None


def extract_event_phrases(title: str) -> List[str]:
    """
    Extract important event phrases from long titles (concerts, shows, etc.).
    v4.0.61: Extracted to reduce cyclomatic complexity.

    Args:
        title: Title string to extract from

    Returns:
        List of extracted event phrases
    """
    event_keywords = ['Super Bowl', 'Halftime Show', 'Concert', 'Live', 'Performance',
                     'Awards', 'Festival', 'Tour', 'Show']
    phrases = []

    for keyword in event_keywords:
        if keyword in title:
            # Find the phrase containing this keyword
            words = title.split()
            for i, word in enumerate(words):
                if keyword in ' '.join(words[i:i+len(keyword.split())]):
                    # Take keyword plus surrounding context (up to 2 words each side)
                    start = max(0, i - 2)
                    end = min(len(words), i + len(keyword.split()) + 2)
                    phrase = ' '.join(words[start:end])
                    phrases.append(phrase)
                    break  # Only add first occurrence of each keyword

    return phrases


def simplify_long_title(title: str, original_title: str) -> str:
    """
    Extract key terms from overly long titles (>100 chars).

    For long titles, extract artist names and event phrases to create
    a more focused search query.

    Args:
        title: Cleaned title to simplify
        original_title: Original title for logging purposes

    Returns:
        Simplified title or original if no simplification needed
    """
    if len(title) <= 100:
        return title

    important_parts = []

    # Extract artist name if present (e.g., "Artist's Song")
    artist_name = extract_artist_name(title)
    if artist_name:
        important_parts.append(artist_name)

    # Extract event phrases (e.g., "Super Bowl", "Live Performance")
    event_phrases = extract_event_phrases(title)
    important_parts.extend(event_phrases)

    if important_parts:
        simplified = ' '.join(important_parts)
        logger.debug(f"Long title simplified: '{original_title[:80]}...' -> '{simplified}'")
        return simplified

    return title


def enhance_with_artist(query: str, artist: str = None) -> str:
    """
    Enhance search query with artist name if useful.

    Adds artist/channel name to the query to improve accuracy for generic titles
    like "Flowers", "Electric", etc. Filters out generic artist names.

    Args:
        query: Base search query
        artist: Artist/channel name (optional)

    Returns:
        Enhanced query with artist, or original query if artist not useful
    """
    if not artist or not isinstance(artist, str):
        return query

    artist_clean = artist.strip()
    # Only use artist if it's not "YouTube" (the platform) or other generic values
    if not artist_clean or artist_clean.lower() in ['youtube', 'unknown', '']:
        return query

    # Clean artist name (remove emojis, special chars)
    artist_clean = EMOJI_PATTERN.sub('', artist_clean)
    artist_clean = SPECIAL_CHARS_PATTERN.sub(' ', artist_clean)
    artist_clean = ' '.join(artist_clean.split())  # Remove extra whitespace

    if artist_clean:
        # v5.0.10: Check if artist is already in query (Issue #123)
        # Prevents duplicates like "The Verve - Bittersweet Symphony The Verve"
        query_lower = query.lower()
        artist_lower = artist_clean.lower()

        if artist_lower in query_lower:
            logger.debug(f"Artist '{artist_clean}' already in query, not adding")
            return query

        enhanced_query = f"{query} {artist_clean}"
        logger.debug(f"Enhanced search query with artist: '{enhanced_query}'")
        return enhanced_query

    return query


def build_smart_search_query(title: str, artist: str = None) -> str:
    """
    Build a simple, effective search query for YouTube.

    Orchestrates the query building process through focused helper methods:
    1. Sanitize: Security validation and normalization
    2. Clean: Remove noise (emojis, special chars, suffixes)
    3. Simplify: Extract key terms from long titles
    4. Enhance: Add artist if useful

    v4.0.75: Refactored into smaller methods for maintainability.

    Args:
        title: The song/video title to search for
        artist: Artist/channel name (optional, improves accuracy for generic titles)

    Returns:
        Cleaned search query string
    """
    # Step 1: Sanitize and validate (security)
    original_title = title
    title = sanitize_title(title)

    # Step 2: Clean the title (remove noise)
    clean = clean_title(title)

    # Step 3: Simplify if too long (extract key terms)
    clean = simplify_long_title(clean, original_title)

    # Step 4: Clean up excessive whitespace
    search_query = ' '.join(clean.split())

    # Step 5: Enhance with artist if provided and useful
    search_query = enhance_with_artist(search_query, artist)

    # Step 6: Final validation - limit query length (YouTube limit is ~500 chars)
    MAX_QUERY_LENGTH = 500
    if len(search_query) > MAX_QUERY_LENGTH:
        logger.warning("Search query too long (%d chars), truncating", len(search_query))
        search_query = search_query[:MAX_QUERY_LENGTH]

    return search_query
