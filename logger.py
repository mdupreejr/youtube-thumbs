import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logger() -> logging.Logger:
    """Configure and return the main application logger."""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    logger = logging.getLogger('youtube_thumbs')
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.handlers = []
    logger.propagate = False

    # Console handler (existing)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(console_handler)

    # Create log directory if it doesn't exist
    log_dir = Path('/config/youtube_thumbs')
    try:
        log_dir.mkdir(parents=True, exist_ok=True)

        # File handler for all logs (with Home Assistant friendly format)
        file_handler = RotatingFileHandler(
            log_dir / 'youtube_thumbs.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s | %(levelname)s | %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
        )
        logger.addHandler(file_handler)

        # Separate error file handler
        error_handler = RotatingFileHandler(
            log_dir / 'errors.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(
            logging.Formatter('%(asctime)s | %(levelname)s | %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
        )
        logger.addHandler(error_handler)

    except Exception as e:
        # If we can't create file handlers (permissions, etc), just use console
        logger.warning(f"Could not create file handlers: {e}")

    return logger


def setup_user_action_logger() -> logging.Logger:
    """Configure user action logger for filtering in Home Assistant."""
    logger = logging.getLogger('youtube_thumbs.user_actions')
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[USER_ACTION] %(message)s'))
    logger.addHandler(handler)

    return logger


def setup_rating_logger() -> logging.Logger:
    """Configure rating history logger for tracking all rating attempts."""
    logger = logging.getLogger('youtube_thumbs.ratings')
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False

    # Create log directory if it doesn't exist
    log_dir = Path('/config/youtube_thumbs')
    try:
        log_dir.mkdir(parents=True, exist_ok=True)

        # File handler for rating history
        rating_handler = RotatingFileHandler(
            log_dir / 'ratings.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=3,
            encoding='utf-8'
        )
        rating_handler.setFormatter(
            logging.Formatter('%(asctime)s | %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S')
        )
        logger.addHandler(rating_handler)

    except Exception as e:
        # Fallback to console if file handler fails
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter('[RATING] %(message)s')
        )
        logger.addHandler(console_handler)
        logger.warning(f"Could not create rating file handler: {e}")

    return logger


logger = setup_logger()
user_action_logger = setup_user_action_logger()
rating_logger = setup_rating_logger()
