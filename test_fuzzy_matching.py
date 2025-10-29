#!/usr/bin/env python3
"""
Test script for fuzzy matching functionality.
"""
from fuzzy_matcher import (
    calculate_levenshtein_distance,
    calculate_similarity_percentage,
    normalize_title,
    fuzzy_match_titles,
    find_best_fuzzy_match,
    get_title_variations
)


def test_levenshtein_distance():
    """Test Levenshtein distance calculation."""
    print("Testing Levenshtein distance...")
    test_cases = [
        ("kitten", "sitting", 3),
        ("saturday", "sunday", 3),
        ("hello", "hello", 0),
        ("test", "tset", 2),
        ("", "test", 4),
        ("test", "", 4),
    ]

    for s1, s2, expected in test_cases:
        result = calculate_levenshtein_distance(s1, s2)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{s1}' -> '{s2}': {result} (expected: {expected})")


def test_similarity_percentage():
    """Test similarity percentage calculation."""
    print("\nTesting similarity percentage...")
    test_cases = [
        ("Hello World", "Hello World", 100.0),
        ("The Beatles - Yesterday", "Beatles - Yesterday", 85.0),  # approximate
        ("Song Title", "Song Titl", 88.0),  # approximate
        ("Completely Different", "Nothing Similar", 20.0),  # approximate
    ]

    for s1, s2, min_expected in test_cases:
        result = calculate_similarity_percentage(s1, s2)
        status = "✓" if result >= min_expected - 10 else "✗"
        print(f"  {status} '{s1}' vs '{s2}': {result:.1f}% (min expected: {min_expected}%)")


def test_normalize_title():
    """Test title normalization."""
    print("\nTesting title normalization...")
    test_cases = [
        ("Hello, World!", "hello world"),
        ("  Spaces   Everywhere  ", "spaces everywhere"),
        ("Song (Official Video)", "song official video"),
        ("THE BEATLES", "the beatles"),
    ]

    for input_title, expected in test_cases:
        result = normalize_title(input_title)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{input_title}' -> '{result}' (expected: '{expected}')")


def test_fuzzy_matching():
    """Test fuzzy matching with sample data."""
    print("\nTesting fuzzy matching...")

    # Sample database records
    candidates = [
        {"yt_video_id": "1", "ha_title": "Yesterday - The Beatles"},
        {"yt_video_id": "2", "ha_title": "Yesterday (Remastered)"},
        {"yt_video_id": "3", "ha_title": "Let It Be - The Beatles"},
        {"yt_video_id": "4", "ha_title": "Hey Jude"},
        {"yt_video_id": "5", "ha_title": "Yesterday by Beatles"},
    ]

    # Test query
    query = "Yesterday Beatles"
    matches = fuzzy_match_titles(query, candidates, threshold=70.0)

    print(f"  Query: '{query}'")
    print(f"  Found {len(matches)} matches:")
    for match, score in matches:
        print(f"    - {match['ha_title']}: {score:.1f}%")


def test_best_match_with_metadata():
    """Test finding best match considering duration and artist."""
    print("\nTesting best match with metadata...")

    candidates = [
        {
            "yt_video_id": "1",
            "ha_title": "Yesterday",
            "ha_duration": 125,
            "yt_channel": "The Beatles"
        },
        {
            "yt_video_id": "2",
            "ha_title": "Yesterday (Cover)",
            "ha_duration": 130,
            "yt_channel": "Cover Artist"
        },
        {
            "yt_video_id": "3",
            "ha_title": "Yesterdays Song",
            "ha_duration": 125,
            "yt_channel": "Different Artist"
        },
    ]

    query = "Yesterday"
    duration = 125
    artist = "Beatles"

    best = find_best_fuzzy_match(
        query,
        candidates,
        duration=duration,
        artist=artist,
        threshold=70.0
    )

    if best:
        print(f"  Query: '{query}' (duration: {duration}s, artist: '{artist}')")
        print(f"  Best match: {best['ha_title']} by {best['yt_channel']}")
    else:
        print("  No match found!")


def test_title_variations():
    """Test title variation generation."""
    print("\nTesting title variations...")

    test_titles = [
        "Song Title [Official Video]",
        "(Audio) Song Title",
        "The Beatles - Yesterday",
        "Song ft. Artist",
        "Song - Lyric Video",
    ]

    for title in test_titles:
        variations = get_title_variations(title)
        print(f"  '{title}':")
        for var in variations:
            if var != title:
                print(f"    -> '{var}'")


if __name__ == "__main__":
    print("Running fuzzy matching tests...\n")
    print("=" * 50)

    test_levenshtein_distance()
    test_similarity_percentage()
    test_normalize_title()
    test_fuzzy_matching()
    test_best_match_with_metadata()
    test_title_variations()

    print("\n" + "=" * 50)
    print("Tests completed!")