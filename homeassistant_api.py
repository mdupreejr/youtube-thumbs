import requests
from typing import Optional, Dict, Any
import os
from logger import logger

class HomeAssistantAPI:
    """Interface to Home Assistant API."""
    
    def __init__(self) -> None:
        self.url = os.getenv('HOME_ASSISTANT_URL')
        self.token = os.getenv('SUPERVISOR_TOKEN') or os.getenv('HOME_ASSISTANT_TOKEN')
        self.entity = os.getenv('MEDIA_PLAYER_ENTITY')

        if self.token and os.getenv('SUPERVISOR_TOKEN'):
            logger.info("Using Supervisor token for authentication")
        elif self.token:
            logger.info("Using long-lived access token for authentication")

        if not all([self.url, self.token, self.entity]):
            raise ValueError("Missing Home Assistant configuration. Please check add-on configuration.")

        logger.info(f"Home Assistant URL: {self.url}")
        logger.info(f"Media Player Entity: {self.entity}")

        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def get_current_media(self) -> Optional[Dict[str, Any]]:
        """Get current playing media information."""
        try:
            logger.debug(f"Fetching current media from Home Assistant entity: {self.entity}")

            url = f"{self.url}/api/states/{self.entity}"

            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                logger.error(f"Home Assistant API error: HTTP {response.status_code} - {response.text[:200]}")
                logger.error(f"Request URL: {url}")
                return None

            # Check if response is actually JSON (not HTML error page)
            content_type = response.headers.get('content-type', '')
            if 'application/json' not in content_type:
                logger.error(
                    f"Home Assistant API returned non-JSON response (Content-Type: {content_type}). "
                    f"This usually indicates a proxy/timeout error. Response preview: {response.text[:200]}"
                )
                return None

            data = response.json()
            state = data.get('state')
            
            if state != 'playing':
                logger.debug(f"Media player state is '{state}', not 'playing'")
                return None
            
            attributes = data.get('attributes', {})

            # Log ALL attributes to see what AppleTV is actually sending
            logger.debug("=== ALL Home Assistant attributes ===")
            for key, value in attributes.items():
                # Truncate long values for readability
                value_str = str(value)
                if len(value_str) > 100:
                    value_str = value_str[:100] + "..."
                logger.debug(f"  {key}: {value_str}")
            logger.debug("=== End attributes ===")

            media_title = attributes.get('media_title')
            media_artist = attributes.get('media_artist')
            app_name = attributes.get('app_name')
            media_duration = attributes.get('media_duration')

            # Check for YouTube video ID in various possible fields
            media_content_id = attributes.get('media_content_id')
            entity_picture = attributes.get('entity_picture')
            media_album_name = attributes.get('media_album_name')

            if media_content_id:
                logger.debug(f"Found media_content_id: {media_content_id}")
            if entity_picture:
                logger.debug(f"Found entity_picture: {entity_picture}")

            # Debug logging to understand what HA is actually sending
            logger.debug(
                "Raw HA attributes: media_title='%s', media_artist='%s', "
                "app_name='%s', duration=%s",
                media_title,
                media_artist,
                app_name,
                media_duration
            )

            if not media_title:
                logger.warning("No media_title found in Home Assistant response")
                return None

            # Only return data if it's from YouTube
            if not app_name or 'youtube' not in app_name.lower():
                logger.debug(f"Skipping non-YouTube content from app: {app_name}")
                return None

            media_info = {
                'title': media_title,
                'artist': media_artist or 'Unknown',
                'app_name': app_name,
                'duration': media_duration
            }

            logger.debug(
                "Current YouTube media: \"%s\" (%ss)",
                media_title,
                media_duration
            )
            return media_info
            
        except requests.exceptions.Timeout:
            logger.warning("Home Assistant API request timed out after 10 seconds")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Home Assistant API connection error: {str(e)}")
            return None
        except ValueError as e:
            # JSON parsing error
            logger.error(f"Failed to parse Home Assistant response as JSON: {str(e)}")
            logger.error(f"Response preview: {response.text[:200] if 'response' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"Error fetching current media: {str(e)}")
            return None

# Create global instance
ha_api = HomeAssistantAPI()
