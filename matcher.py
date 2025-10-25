from typing import List, Dict
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
        
        # Remove extra whitespace
        text = ' '.join(text.split())
        
        return text
    
    @staticmethod
    def filter_candidates_by_title(ha_title: str, candidates: List[Dict]) -> List[Dict]:
        """
        Filter video candidates by title text matching.
        
        Args:
            ha_title: Title from Home Assistant
            candidates: List of video dicts with 'video_id', 'title', 'channel', 'duration'
        
        Returns:
            List of matching videos (may be empty)
        """
        ha_title_norm = TitleMatcher.normalize_text(ha_title)
        matches = []
        
        logger.info(f"Filtering {len(candidates)} candidates by title: '{ha_title}'")
        
        ha_words = set(ha_title_norm.split())

        for video in candidates:
            yt_title = video.get('title', '')
            yt_title_norm = TitleMatcher.normalize_text(yt_title)
            
            # Check if HA title words appear in YouTube title
            # Extract key words from HA title (ignore common words)
            yt_words = set(yt_title_norm.split())
            
            # Calculate overlap - need at least 50% of HA words in YT title
            if ha_words:
                overlap = len(ha_words & yt_words) / len(ha_words)
                if overlap >= 0.5:
                    logger.info(f"Title match: '{yt_title}' (overlap: {overlap:.0%})")
                    matches.append(video)
                else:
                    logger.debug(f"Title rejected: '{yt_title}' (overlap: {overlap:.0%})")
        
        logger.info(f"Title filtering: {len(matches)}/{len(candidates)} candidates matched")
        return matches

# Create global instance
matcher = TitleMatcher()
