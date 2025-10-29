import json
import os
import pickle
import re
import traceback
from typing import Optional, List, Dict, Any, Tuple
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from logger import logger
from quota_guard import quota_guard
from error_handler import handle_api_error, log_and_suppress, validate_environment_variable
from decorators import handle_youtube_error

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

        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)

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

            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
            logger.info("YouTube API credentials saved")

        self.youtube = build('youtube', 'v3', credentials=creds)
        logger.info("YouTube API authenticated successfully")
    
    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """Parse ISO 8601 duration string to seconds."""
        match = YouTubeAPI.DURATION_PATTERN.match(duration_str)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            seconds = int(match.group(3) or 0)
            return hours * 3600 + minutes * 60 + seconds
        return 0

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

    def _build_smart_search_query(self, title: str, artist: Optional[str] = None) -> str:
        """
        Build a smart search query using YouTube search operators.

        Strategies:
        1. Use intitle: for better title matching
        2. Use quotes for exact phrase matching when appropriate
        3. Include artist/channel information when available
        4. Handle special characters and formatting

        Args:
            title: The song/video title to search for
            artist: Optional artist/channel name

        Returns:
            Optimized search query string
        """
        # Clean the title first
        clean_title = title.strip()

        # Remove ALL quotes to prevent injection and query malformation
        clean_title = clean_title.replace('"', '').replace("'", '')

        # Remove YouTube search operators to prevent injection
        youtube_operators = ['intitle:', 'inurl:', 'site:', 'filetype:', 'inauthor:', 'allintitle:']
        for operator in youtube_operators:
            clean_title = clean_title.replace(operator, '')

        # Remove common suffixes that might interfere with search
        suffixes_to_remove = [
            ' (Official Video)',
            ' (Official Audio)',
            ' (Lyric Video)',
            ' (Audio)',
            ' [Official Video]',
            ' [Official Audio]',
            ' [Lyric Video]',
            ' [Audio]',
        ]
        for suffix in suffixes_to_remove:
            if clean_title.endswith(suffix):
                clean_title = clean_title[:-len(suffix)].strip()
                break

        # Build query components
        query_parts = []

        # Strategy 1: Use intitle for exact title matching
        # Since we removed all quotes, check for complexity differently
        if ' ' in clean_title or any(c in clean_title for c in ['(', ')', '[', ']', '-']):
            # For complex titles, use intitle with quotes for exact phrase
            query_parts.append(f'intitle:"{clean_title}"')
        else:
            # For simple titles
            query_parts.append(f'intitle:{clean_title}')

        # Strategy 2: Add artist/channel if provided
        if artist:
            # Clean artist name - remove quotes and operators
            clean_artist = artist.strip().replace('"', '').replace("'", '')
            for operator in youtube_operators:
                clean_artist = clean_artist.replace(operator, '')

            # Remove common prefixes/suffixes from artist
            if clean_artist.lower().startswith('the '):
                alt_artist = clean_artist[4:]
            else:
                alt_artist = clean_artist

            # Add artist as additional search term (not in intitle)
            # This helps find videos on the artist's channel
            if ' ' in clean_artist:
                query_parts.append(f'"{clean_artist}"')
            else:
                query_parts.append(clean_artist)

        # Join query parts
        search_query = ' '.join(query_parts)

        # Validate and limit query length (YouTube limit is ~500 chars)
        MAX_QUERY_LENGTH = 500
        if len(search_query) > MAX_QUERY_LENGTH:
            logger.warning("Search query too long (%d chars), truncating", len(search_query))
            # Fallback to simpler query with intitle preserved
            if artist and len(clean_artist) < 50:
                search_query = f'intitle:"{clean_title[:200]}" {clean_artist}'
            else:
                search_query = f'intitle:"{clean_title[:250]}"'

            # Final truncation if still too long
            if len(search_query) > MAX_QUERY_LENGTH:
                search_query = search_query[:MAX_QUERY_LENGTH]

        return search_query

    def search_video_globally(self, title: str, expected_duration: Optional[int] = None, artist: Optional[str] = None) -> Optional[List[Dict]]:
        """
        Search for a video globally. Filters by duration (±2s) if provided.
        Uses smart query building with exact phrase matching and intitle parameter.
        """
        if quota_guard.is_blocked():
            logger.info(
                "Quota cooldown active; skipping YouTube global search for '%s': %s",
                title,
                quota_guard.describe_block(),
            )
            return None
        try:
            # Build smart search query
            search_query = self._build_smart_search_query(title, artist)
            logger.info(f"Searching globally with smart query: {search_query}")

            response = self.youtube.search().list(
                part='snippet',
                q=search_query,
                type='video',
                maxResults=self.MAX_SEARCH_RESULTS,
                fields=self.SEARCH_FIELDS,
            ).execute()

            items = response.get('items', [])
            if not items:
                logger.error(f"No videos found globally for: '{title}'")
                return None

            logger.info(f"Found {len(items)} videos globally")

            video_ids = [item['id']['videoId'] for item in items]
            details = self.youtube.videos().list(
                part='contentDetails,snippet,recordingDetails',
                id=','.join(video_ids),
                fields=self.VIDEO_FIELDS,
            ).execute()

            candidates = []
            for video in details.get('items', []):
                video_id = video['id']
                if not self._validate_video_id(video_id):
                    logger.error("Skipping video with invalid ID: %s", video_id)
                    continue

                snippet = video.get('snippet') or {}
                content_details = video.get('contentDetails') or {}
                recording_details = video.get('recordingDetails') or {}

                duration_str = content_details.get('duration')
                duration = self._parse_duration(duration_str) if duration_str else None

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

                if expected_duration is not None and duration is not None:
                    diff = abs(duration - expected_duration)
                    if diff <= 2:
                        logger.debug(
                            f"Duration match: '{video_info['title']}' on '{video_info['channel']}' - "
                            f"{duration}s (diff: {diff}s)"
                        )
                        candidates.append(video_info)
                else:
                    if duration is None and expected_duration is not None:
                        logger.warning(
                            f"Duration missing for '{video_info['title']}' "
                            f"(ID: {video_info['yt_video_id']}); falling back to title match only"
                        )
                    candidates.append(video_info)
                if len(candidates) >= self.MAX_CANDIDATES:
                    break

            if not candidates and expected_duration:
                logger.error(f"No videos match duration {expected_duration}s (±2s) | Query: '{title}'")
                return None

            if len(candidates) > self.MAX_CANDIDATES:
                candidates = candidates[:self.MAX_CANDIDATES]
                logger.debug(
                    "Trimmed candidates to %s to minimize API comparisons",
                    self.MAX_CANDIDATES,
                )

            logger.info(f"Found {len(candidates)} duration-matched candidates")
            # Record successful API call for quota recovery tracking
            quota_guard.record_success()
            return candidates

        except HttpError as e:
            detail = self._quota_error_detail(e)
            if detail is not None:
                quota_guard.trip('quotaExceeded', context='search', detail=detail)
            return log_and_suppress(
                e,
                f"YouTube API error in search_video_globally | Query: '{title}'",
                level="error",
                return_value=None
            )
        except Exception as e:
            return log_and_suppress(
                e,
                f"Unexpected error searching video | Query: '{title}'",
                level="error",
                return_value=None
            )

    @handle_youtube_error(context='get_rating', return_value='none')
    def get_video_rating(self, yt_video_id: str) -> str:
        """Get current rating for a video. Returns 'like', 'dislike', or 'none'."""
        if quota_guard.is_blocked():
            logger.info(
                "Quota cooldown active; skipping get_video_rating for %s: %s",
                yt_video_id,
                quota_guard.describe_block(),
            )
            return self.NO_RATING

        logger.info(f"Checking rating for video ID: {yt_video_id}")

        request = self.youtube.videos().getRating(id=yt_video_id)
        response = request.execute()

        if response.get('items'):
            rating = response['items'][0].get('rating', self.NO_RATING)
            logger.info(f"Current rating for {yt_video_id}: {rating}")
            # Record successful API call for quota recovery tracking
            quota_guard.record_success()
            return rating

        # Record successful API call even when no items returned
        quota_guard.record_success()
        return self.NO_RATING

    @handle_youtube_error(context='set_rating', return_value=False)
    def set_video_rating(self, yt_video_id: str, rating: str) -> bool:
        """Set rating for a video. Returns True on success, False on failure."""
        if quota_guard.is_blocked():
            logger.info(
                "Quota cooldown active; skipping set_video_rating for %s (%s): %s",
                yt_video_id,
                rating,
                quota_guard.describe_block(),
            )
            return False

        logger.info(f"Setting rating '{rating}' for video ID: {yt_video_id}")

        request = self.youtube.videos().rate(
            id=yt_video_id,
            rating=rating
        )
        request.execute()

        logger.info(f"Successfully rated video {yt_video_id} as '{rating}'")
        # Record successful API call for quota recovery tracking
        quota_guard.record_success()
        return True

    def batch_get_videos(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch video details for multiple videos in a single API call.
        YouTube API allows up to 50 video IDs per call.

        Args:
            video_ids: List of YouTube video IDs to fetch

        Returns:
            Dict mapping video ID to video details (or None if not found)
        """
        if not video_ids:
            return {}

        if quota_guard.is_blocked():
            logger.info(
                "Quota cooldown active; skipping batch_get_videos for %d videos: %s",
                len(video_ids),
                quota_guard.describe_block(),
            )
            return {}

        # YouTube API allows max 50 IDs per call
        batch_size = 50
        all_videos = {}

        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i:i + batch_size]
            try:
                logger.info(f"Fetching batch of {len(batch)} videos")

                request = self.youtube.videos().list(
                    part='snippet,contentDetails',
                    id=','.join(batch)
                )
                response = request.execute()

                # Process response
                for item in response.get('items', []):
                    video_id = item['id']
                    snippet = item.get('snippet', {})
                    content_details = item.get('contentDetails', {})

                    all_videos[video_id] = {
                        'yt_video_id': video_id,
                        'yt_title': snippet.get('title'),
                        'yt_channel': snippet.get('channelTitle'),
                        'yt_channel_id': snippet.get('channelId'),
                        'yt_description': snippet.get('description'),
                        'yt_published_at': snippet.get('publishedAt'),
                        'yt_category_id': snippet.get('categoryId'),
                        'yt_live_broadcast': snippet.get('liveBroadcastContent'),
                        'yt_duration': self._parse_duration(content_details.get('duration')),
                        'yt_url': f"https://www.youtube.com/watch?v={video_id}",
                        'exists': True
                    }

                # Mark videos not found in response
                for vid in batch:
                    if vid not in all_videos:
                        all_videos[vid] = {'yt_video_id': vid, 'exists': False}

                # Record successful API call for quota recovery tracking
                quota_guard.record_success()
                logger.info(f"Successfully fetched {len(response.get('items', []))} videos from batch of {len(batch)}")

            except HttpError as e:
                detail = self._quota_error_detail(e)
                if detail is not None:
                    quota_guard.trip('quotaExceeded', context='batch_get_videos', detail=detail)
                log_and_suppress(
                    e,
                    f"YouTube API error fetching batch of videos",
                    level="error"
                )
                # Return partial results if we hit quota
                break
            except Exception as e:
                log_and_suppress(
                    e,
                    f"Unexpected error fetching batch of videos",
                    level="error"
                )
                # Continue with next batch on other errors
                continue

        return all_videos

    def batch_set_ratings(self, ratings: List[Tuple[str, str]]) -> Dict[str, bool]:
        """
        Set ratings for multiple videos. Optimized with early exit on quota exhaustion.

        Args:
            ratings: List of (video_id, rating) tuples

        Returns:
            Dict mapping video ID to success status
        """
        if not ratings:
            return {}

        results = {}

        # Check quota before starting
        if quota_guard.is_blocked():
            logger.info("Quota blocked, returning all failures for batch rating")
            return {vid: False for vid, _ in ratings}

        # Process ratings one by one with early exit on quota exhaustion
        for video_id, rating in ratings:
            # Check quota before each rating
            if quota_guard.is_blocked():
                logger.warning("Quota exhausted mid-batch at video %s, stopping", video_id)
                # Mark remaining as failed
                results[video_id] = False
                continue

            # Try to rate the video
            success = self.set_video_rating(video_id, rating)
            results[video_id] = success

            # Early exit if we hit quota (set_video_rating will have tripped quota_guard)
            if not success and quota_guard.is_blocked():
                logger.warning("Quota exhausted after rating %s, marking remaining as failed", video_id)
                # Mark any remaining ratings as failed
                for remaining_vid, _ in ratings:
                    if remaining_vid not in results:
                        results[remaining_vid] = False
                break

        return results

# Create global instance (will be initialized when module is imported)
yt_api = None

def get_youtube_api() -> YouTubeAPI:
    """Get or create YouTube API instance."""
    global yt_api
    if yt_api is None:
        yt_api = YouTubeAPI()
    return yt_api
