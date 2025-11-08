import json
import os
import re
import stat
import traceback
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
    SEARCH_FIELDS = 'items(id/videoId)'
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
                logger.info("Loaded YouTube API credentials from JSON")
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
                    logger.info("Loaded YouTube API credentials from JSON (permission check failed)")
                except Exception as inner_e:
                    logger.error(f"Failed to load credentials: {inner_e}")
                    creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing YouTube API credentials")
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
        logger.info("YouTube API authenticated successfully")
    
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
        import unicodedata

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

        # Remove emojis and special Unicode characters that can break search
        # This removes emoji, symbols, and other special chars while keeping regular text
        clean_title = ''.join(
            char for char in clean_title
            if unicodedata.category(char)[0] in ['L', 'N', 'Z', 'P', 'S']
            and ord(char) < 0x1F600  # Exclude emoji range
        )

        # Split on pipe character and take the first part (main title)
        # This handles cases like "Song Title | Additional Info"
        if '|' in clean_title:
            parts = clean_title.split('|')
            clean_title = parts[0].strip()
            # If the first part is too short, use the whole thing
            if len(clean_title) < 10 and len(parts) > 1:
                clean_title = ' '.join(p.strip() for p in parts[:2])

        # Remove noise words that don't help search accuracy
        noise_words = [
            'FULL', 'HD', 'HQ', '4K', '8K', 'OFFICIAL',
            'NEW', 'EXCLUSIVE', 'PREMIERE', 'ORIGINAL',
        ]
        words = clean_title.split()
        words = [w for w in words if w.upper() not in noise_words]
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

        # For very long titles (>100 chars), try to extract key terms
        # Focus on artist names and significant event keywords
        if len(clean_title) > 100:
            # Extract artist name if at beginning
            potential_artist = clean_title.split("'s ")[0] if "'s " in clean_title else None

            # Look for event keywords (concerts, shows, performances)
            event_keywords = ['Super Bowl', 'Halftime Show', 'Concert', 'Live', 'Performance',
                            'Awards', 'Festival', 'Tour', 'Show']
            important_parts = []

            if potential_artist and len(potential_artist) < 30:
                important_parts.append(potential_artist)

            for keyword in event_keywords:
                if keyword in clean_title:
                    # Find the phrase containing this keyword
                    words = clean_title.split()
                    for i, word in enumerate(words):
                        if keyword in ' '.join(words[i:i+len(keyword.split())]):
                            # Take keyword plus surrounding context (up to 5 words each side)
                            start = max(0, i - 2)
                            end = min(len(words), i + len(keyword.split()) + 2)
                            phrase = ' '.join(words[start:end])
                            important_parts.append(phrase)
                            break

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

    def search_video_globally(self, title: str, expected_duration: Optional[int] = None, artist: Optional[str] = None) -> Optional[List[Dict]]:
        """
        Search for a video globally. Filters by duration (±2s) if provided.

        Note: artist parameter is kept for compatibility but not used in search
        since ha_artist is typically just "YouTube" (the platform), not the actual artist.
        """
        try:
            # Build search query (cleaned and simplified) - don't use artist since it's just "YouTube"
            search_query = self._build_smart_search_query(title)
            logger.debug(f"YouTube Search: Original='{title}' | Cleaned query='{search_query}'")

            response = self.youtube.search().list(
                part='snippet',
                q=search_query,
                type='video',
                maxResults=self.MAX_SEARCH_RESULTS,
                fields=self.SEARCH_FIELDS,
            ).execute()

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
                return None

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

            # v4.0.3: Two-phase matching strategy for quota optimization
            # Phase 1: Check first 10 videos (high confidence - best title matches)
            #          If match found with duration, stop (high confidence match)
            # Phase 2: If no match in first 10, continue up to 25 total
            # This balances quota usage with match quality
            PHASE_1_LIMIT = 10  # High-confidence check
            PHASE_2_LIMIT = 25  # Extended search if needed
            candidates = []
            videos_checked = 0

            def check_video(idx: int, video_id: str, phase: str) -> bool:
                """
                Check a single video for duration match.
                Returns True if match found (to stop early), False to continue.
                """
                nonlocal videos_checked, candidates

                logger.debug(f"[{phase}] Checking video {idx+1}: {video_id}")

                try:
                    # Fetch details for this single video
                    details = self.youtube.videos().list(
                        part='contentDetails,snippet,recordingDetails',
                        id=video_id,
                        fields=self.VIDEO_FIELDS,
                    ).execute()

                    # Track successful API call
                    if _db:
                        _db.record_api_call('videos.list', success=True, quota_cost=1)
                        _db.log_api_call_detailed(
                            api_method='videos.list',
                            operation_type='get_video_details',
                            query_params=f"id={video_id}",
                            quota_cost=1,
                            success=True,
                            results_count=len(details.get('items', [])),
                            context=f"[{phase}] video {idx+1} of search for '{title[:30]}...'" if len(title) > 30 else f"[{phase}] video {idx+1} of search for '{title}'"
                        )

                    videos_checked += 1

                    # Process video and check for duration match
                    for video in details.get('items', []):
                        video_info = self._process_search_result(video, expected_duration)
                        if video_info:
                            candidates.append(video_info)

                    # If we found a match, stop early
                    if candidates:
                        logger.debug(f"[{phase}] Found {len(candidates)} match(es), stopping search")
                        return True  # Stop checking

                    # If we have enough candidates, stop
                    if len(candidates) >= self.MAX_CANDIDATES:
                        logger.debug(f"[{phase}] Reached MAX_CANDIDATES ({self.MAX_CANDIDATES}), stopping")
                        return True  # Stop checking

                    return False  # Continue checking

                except HttpError as e:
                    # Handle quota errors by re-raising
                    detail = self._quota_error_detail(e)
                    if detail is not None:
                        raise QuotaExceededError("YouTube quota exceeded")

                    # v4.0.3: Track failed API call (non-quota errors)
                    if _db:
                        _db.log_api_call_detailed(
                            api_method='videos.list',
                            operation_type='get_video_details',
                            query_params=f"id={video_id}",
                            quota_cost=1,
                            success=False,
                            error_message=str(e),
                            context=f"[{phase}] video {idx+1} of search for '{title[:30]}...'" if len(title) > 30 else f"[{phase}] video {idx+1} of search for '{title}'"
                        )

                    # Log and continue on other errors
                    logger.warning(f"[{phase}] Error fetching video {video_id}: {e}")
                    return False  # Continue checking

                except Exception as e:
                    # v4.0.3: Handle unexpected non-HTTP errors (network issues, JSON errors, etc.)
                    logger.error(f"[{phase}] Unexpected error fetching video {video_id}: {e}", exc_info=True)

                    if _db:
                        _db.log_api_call_detailed(
                            api_method='videos.list',
                            operation_type='get_video_details',
                            query_params=f"id={video_id}",
                            quota_cost=1,
                            success=False,
                            error_message=f"Unexpected error: {str(e)}",
                            context=f"[{phase}] video {idx+1} of search for '{title[:30]}...'" if len(title) > 30 else f"[{phase}] video {idx+1} of search for '{title}'"
                        )

                    return False  # Continue checking

            # Phase 1: Check first 10 videos (high confidence)
            logger.debug(f"Starting Phase 1: Checking first {PHASE_1_LIMIT} videos (high confidence)")
            for idx, video_id in enumerate(video_ids[:PHASE_1_LIMIT]):
                if check_video(idx, video_id, "Phase 1"):
                    break  # Match found, stop early

            # Phase 2: If no match found, continue up to 25 total
            if not candidates and len(video_ids) > PHASE_1_LIMIT:
                remaining = min(PHASE_2_LIMIT - PHASE_1_LIMIT, len(video_ids) - PHASE_1_LIMIT)
                logger.debug(f"No match in Phase 1, starting Phase 2: Checking {remaining} more videos (up to {PHASE_2_LIMIT} total)")

                for idx in range(PHASE_1_LIMIT, min(PHASE_2_LIMIT, len(video_ids))):
                    video_id = video_ids[idx]
                    if check_video(idx, video_id, "Phase 2"):
                        break  # Match found, stop early

            if candidates:
                logger.debug(f"Search complete: Found match after checking {videos_checked} videos (saved checking {min(PHASE_2_LIMIT, len(video_ids)) - videos_checked} videos)")
            else:
                logger.debug(f"Search complete: No match found after checking {videos_checked} videos")

            if not candidates and expected_duration:
                logger.error(
                    f"No exact duration matches found: HA='{title}' ({expected_duration}s) | "
                    f"Expected YouTube duration: {expected_duration + YOUTUBE_DURATION_OFFSET}s | "
                    f"Checked {videos_checked}/{len(video_ids)} videos"
                )
                return None

            if len(candidates) > self.MAX_CANDIDATES:
                candidates = candidates[:self.MAX_CANDIDATES]
                logger.debug(
                    "Trimmed candidates to %s to minimize API comparisons",
                    self.MAX_CANDIDATES,
                )

            logger.debug(f"Found {len(candidates)} duration-matched candidates")
            return candidates

        except HttpError as e:
            detail = self._quota_error_detail(e)
            is_quota_error = detail is not None
            if is_quota_error:
                # Raise exception - worker will catch and sleep for 1 hour
                raise QuotaExceededError("YouTube quota exceeded")

            # Track failed API call
            if _db:
                _db.log_api_call_detailed(
                    api_method='search',
                    operation_type='search_video',
                    query_params=f"q='{search_query}', maxResults={self.MAX_SEARCH_RESULTS}",
                    quota_cost=100 if not is_quota_error else 0,  # No quota consumed if quota already exceeded
                    success=False,
                    error_message=str(e),
                    context=f"title='{title[:50]}...'" if len(title) > 50 else f"title='{title}'"
                )

            return log_and_suppress(
                e,
                f"YouTube API error in search_video_globally | Query: '{title}'",
                level="error",
                return_value=None,
                log_traceback=not is_quota_error  # Skip traceback for quota errors
            )
        except Exception as e:
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

        # Track successful API usage
        if _db:
            _db.record_api_call('videos.getRating', success=True, quota_cost=1)

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

        # Track successful API usage
        if _db:
            _db.record_api_call('videos.rate', success=True, quota_cost=50)

        logger.info(f"Successfully rated video {yt_video_id} as '{rating}'")
        return True

# Create global instance (will be initialized when module is imported)
yt_api = None

def get_youtube_api() -> YouTubeAPI:
    """Get or create YouTube API instance."""
    global yt_api
    if yt_api is None:
        logger.info("Creating new YouTube API instance")
        yt_api = YouTubeAPI()
    return yt_api
