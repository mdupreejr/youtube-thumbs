"""
YouTube API OAuth2 authentication.

This module handles authentication with YouTube using OAuth2 credentials.
"""

import json
import os
import stat
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from logging_helper import LoggingHelper, LogType

# Get logger instance
logger = LoggingHelper.get_logger(LogType.MAIN)

# OAuth2 scopes for YouTube API
SCOPES = ['https://www.googleapis.com/auth/youtube']


def authenticate() -> object:
    """
    Authenticate with YouTube API using OAuth2.

    Returns:
        Authenticated YouTube API client
    """
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
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
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
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
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
                'credentials.json', SCOPES
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

    youtube = build('youtube', 'v3', credentials=creds)
    logger.debug("YouTube API credentials loaded successfully")
    return youtube
