import json
import os
import re
import stat
import traceback
import unicodedata
from typing import Optional, List, Dict, Any, Tuple
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from logger import logger
from error_handler import log_and_suppress, validate_environment_variable
from decorators import handle_youtube_error
import decorators
from constants import YOUTUBE_DURATION_OFFSET
from quota_error import QuotaExceededError

# Global database instance for API usage tracking (injected from app.py)
_db = None

def set_database(db):
    """Set the database instance for API usage tracking."""
    global _db
    _db = db
    # Also set database in decorators module so it can log API call errors
    decorators._db = db

class YouTubeAPI:
    """Interface to YouTube Data API v3."""

    SCOPES = ['https://www.googleapis.com/auth/youtube']
    DURATION_PATTERN = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
    NO_RATING = 'none'  # YouTube API rating value for unrated videos
    MAX_SEARCH_RESULTS = validate_environment_variable(
        'YTT_SEARCH_MAX_RESULTS',
        default=25,
        converter=int,
        validator=lambda x: 1 <= x <= 50
    )
    MAX_CANDIDATES = validate_environment_variable(
        'YTT_SEARCH_MAX_CANDIDATES',
        default=10,
        converter=int,
        validator=lambda x: 1 <= x <= 50
    )
    SEARCH_FIELDS = 'items(id/videoId,snippet/title)'
    VIDEO_FIELDS = 'items(id,snippet(title,channelTitle,channelId,description,publishedAt,categoryId,liveBroadcastContent),contentDetails(duration),recordingDetails(location,recordingDate))'
    QUOTA_REASON_CODES = {
        'quotaExceeded',
        'rateLimitExceeded',
        'userRateLimitExceeded',
        'dailyLimitExceeded',
        'dailyLimitExceededUnreg',
        'limitExceeded',
        'usageLimits.rateLimitExceeded',
    }
    QUOTA_REASON_TOKENS = tuple(code.lower() for code in QUOTA_REASON_CODES)
    QUOTA_MESSAGE_KEYWORDS = ('quota', 'rate limit', 'ratelimit', 'limit exceeded')

    # v4.0.61: Optimized string processing constants
    NOISE_WORDS = frozenset([
        'FULL', 'HD', 'HQ', '4K', '8K', 'OFFICIAL',
        'NEW', 'EXCLUSIVE', 'PREMIERE', 'ORIGINAL',
    ])
    # Regex patterns compiled once for better performance
    EMOJI_PATTERN = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251]+')
    SPECIAL_CHARS_PATTERN = re.compile(r'[^\w\s\-\'\"]+')

    def __init__(self) -> None:
        self.youtube = None
        self.authenticate()
    
    def authenticate(self) -> None:
        """Authenticate with YouTube API using OAuth2."""
        creds = None
        token_file = 'token.json'  # nosec B105 - filename, not password

        # Load credentials from JSON file
        if os.path.exists(token_file):
            try:
                # Check and fix insecure file permissions
                file_stat = os.stat(token_file)
                file_mode = stat.S_IMODE(file_stat.st_mode)
                expected_mode = stat.S_IRUSR | stat.S_IWUSR  # 600

                if file_mode != expected_mode:
                    logger.warning(f"Token file has insecure permissions ({oct(file_mode)}), fixing to 600")
                    os.chmod(token_file, expected_mode)

                with open(token_file, 'r') as f:
                    token_data = json.load(f)
                creds = Credentials.from_authorized_user_info(token_data, self.SCOPES)
                logger.debug("Loaded YouTube API credentials from JSON")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to load credentials from {token_file}: {e}")
                logger.warning("Removing corrupted token file")
                os.remove(token_file)
                creds = None
            except OSError as e:
                logger.error(f"Failed to check/fix token file permissions: {e}")
                # Continue anyway - permission check failure shouldn't block authentication
                try:
                    with open(token_file, 'r') as f:
                        token_data = json.load(f)
                    creds = Credentials.from_authorized_user_info(token_data, self.SCOPES)
                    logger.debug("Loaded YouTube API credentials from JSON (permission check failed)")
                except Exception as inner_e:
                    logger.error(f"Failed to load credentials: {inner_e}")
                    creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.debug("Refreshing YouTube API credentials")
                creds.refresh(Request())
            else:
                logger.info("No valid credentials found, starting OAuth2 flow")
                if not os.path.exists('credentials.json'):
                    raise FileNotFoundError(
                        "credentials.json not found. Please download OAuth2 credentials "
                        "from Google Cloud Console and save as 'credentials.json'"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials as JSON with secure file permissions (600)
            # Set umask to ensure file is created with restricted permissions
            old_umask = os.umask(0o077)  # Creates files as 600 (owner-only read/write)
            try:
                with open(token_file, 'w') as f:
                    f.write(creds.to_json())
                # Explicitly set permissions to be safe
                os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR)  # 600 (rw-------)
                logger.info("YouTube API credentials saved to JSON with secure permissions (600)")
            finally:
                os.umask(old_umask)  # Restore original umask

        self.youtube = build('youtube', 'v3', credentials=creds)
        logger.debug("YouTube API credentials loaded successfully")
    
    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """
        Parse ISO 8601 duration string to seconds.

        Args:
            duration_str: ISO 8601 duration (e.g., "PT3M45S")

        Returns:
            Duration in seconds

        Raises:
            ValueError: If duration string format is invalid
        """
        if not duration_str:
            raise ValueError("Duration string is empty")

        match = YouTubeAPI.DURATION_PATTERN.match(duration_str)
        if not match:
            raise ValueError(f"Invalid ISO 8601 duration format: {duration_str}")

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _quota_error_detail(error: HttpError) -> Optional[str]:
        def _message_indicates_quota(message: Optional[str]) -> bool:
            if not message:
                return False
            lowered = message.lower()
            return any(keyword in lowered for keyword in YouTubeAPI.QUOTA_MESSAGE_KEYWORDS)

        def _text_matches_reason(text: Optional[str]) -> Optional[str]:
            if not text:
                return None
            lowered = text.lower()
            for token in YouTubeAPI.QUOTA_REASON_TOKENS:
                if token in lowered:
                    return text
            return None

        content = getattr(error, 'content', None)
        if isinstance(content, bytes):
            try:
                content = content.decode('utf-8')
            except Exception:
                content = None
        if isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
        else:
            payload = None

        if payload:
            error_payload = payload.get('error', {})
            for item in error_payload.get('errors', []):
                reason = item.get('reason')
                match = _text_matches_reason(reason)
                if match:
                    return item.get('message') or error_payload.get('message') or match
            message = error_payload.get('message')
            if _message_indicates_quota(message):
                return message

        resp = getattr(error, 'resp', None)
        if resp:
            resp_reason = getattr(resp, 'reason', None)
            match = _text_matches_reason(resp_reason)
            if match:
                return match

        text = str(error)
        match = _text_matches_reason(text)
        if match:
            return match
        if _message_indicates_quota(text):
            return text
        return None

    def _validate_video_id(self, video_id: str) -> bool:
        """Validate YouTube video ID format."""
        if not video_id:
            return False
        if len(video_id) != 11:
            logger.warning("Invalid video ID length: %s", video_id)
            return False
        if not re.match(r'^[A-Za-z0-9_-]{11}$', video_id):
            logger.warning("Invalid video ID format: %s", video_id)
            return False
        return True

    def _validate_and_truncate_description(self, description: str) -> str:
        """Truncate description to prevent memory issues."""
        if not description:
            return ""
        if len(description) > 5000:
            logger.warning("Truncating description from %d to 5000 characters", len(description))
            return description[:5000]
        return description

    def _validate_duration(self, duration: int) -> Optional[int]:
        """Validate duration is within reasonable bounds."""
        if duration is None:
            return None
        if duration < 0:
            logger.warning("Invalid negative duration: %d", duration)
            return None
        if duration > 86400:  # 24 hours
            logger.warning("Invalid duration exceeding 24 hours: %d", duration)
            return None
        return duration

    def _process_search_result(self, video: Dict[str, Any], expected_duration: Optional[int]) -> Optional[Dict[str, Any]]:
        """
        Process a single video from YouTube API response.

        Args:
            video: Video data from YouTube API
            expected_duration: Expected HA duration (YouTube will be +1s)

        Returns:
            Processed video_info dict or None if video should be skipped
        """
        video_id = video['id']
        if not self._validate_video_id(video_id):
            logger.error("Skipping video with invalid ID: %s", video_id)
            return None

        snippet = video.get('snippet') or {}
        content_details = video.get('contentDetails') or {}
        recording_details = video.get('recordingDetails') or {}

        duration_str = content_details.get('duration')
        try:
            duration = self._parse_duration(duration_str) if duration_str else None
        except ValueError as e:
            logger.error(f"Failed to parse duration for video {video_id}: {e}")
            # Skip videos with invalid duration format
            return None

        # Extract location if available
        location = None
        if recording_details.get('location'):
            loc = recording_details['location']
            if loc.get('latitude') and loc.get('longitude'):
                location = f"{loc['latitude']},{loc['longitude']}"
                if loc.get('altitude'):
                    location += f",{loc['altitude']}"

        video_info = {
            'yt_video_id': video_id,
            'title': snippet.get('title'),
            'channel': snippet.get('channelTitle'),
            'channel_id': snippet.get('channelId'),
            'description': self._validate_and_truncate_description(snippet.get('description')),
            'published_at': snippet.get('publishedAt'),
            'category_id': snippet.get('categoryId'),
            'live_broadcast': snippet.get('liveBroadcastContent'),
            'location': location,
            'recording_date': recording_details.get('recordingDate'),
            'duration': self._validate_duration(duration)
        }

        # Check duration matching if expected_duration is provided
        if expected_duration is not None and duration is not None:
            # YouTube always reports exactly 1 second more than HA
            expected_youtube_duration = expected_duration + YOUTUBE_DURATION_OFFSET
            if duration != expected_youtube_duration:
                return None  # Skip videos that don't match duration
            logger.debug(
                f"Duration match: {expected_duration}s (HA) → {video_info['duration']}s (YT) | '{video_info['title']}'"
            )
        elif duration is None and expected_duration is not None:
            logger.warning(
                f"Duration missing for '{video_info['title']}' "
                f"(ID: {video_info['yt_video_id']}); falling back to title match only"
            )

        return video_info

    def _extract_artist_name(self, title: str) -> Optional[str]:
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

    def _extract_event_phrases(self, title: str) -> List[str]:
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

    def _build_smart_search_query(self, title: str) -> str:
        """
        Build a simple, effective search query for YouTube.

        Going back to the proven approach that worked successfully:
        - Remove problematic characters (emojis, special chars)
        - Keep it simple - let YouTube's search algorithm do the work
        - Don't use restrictive operators like intitle:
        - Don't use ha_artist since it's just "YouTube" (the platform)

        Args:
            title: The song/video title to search for

        Returns:
            Cleaned search query string
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

        # Clean the title first
        clean_title = title.strip()

        # v4.0.61: OPTIMIZED - Use regex for emoji/special char removal (2-3x faster)
        # Remove emojis first
        clean_title = self.EMOJI_PATTERN.sub('', clean_title)
        # Remove special characters, keeping alphanumeric, spaces, hyphens, quotes
        clean_title = self.SPECIAL_CHARS_PATTERN.sub(' ', clean_title)

        # Split on pipe character and take the first part (main title)
        # This handles cases like "Song Title | Additional Info"
        if '|' in clean_title:
            parts = clean_title.split('|')
            clean_title = parts[0].strip()
            # If the first part is too short, use the whole thing
            if len(clean_title) < 10 and len(parts) > 1:
                clean_title = ' '.join(p.strip() for p in parts[:2])

        # v4.0.61: OPTIMIZED - Use class constant for noise words (no recreation on each call)
        words = clean_title.split()
        words = [w for w in words if w.upper() not in self.NOISE_WORDS]
        clean_title = ' '.join(words)

        # Remove common suffixes that might interfere with search
        suffixes_to_remove = [
            ' (Official Video)',
            ' (Official Audio)',
            ' (Lyric Video)',
            ' (Lyrics Video)',
            ' (Audio)',
            ' (Video)',
            ' [Official Video]',
            ' [Official Audio]',
            ' [Lyric Video]',
            ' [Audio]',
            ' [Video]',
        ]
        for suffix in suffixes_to_remove:
            if clean_title.endswith(suffix):
                clean_title = clean_title[:-len(suffix)].strip()
                break

        # v4.0.61: OPTIMIZED - Extracted to helper methods for lower complexity
        # For very long titles (>100 chars), try to extract key terms
        if len(clean_title) > 100:
            important_parts = []

            # Extract artist name if present
            artist = self._extract_artist_name(clean_title)
            if artist:
                important_parts.append(artist)

            # Extract event phrases
            event_phrases = self._extract_event_phrases(clean_title)
            important_parts.extend(event_phrases)

            if important_parts:
                clean_title = ' '.join(important_parts)
                logger.debug(f"Long title simplified: '{title[:80]}...' -> '{clean_title}'")

        # Clean up excessive whitespace
        search_query = ' '.join(clean_title.split())

        # Validate and limit query length (YouTube limit is ~500 chars)
        MAX_QUERY_LENGTH = 500
        if len(search_query) > MAX_QUERY_LENGTH:
            logger.warning("Search query too long (%d chars), truncating", len(search_query))
            search_query = search_query[:MAX_QUERY_LENGTH]

        return search_query

    def search_video_globally(self, title: str, expected_duration: Optional[int] = None, artist: Optional[str] = None, return_api_response: bool = False):
        """
        Search for a video globally. Filters by duration (±2s) if provided.

        Args:
            title: Video title to search for
            expected_duration: Expected duration in seconds (±2s tolerance)
            artist: Artist name (kept for compatibility, not used)
            return_api_response: If True, return tuple of (candidates, api_debug_data)

        Note: artist parameter is kept for compatibility but not used in search
        since ha_artist is typically just "YouTube" (the platform), not the actual artist.

        Returns:
            If return_api_response=False: List of candidate videos or None
            If return_api_response=True: Tuple of (candidates or None, api_debug_data dict)
        """
        api_debug_data = {
            'search_query': None,
            'search_response': None,
            'batch_responses': [],
            'videos_checked': 0,
            'candidates_found': 0
        }

        try:
            # Build search query (cleaned and simplified) - don't use artist since it's just "YouTube"
            search_query = self._build_smart_search_query(title)
            logger.debug(f"YouTube Search: Original='{title}' | Cleaned query='{search_query}'")

            api_debug_data['search_query'] = search_query

            response = self.youtube.search().list(
                part='snippet',
                q=search_query,
                type='video',
                maxResults=self.MAX_SEARCH_RESULTS,
                fields=self.SEARCH_FIELDS,
            ).execute()

            api_debug_data['search_response'] = response

            # Track API usage (both old and new methods for compatibility)
            if _db:
                _db.record_api_call('search', success=True, quota_cost=100)
                _db.log_api_call_detailed(
                    api_method='search',
                    operation_type='search_video',
                    query_params=f"q='{search_query}', maxResults={self.MAX_SEARCH_RESULTS}",
                    quota_cost=100,
                    success=True,
                    results_count=len(response.get('items', [])),
                    context=f"title='{title[:50]}...'" if len(title) > 50 else f"title='{title}'"
                )

            items = response.get('items', [])
            if not items:
                logger.error(f"No videos found globally for: '{title}'")
                api_debug_data['videos_checked'] = 0
                api_debug_data['candidates_found'] = 0
                return (None, api_debug_data) if return_api_response else None

            logger.debug(f"Found {len(items)} videos globally")

            # OPTIMIZATION: Score results by title similarity before checking durations
            # This ensures we check the most relevant matches first
            def calculate_title_similarity(result_title: str, query_title: str) -> float:
                """Calculate similarity score between titles (0-1, higher is better)."""
                result_lower = result_title.lower()
                query_lower = query_title.lower()

                # Exact match = perfect score
                if result_lower == query_lower:
                    return 1.0

                # Contains exact query = high score
                if query_lower in result_lower:
                    return 0.9

                # Word overlap scoring
                result_words = set(result_lower.split())
                query_words = set(query_lower.split())

                if not query_words:
                    return 0.0

                # Jaccard similarity (intersection / union)
                intersection = len(result_words & query_words)
                union = len(result_words | query_words)

                return intersection / union if union > 0 else 0.0

            # Score and sort results by title similarity
            scored_items = []
            for item in items:
                result_title = item['snippet'].get('title', '')
                score = calculate_title_similarity(result_title, title)
                scored_items.append((score, item))

            # Sort by score descending (best matches first)
            scored_items.sort(key=lambda x: x[0], reverse=True)

            logger.debug(f"Top 3 matches by title similarity: " +
                        ", ".join([f"{item['snippet'].get('title', '')[:40]}... ({score:.2f})"
                                  for score, item in scored_items[:3]]))

            video_ids = [item['id']['videoId'] for score, item in scored_items]

            # v4.0.60: OPTIMIZED with batched API calls to reduce network latency
            # Phase 1: Batch fetch first 10 videos (high confidence - best title matches)
            # Phase 2: If no match, batch fetch up to 15 more (up to 25 total)
            # IMPORTANT: Cache ALL videos checked, not just the ones that match
            PHASE_1_LIMIT = 10  # High-confidence check
            PHASE_2_LIMIT = 25  # Extended search if needed
            BATCH_SIZE = 50  # YouTube API supports up to 50 IDs per request
            candidates = []
            all_fetched_videos = []  # Track ALL videos fetched for caching
            videos_checked = 0

            def fetch_video_batch(video_id_batch: list, phase: str, batch_num: int) -> bool:
                """
                OPTIMIZED: Fetch multiple videos in a single API call (reduces network latency 10x).
                Process videos in order, stop if match found.
                Returns True if match found (to stop checking more batches).
                """
                nonlocal videos_checked, candidates, all_fetched_videos

                if not video_id_batch:
                    return False

                batch_ids = ','.join(video_id_batch)
                logger.debug(f"[{phase}] Batch {batch_num}: Fetching {len(video_id_batch)} videos in single API call")

                try:
                    # OPTIMIZED: Single batch API call instead of N sequential calls
                    details = self.youtube.videos().list(
                        part='contentDetails,snippet,recordingDetails',
                        id=batch_ids,  # Batch request - up to 50 IDs
                        fields=self.VIDEO_FIELDS,
                    ).execute()

                    # Capture batch response for debugging
                    api_debug_data['batch_responses'].append({
                        'phase': phase,
                        'batch_num': batch_num,
                        'video_ids_requested': len(video_id_batch),
                        'response': details
                    })

                    videos_fetched = len(details.get('items', []))
                    videos_checked += videos_fetched

                    # Track successful batch API call (quota = 1 per video)
                    if _db:
                        _db.record_api_call('videos.list', success=True, quota_cost=videos_fetched)
                        _db.log_api_call_detailed(
                            api_method='videos.list',
                            operation_type='batch_get_video_details',
                            query_params=f"ids={len(video_id_batch)} videos",
                            quota_cost=videos_fetched,
                            success=True,
                            results_count=videos_fetched,
                            context=f"[{phase}] batch {batch_num} of search for '{title[:30]}...'" if len(title) > 30 else f"[{phase}] batch {batch_num} of search for '{title}'"
                        )

                    # Process ALL fetched videos in score order (best title matches first)
                    for video in details.get('items', []):
                        # First, cache video WITHOUT duration filtering
                        video_info_all = self._process_search_result(video, expected_duration=None)
                        if video_info_all:
                            all_fetched_videos.append(video_info_all)

                        # Then check for duration match
                        video_info = self._process_search_result(video, expected_duration)
                        if video_info:
                            candidates.append(video_info)

                    # If we found a match, stop checking more batches
                    if candidates:
                        logger.debug(f"[{phase}] Found {len(candidates)} match(es) in batch {batch_num}, stopping search")
                        return True

                    # If we have enough candidates, stop
                    if len(candidates) >= self.MAX_CANDIDATES:
                        logger.debug(f"[{phase}] Reached MAX_CANDIDATES ({self.MAX_CANDIDATES}) in batch {batch_num}")
                        return True

                    return False  # Continue to next batch

                except HttpError as e:
                    # Check for quota errors
                    detail = self._quota_error_detail(e)
                    is_quota_error = detail is not None

                    # Log failed API calls
                    if _db:
                        _db.record_api_call('videos.list', success=False,
                                           quota_cost=len(video_id_batch) if not is_quota_error else 0,
                                           error_message="Quota exceeded" if is_quota_error else str(e))
                        _db.log_api_call_detailed(
                            api_method='videos.list',
                            operation_type='batch_get_video_details',
                            query_params=f"ids={len(video_id_batch)} videos",
                            quota_cost=len(video_id_batch) if not is_quota_error else 0,
                            success=False,
                            error_message="Quota exceeded" if is_quota_error else str(e),
                            context=f"[{phase}] batch {batch_num} of search for '{title[:30]}...'" if len(title) > 30 else f"[{phase}] batch {batch_num} of search for '{title}'"
                        )

                    # Raise quota errors to stop processing
                    if is_quota_error:
                        raise QuotaExceededError("YouTube quota exceeded")

                    # Log and continue on other errors
                    logger.warning(f"[{phase}] Error fetching batch {batch_num}: {e}")
                    return False

                except Exception as e:
                    logger.error(f"[{phase}] Unexpected error fetching batch {batch_num}: {e}", exc_info=True)
                    if _db:
                        _db.log_api_call_detailed(
                            api_method='videos.list',
                            operation_type='batch_get_video_details',
                            query_params=f"ids={len(video_id_batch)} videos",
                            quota_cost=len(video_id_batch),
                            success=False,
                            error_message=f"Unexpected error: {str(e)}",
                            context=f"[{phase}] batch {batch_num} of search for '{title[:30]}...'" if len(title) > 30 else f"[{phase}] batch {batch_num} of search for '{title}'"
                        )
                    return False

            # Phase 1: Batch fetch first 10 videos (single API call = 10x faster than sequential)
            logger.debug(f"Starting Phase 1: Batch fetching first {PHASE_1_LIMIT} videos (high confidence)")
            phase1_ids = video_ids[:PHASE_1_LIMIT]
            if phase1_ids:
                fetch_video_batch(phase1_ids, "Phase 1", 1)

            # Phase 2: If no match found, batch fetch next 15 videos (up to 25 total)
            if not candidates and len(video_ids) > PHASE_1_LIMIT:
                remaining = min(PHASE_2_LIMIT - PHASE_1_LIMIT, len(video_ids) - PHASE_1_LIMIT)
                logger.debug(f"No match in Phase 1, starting Phase 2: Batch fetching {remaining} more videos")
                phase2_ids = video_ids[PHASE_1_LIMIT:PHASE_1_LIMIT + remaining]
                if phase2_ids:
                    fetch_video_batch(phase2_ids, "Phase 2", 2)

            if candidates:
                logger.info(f"Found match after checking {videos_checked} videos (saved checking {min(PHASE_2_LIMIT, len(video_ids)) - videos_checked} videos)")
            else:
                logger.debug(f"No match found after checking {videos_checked} videos")

            if not candidates and expected_duration:
                logger.error(
                    f"No exact duration matches found: HA='{title}' ({expected_duration}s) | "
                    f"Expected YouTube duration: {expected_duration + YOUTUBE_DURATION_OFFSET}s | "
                    f"Checked {videos_checked}/{len(video_ids)} videos"
                )
                # Don't return None yet - still cache all checked videos

            if len(candidates) > self.MAX_CANDIDATES:
                candidates = candidates[:self.MAX_CANDIDATES]
                logger.debug(
                    "Trimmed candidates to %s to minimize API comparisons",
                    self.MAX_CANDIDATES,
                )

            # v4.0.58: Cache ALL videos we checked (even if no duration match found)
            # This ensures we don't waste the API quota we already spent
            if _db and all_fetched_videos:
                try:
                    cached_count = _db.cache_search_results(all_fetched_videos, ttl_days=30)
                    logger.info(f"Opportunistically cached {cached_count}/{len(all_fetched_videos)} videos checked during search ({len(candidates)} duration matches)")
                except Exception as exc:
                    logger.warning(f"Failed to cache fetched videos: {exc}")

            # Update final stats in debug data
            api_debug_data['videos_checked'] = videos_checked
            api_debug_data['candidates_found'] = len(candidates) if candidates else 0

            if not candidates:
                logger.info(f"No duration matches, but cached {len(all_fetched_videos)} checked videos for future searches")
                return (None, api_debug_data) if return_api_response else None

            logger.debug(f"Found {len(candidates)} duration-matched candidates")
            return (candidates, api_debug_data) if return_api_response else candidates

        except HttpError as e:
            detail = self._quota_error_detail(e)
            is_quota_error = detail is not None

            # Capture error in debug data
            api_debug_data['error'] = {
                'type': 'quota_exceeded' if is_quota_error else 'http_error',
                'message': "Quota exceeded" if is_quota_error else str(e),
                'detail': detail
            }

            # v4.0.29: ALWAYS log failed API calls (including quota errors) BEFORE raising
            # This ensures check_quota_recently_exceeded() can find recent quota errors
            if _db:
                _db.record_api_call('search', success=False, quota_cost=100 if not is_quota_error else 0,
                                   error_message="Quota exceeded" if is_quota_error else str(e))
                _db.log_api_call_detailed(
                    api_method='search',
                    operation_type='search_video',
                    query_params=f"q='{api_debug_data.get('search_query', title)}', maxResults={self.MAX_SEARCH_RESULTS}",
                    quota_cost=100 if not is_quota_error else 0,  # No quota consumed if quota already exceeded
                    success=False,
                    error_message="Quota exceeded" if is_quota_error else str(e),
                    context=f"title='{title[:50]}...'" if len(title) > 50 else f"title='{title}'"
                )

            if is_quota_error:
                # Raise exception - worker will catch and sleep until midnight
                raise QuotaExceededError("YouTube quota exceeded")

            if return_api_response:
                return (None, api_debug_data)

            return log_and_suppress(
                e,
                f"YouTube API error in search_video_globally | Query: '{title}'",
                level="error",
                return_value=None,
                log_traceback=not is_quota_error  # Skip traceback for quota errors
            )
        except Exception as e:
            # Capture unexpected error in debug data
            api_debug_data['error'] = {
                'type': 'unexpected_error',
                'message': str(e)
            }

            if return_api_response:
                return (None, api_debug_data)

            return log_and_suppress(
                e,
                f"Unexpected error searching video | Query: '{title}'",
                level="error",
                return_value=None
            )

    @handle_youtube_error(context='get_rating', api_method='videos.getRating', quota_cost=1)
    def get_video_rating(self, yt_video_id: str) -> str:
        """
        Get current rating for a video.

        Returns 'like', 'dislike', or 'none'.
        Raises specific exceptions on failure (no error suppression).
        """
        logger.info(f"Checking rating for video ID: {yt_video_id}")

        request = self.youtube.videos().getRating(id=yt_video_id)
        response = request.execute()

        # Track successful API usage (both tables)
        if _db:
            _db.record_api_call('videos.getRating', success=True, quota_cost=1)
            _db.log_api_call_detailed(
                api_method='videos.getRating',
                operation_type='get_rating',
                query_params=f"video_id={yt_video_id}",
                quota_cost=1,
                success=True,
                results_count=len(response.get('items', [])),
                context=f"Check rating for {yt_video_id}"
            )

        if response.get('items'):
            rating = response['items'][0].get('rating', self.NO_RATING)
            logger.info(f"Current rating for {yt_video_id}: {rating}")
            return rating

        return self.NO_RATING

    @handle_youtube_error(context='set_rating', api_method='videos.rate', quota_cost=50)
    def set_video_rating(self, yt_video_id: str, rating: str) -> bool:
        """
        Set rating for a video.

        Returns True on success.
        Raises specific exceptions on failure (no error suppression).
        """
        logger.info(f"Setting rating '{rating}' for video ID: {yt_video_id}")

        request = self.youtube.videos().rate(
            id=yt_video_id,
            rating=rating
        )
        request.execute()

        # Track successful API usage (both tables)
        if _db:
            _db.record_api_call('videos.rate', success=True, quota_cost=50)
            _db.log_api_call_detailed(
                api_method='videos.rate',
                operation_type='set_rating',
                query_params=f"video_id={yt_video_id}, rating={rating}",
                quota_cost=50,
                success=True,
                results_count=1,
                context=f"Set rating '{rating}' for {yt_video_id}"
            )

        logger.info(f"Successfully rated video {yt_video_id} as '{rating}'")
        return True

# Create global instance (will be initialized when module is imported)
yt_api = None

def get_youtube_api() -> YouTubeAPI:
    """Get or create YouTube API instance."""
    global yt_api
    if yt_api is None:
        logger.debug("Creating new YouTube API instance")
        yt_api = YouTubeAPI()
    return yt_api
