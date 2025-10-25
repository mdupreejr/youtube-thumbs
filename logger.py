import logging
import os


def setup_logger() -> logging.Logger:
    """Configure and return the main application logger."""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    logger = logging.getLogger('youtube_thumbs')
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.handlers = []
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(handler)

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


logger = setup_logger()
user_action_logger = setup_user_action_logger()
