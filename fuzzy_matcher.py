"""
Fuzzy matching utilities for enhanced local caching.
Uses Levenshtein distance and similarity scoring to find approximate title matches.
"""
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
import re


def calculate_levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings.

    Args:
        s1: First string
        s2: Second string

    Returns:
        The minimum number of single-character edits required to change s1 into s2
    """
    if len(s1) < len(s2):
        return calculate_levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # j+1 instead of j since previous_row and current_row are one character longer than s2
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def calculate_similarity_percentage(s1: str, s2: str, use_levenshtein: bool = True) -> float:
    """
    Calculate similarity percentage between two strings.

    Args:
        s1: First string
        s2: Second string
        use_levenshtein: If True, use Levenshtein distance; if False, use SequenceMatcher

    Returns:
        Similarity percentage (0-100)
    """
    if not s1 or not s2:
        return 0.0

    # Normalize strings for comparison
    s1_normalized = normalize_title(s1)
    s2_normalized = normalize_title(s2)

    if s1_normalized == s2_normalized:
        return 100.0

    if use_levenshtein:
        # Calculate similarity based on Levenshtein distance
        max_len = max(len(s1_normalized), len(s2_normalized))
        if max_len == 0:
            return 100.0
        distance = calculate_levenshtein_distance(s1_normalized, s2_normalized)
        similarity = (1 - distance / max_len) * 100
        return max(0, similarity)
    else:
        # Use SequenceMatcher for similarity (faster but less precise)
        ratio = SequenceMatcher(None, s1_normalized, s2_normalized).ratio()
        return ratio * 100


def normalize_title(title: str) -> str:
    """
    Normalize a title for fuzzy matching.

    Args:
        title: The title to normalize

    Returns:
        Normalized title (lowercase, stripped whitespace, removed punctuation)
    """
    # Convert to lowercase
    normalized = title.lower().strip()

    # Remove common punctuation and special characters but keep spaces
    normalized = re.sub(r'[^\w\s]', '', normalized)

    # Normalize multiple spaces to single space
    normalized = re.sub(r'\s+', ' ', normalized)

    return normalized


def fuzzy_match_titles(
    query_title: str,
    candidates: List[Dict[str, Any]],
    threshold: float = 85.0,
    title_key: str = 'ha_title',
    use_levenshtein: bool = True
) -> List[Tuple[Dict[str, Any], float]]:
    """
    Find fuzzy matches for a title from a list of candidates.

    Args:
        query_title: The title to match
        candidates: List of candidate records (dicts)
        threshold: Minimum similarity percentage to consider a match (0-100)
        title_key: Key in candidate dicts containing the title to compare
        use_levenshtein: If True, use Levenshtein distance; if False, use SequenceMatcher

    Returns:
        List of (candidate, similarity_score) tuples sorted by similarity descending
    """
    if not query_title or not candidates:
        return []

    matches = []

    for candidate in candidates:
        candidate_title = candidate.get(title_key)
        if not candidate_title:
            continue

        similarity = calculate_similarity_percentage(
            query_title,
            candidate_title,
            use_levenshtein=use_levenshtein
        )

        if similarity >= threshold:
            matches.append((candidate, similarity))

    # Sort by similarity score (highest first)
    matches.sort(key=lambda x: x[1], reverse=True)

    return matches


def find_best_fuzzy_match(
    query_title: str,
    candidates: List[Dict[str, Any]],
    duration: Optional[int] = None,
    artist: Optional[str] = None,
    threshold: float = 85.0,
    title_key: str = 'ha_title',
    use_levenshtein: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Find the best fuzzy match considering title, duration, and artist.

    Args:
        query_title: The title to match
        candidates: List of candidate records (dicts)
        duration: Optional duration to match (will prefer matches with similar duration)
        artist: Optional artist to match (will prefer matches with similar artist)
        threshold: Minimum similarity percentage to consider a match (0-100)
        title_key: Key in candidate dicts containing the title to compare
        use_levenshtein: If True, use Levenshtein distance; if False, use SequenceMatcher

    Returns:
        Best matching candidate or None if no match above threshold
    """
    fuzzy_matches = fuzzy_match_titles(
        query_title,
        candidates,
        threshold=threshold,
        title_key=title_key,
        use_levenshtein=use_levenshtein
    )

    if not fuzzy_matches:
        return None

    # If we have duration and/or artist, refine the matches
    if duration is not None or artist:
        scored_matches = []

        for candidate, title_similarity in fuzzy_matches:
            score = title_similarity

            # Adjust score based on duration match
            if duration is not None:
                candidate_duration = candidate.get('ha_duration') or candidate.get('yt_duration')
                if candidate_duration:
                    duration_diff = abs(candidate_duration - duration)
                    if duration_diff <= 2:
                        score += 10  # Boost for exact/near duration match
                    elif duration_diff <= 5:
                        score += 5   # Small boost for close duration
                    else:
                        score -= min(duration_diff, 20)  # Penalty for wrong duration

            # Adjust score based on artist match
            if artist:
                candidate_artist = candidate.get('ha_artist') or candidate.get('yt_channel')
                if candidate_artist:
                    artist_similarity = calculate_similarity_percentage(
                        artist,
                        candidate_artist,
                        use_levenshtein=False  # Use faster method for artist
                    )
                    if artist_similarity >= 90:
                        score += 10  # Boost for matching artist
                    elif artist_similarity >= 70:
                        score += 5   # Small boost for similar artist

            scored_matches.append((candidate, score))

        # Sort by adjusted score
        scored_matches.sort(key=lambda x: x[1], reverse=True)

        if scored_matches and scored_matches[0][1] >= threshold:
            return scored_matches[0][0]
    else:
        # No additional criteria, just return the best title match
        return fuzzy_matches[0][0]

    return None


def get_title_variations(title: str) -> List[str]:
    """
    Generate common variations of a title for matching.

    Args:
        title: The original title

    Returns:
        List of title variations
    """
    variations = [title]

    # Remove common prefixes/suffixes
    patterns_to_remove = [
        r'^\s*\[.*?\]\s*',  # [Something] at beginning
        r'\s*\[.*?\]\s*$',  # [Something] at end
        r'^\s*\(.*?\)\s*',  # (Something) at beginning
        r'\s*\(.*?\)\s*$',  # (Something) at end
        r'\s*-\s*official.*$',  # - Official Video/Audio etc
        r'\s*-\s*lyric.*$',  # - Lyric Video etc
        r'\s*-\s*audio.*$',  # - Audio etc
        r'\s*ft\..*$',  # ft. featuring
        r'\s*feat\..*$',  # feat. featuring
    ]

    for pattern in patterns_to_remove:
        modified = re.sub(pattern, '', title, flags=re.IGNORECASE).strip()
        if modified and modified != title and modified not in variations:
            variations.append(modified)

    # Add version without "The" at beginning
    if title.lower().startswith('the '):
        without_the = title[4:].strip()
        if without_the and without_the not in variations:
            variations.append(without_the)

    return variations