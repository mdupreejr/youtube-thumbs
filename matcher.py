import re
from typing import List, Dict, Optional, Set
from logger import logger

REPLACEMENTS = {
    ' - ': ' ',
    ' – ': ' ',
    ' — ': ' ',
    '(official video)': '',
    '(official music video)': '',
    '(official audio)': '',
    '(lyric video)': '',
    '(lyrics)': '',
    '[official video]': '',
    '[official music video]': '',
    '[official audio]': '',
    'ft.': 'feat.',
    'ft ': 'feat ',
}

NON_ALNUM_PATTERN = re.compile(r'[^a-z0-9\s]')
MIN_TITLE_OVERLAP = 0.9  # Require near-identical titles (≈90% overlap)

class TitleMatcher:
    """Match song titles between Home Assistant and YouTube history."""
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text for comparison."""
        if not text:
            return ""
        
        # Convert to lowercase
        text = text.lower()
        
        # Remove common separators and variations
        for old, new in REPLACEMENTS.items():
            text = text.replace(old, new)
        
        # Remove remaining punctuation/symbols and collapse whitespace
        text = NON_ALNUM_PATTERN.sub(' ', text)
        text = ' '.join(text.split())
        
        return text
    
    @staticmethod
    def _word_set(text: str) -> Set[str]:
        normalized = TitleMatcher.normalize_text(text)
        return set(normalized.split()) if normalized else set()
    
    @staticmethod
    def filter_candidates_by_title(
        ha_title: str,
        candidates: List[Dict],
        ha_artist: Optional[str] = None
    ) -> List[Dict]:
        """
        Filter video candidates by title text matching.
        
        Args:
            ha_title: Title from Home Assistant
            candidates: List of video dicts with 'video_id', 'title', 'channel', 'duration'
            ha_artist: Optional artist/channel hint from Home Assistant
        
        Returns:
            List of matching videos (may be empty)
        """
        matches: List[Dict] = []
        ha_words = TitleMatcher._word_set(ha_title)
        artist_hint = TitleMatcher.normalize_text(ha_artist) if ha_artist else None
        logger.info("Filtering %s candidates by title '%s'", len(candidates), ha_title)

        if not ha_words:
            logger.warning("Cannot filter candidates without HA title words")
            return matches

        for video in candidates:
            yt_title = video.get('title', '')
            yt_words = TitleMatcher._word_set(yt_title)
            if not yt_words:
                logger.debug("Title rejected: '%s' (no usable words)", yt_title)
                continue

            overlap_words = ha_words & yt_words
            if not overlap_words:
                logger.debug("Title rejected: '%s' (no overlap)", yt_title)
                continue

            overlap_ratio = len(overlap_words) / len(ha_words)
            yt_coverage = len(overlap_words) / len(yt_words)

            if overlap_ratio < MIN_TITLE_OVERLAP:
                logger.debug(
                    "Title rejected: '%s' (overlap %.0f%% < %.0f%% required)",
                    yt_title,
                    overlap_ratio * 100,
                    MIN_TITLE_OVERLAP * 100,
                )
                continue

            score = overlap_ratio * 0.7 + yt_coverage * 0.3

            channel = video.get('channel')
            if artist_hint and channel:
                channel_norm = TitleMatcher.normalize_text(channel)
                if artist_hint in channel_norm:
                    score += 0.15  # prefer artist/channel matches

            logger.info(
                "Title match: '%s' (HA overlap %.0f%%, YT coverage %.0f%%, score %.2f)",
                yt_title,
                overlap_ratio * 100,
                yt_coverage * 100,
                score,
            )

            video['_match_score'] = round(score, 4)
            matches.append(video)
        
        matches.sort(key=lambda v: v.get('_match_score', 0), reverse=True)
        logger.info("Title filtering: %s/%s candidates matched", len(matches), len(candidates))
        return matches

# Create global instance
matcher = TitleMatcher()
