import logging
import os
from dotenv import load_dotenv

load_dotenv()


def setup_logger() -> logging.Logger:
    """
    Configure and return the main application logger.
    Uses standard Python logging that outputs to stdout/stderr.
    Home Assistant supervisor captures and routes to HA's logging system.
    """
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    logger = logging.getLogger('youtube_thumbs')
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.handlers = []  # Remove existing handlers to avoid duplicates
    logger.propagate = False

    # Console handler (outputs to stdout/stderr, captured by HA supervisor)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    # Simple formatter for Home Assistant logs
    formatter = logging.Formatter(
        '[%(levelname)s] %(message)s'
    )

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def setup_user_action_logger() -> logging.Logger:
    """
    Configure and return the user action logger.
    Separate logger name allows filtering in Home Assistant.
    """
    logger = logging.getLogger('youtube_thumbs.user_actions')
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # User action formatter (simpler, no level since it's always INFO)
    formatter = logging.Formatter('[USER_ACTION] %(message)s')

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# Create global logger instances
logger = setup_logger()
user_action_logger = setup_user_action_logger()
