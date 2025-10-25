import os
import pickle
import re
import traceback
from typing import Optional, List, Dict
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from logger import logger

class YouTubeAPI:
    """Interface to YouTube Data API v3."""

    SCOPES = ['https://www.googleapis.com/auth/youtube']
    DURATION_PATTERN = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
    NO_RATING = 'none'  # YouTube API rating value for unrated videos
    
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

    def search_video_globally(self, title: str, expected_duration: Optional[int] = None) -> Optional[List[Dict]]:
        """Search for a video globally. Filters by duration (±2s) if provided."""
        try:
            logger.info(f"Searching globally for: \"{title}\"")

            response = self.youtube.search().list(
                part='snippet', q=title, type='video', maxResults=50
            ).execute()

            items = response.get('items', [])
            if not items:
                logger.error(f"No videos found globally for: '{title}'")
                return None

            logger.info(f"Found {len(items)} videos globally")

            video_ids = [item['id']['videoId'] for item in items]
            details = self.youtube.videos().list(
                part='contentDetails,snippet', id=','.join(video_ids)
            ).execute()

            candidates = []
            for video in details.get('items', []):
                content_details = video.get('contentDetails') or {}
                duration_str = content_details.get('duration')
                duration = self._parse_duration(duration_str) if duration_str else None
                video_info = {
                    'video_id': video['id'],
                    'title': video['snippet']['title'],
                    'channel': video['snippet']['channelTitle'],
                    'duration': duration
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
                            f"(ID: {video_info['video_id']}); falling back to title match only"
                        )
                    candidates.append(video_info)

            if not candidates and expected_duration:
                logger.error(f"No videos match duration {expected_duration}s (±2s) | Query: '{title}'")
                return None

            logger.info(f"Found {len(candidates)} duration-matched candidates")
            return candidates

        except HttpError as e:
            logger.error(f"YouTube API error in search_video_globally | Query: '{title}' | Error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error searching video | Query: '{title}' | Error: {str(e)}")
            logger.debug(f"Traceback for search error: {traceback.format_exc()}")
            return None

    def get_video_rating(self, video_id: str) -> str:
        """Get current rating for a video. Returns 'like', 'dislike', or 'none'."""
        try:
            logger.info(f"Checking rating for video ID: {video_id}")

            request = self.youtube.videos().getRating(id=video_id)
            response = request.execute()

            if response.get('items'):
                rating = response['items'][0].get('rating', self.NO_RATING)
                logger.info(f"Current rating for {video_id}: {rating}")
                return rating

            return self.NO_RATING

        except HttpError as e:
            logger.error(f"YouTube API error getting rating | Video ID: {video_id} | Error: {str(e)}")
            return self.NO_RATING
        except Exception as e:
            logger.error(f"Unexpected error getting video rating | Video ID: {video_id} | Error: {str(e)}")
            logger.debug(f"Traceback for get_video_rating error: {traceback.format_exc()}")
            return self.NO_RATING

    def set_video_rating(self, video_id: str, rating: str) -> bool:
        """Set rating for a video. Returns True on success, False on failure."""
        try:
            logger.info(f"Setting rating '{rating}' for video ID: {video_id}")

            request = self.youtube.videos().rate(
                id=video_id,
                rating=rating
            )
            request.execute()

            logger.info(f"Successfully rated video {video_id} as '{rating}'")
            return True

        except HttpError as e:
            logger.error(f"YouTube API error setting rating | Video ID: {video_id} | Rating: {rating} | Error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error setting video rating | Video ID: {video_id} | Rating: {rating} | Error: {str(e)}")
            logger.debug(f"Traceback for set_video_rating error: {traceback.format_exc()}")
            return False

# Create global instance (will be initialized when module is imported)
yt_api = None

def get_youtube_api() -> YouTubeAPI:
    """Get or create YouTube API instance."""
    global yt_api
    if yt_api is None:
        yt_api = YouTubeAPI()
    return yt_api
