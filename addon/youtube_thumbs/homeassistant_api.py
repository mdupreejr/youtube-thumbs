 import requests
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv
from logger import logger

load_dotenv()

class HomeAssistantAPI:
    """Interface to Home Assistant API."""
    
    def __init__(self) -> None:
        self.url = os.getenv('HOME_ASSISTANT_URL')
        # Use SUPERVISOR_TOKEN if available (add-on environment), otherwise use HOME_ASSISTANT_TOKEN
        self.token = os.getenv('SUPERVISOR_TOKEN') or os.getenv('HOME_ASSISTANT_TOKEN')
        self.entity = os.getenv('MEDIA_PLAYER_ENTITY')
        
        if self.token and os.getenv('SUPERVISOR_TOKEN'):
            logger.info("Using Supervisor token for authentication")
        elif self.token:
            logger.info("Using long-lived access token for authentication")
        
        if not all([self.url, self.token, self.entity]):
            raise ValueError("Missing Home Assistant configuration in .env file")
        
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        # Use session for connection pooling and performance
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def get_current_media(self) -> Optional[Dict[str, Any]]:
        """
        Get current playing media information.
        Returns dict with title, artist, album or None if nothing playing.
        """
        try:
            logger.info(f"Fetching current media from Home Assistant entity: {self.entity}")
            
            response = self.session.get(
                f"{self.url}/api/states/{self.entity}",
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Home Assistant API error: HTTP {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            state = data.get('state')
            
            if state != 'playing':
                logger.warning(f"Media player state is '{state}', not 'playing'")
                return None
            
            attributes = data.get('attributes', {})
            media_title = attributes.get('media_title')
            media_artist = attributes.get('media_artist')
            media_album = attributes.get('media_album')
            
            if not media_title:
                logger.warning("No media_title found in Home Assistant response")
                return None
            
            media_duration = attributes.get('media_duration')
            
            media_info = {
                'title': media_title,
                'artist': media_artist or 'Unknown',
                'album': media_album or 'Unknown',
                'duration': media_duration
            }
            
            logger.info(f"Current media: \"{media_title}\" by \"{media_artist}\" ({media_duration}s)")
            return media_info
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Home Assistant API connection error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error fetching current media: {str(e)}")
            return None

# Create global instance
ha_api = HomeAssistantAPI()
