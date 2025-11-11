"""
Unified logging helper for consistent logging across all processes.

This module provides a centralized logging system that eliminates duplicate
logging patterns and ensures consistent formatting across the application.

Usage:
    from logging_helper import LoggingHelper, LogType

    # Get a logger instance
    logger = LoggingHelper.get_logger(LogType.MAIN)
    logger.info("Standard logging")

    # Use helper methods for common patterns
    LoggingHelper.log_error_with_trace("Operation failed", exception)
    LoggingHelper.log_user_action("Rated video", "video_id: abc123")
"""

import logging
import os
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


class LogType(Enum):
    """Enum for different log types in the application."""
    MAIN = "youtube_thumbs"
    USER_ACTION = "youtube_thumbs.user_actions"
    RATING = "youtube_thumbs.ratings"


class LoggingHelper:
    """
    Unified logging helper for consistent logging across all processes.

    This class manages all loggers in the application and provides helper
    methods for common logging patterns to prevent duplicate/inconsistent logging.
    """

    _loggers = {}
    _initialized = False
    _log_dir = Path('/config/youtube_thumbs')

    @classmethod
    def initialize(cls, log_dir: str = '/config/youtube_thumbs'):
        """
        Initialize all loggers. Should be called once at application startup.

        Args:
            log_dir: Directory where log files will be stored
        """
        if cls._initialized:
            return

        cls._log_dir = Path(log_dir)
        cls._log_dir.mkdir(parents=True, exist_ok=True)

        # Setup all loggers
        cls._loggers[LogType.MAIN] = cls._setup_main_logger()
        cls._loggers[LogType.USER_ACTION] = cls._setup_user_action_logger()
        cls._loggers[LogType.RATING] = cls._setup_rating_logger()

        cls._initialized = True

    @classmethod
    def get_logger(cls, log_type: LogType = LogType.MAIN) -> logging.Logger:
        """
        Get a logger instance by type.

        Args:
            log_type: The type of logger to retrieve

        Returns:
            The requested logger instance
        """
        if not cls._initialized:
            cls.initialize()
        return cls._loggers.get(log_type, cls._loggers[LogType.MAIN])

    # =============================================================================
    # Helper methods for common logging patterns (prevents duplicate logging)
    # =============================================================================

    @classmethod
    def log_error_with_trace(cls, message: str, exception: Exception,
                            log_type: LogType = LogType.MAIN):
        """
        Log an error with full traceback in a single call.

        This replaces the common pattern of:
            logger.error(f"Error: {e}")
            logger.error(traceback.format_exc())

        Args:
            message: Error message to log
            exception: The exception that occurred
            log_type: Which logger to use
        """
        logger = cls.get_logger(log_type)
        logger.error(f"{message}: {exception}", exc_info=True)

    @classmethod
    def log_status_change(cls, item_type: str, item_id: str, new_status: str,
                         log_type: LogType = LogType.MAIN):
        """
        Log status changes consistently with minimal verbosity.

        Args:
            item_type: Type of item (e.g., "Queue item", "Video")
            item_id: Identifier for the item
            new_status: New status value
            log_type: Which logger to use
        """
        logger = cls.get_logger(log_type)
        logger.debug(f"{item_type} {item_id} → {new_status}")

    @classmethod
    def log_operation(cls, operation: str, status: str = "started",
                     log_type: LogType = LogType.MAIN):
        """
        Log operation start/completion with consistent formatting.

        This consolidates multiple initialization messages into single log entries.

        Args:
            operation: Name of the operation
            status: Status - "started" or "completed"
            log_type: Which logger to use
        """
        logger = cls.get_logger(log_type)
        emoji = "▶" if status == "started" else "✓"
        logger.info(f"{emoji} {operation.capitalize()} {status}")

    @classmethod
    def log_user_action(cls, action: str, details: Optional[str] = None):
        """
        Log user actions consistently with USER_ACTION tag.

        Args:
            action: The action performed
            details: Optional additional details
        """
        logger = cls.get_logger(LogType.USER_ACTION)
        message = action
        if details:
            message += f" - {details}"
        logger.info(message)

    @classmethod
    def log_rating(cls, video_id: str, rating: str, result: str):
        """
        Log rating attempts consistently to the ratings log.

        Args:
            video_id: The YouTube video ID
            rating: Rating type (like/dislike)
            result: Result of the rating attempt
        """
        logger = cls.get_logger(LogType.RATING)
        logger.info(f"{video_id} | {rating} | {result}")

    # =============================================================================
    # Private logger setup methods
    # =============================================================================

    @classmethod
    def _setup_main_logger(cls) -> logging.Logger:
        """Configure and return the main application logger."""
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

        logger = logging.getLogger(LogType.MAIN.value)
        logger.setLevel(getattr(logging, log_level, logging.INFO))
        logger.handlers = []
        logger.propagate = False

        # Console handler without timestamp (Home Assistant supervisor adds its own)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
        logger.addHandler(console_handler)

        try:
            # File handler for all logs (with timestamp)
            file_handler = RotatingFileHandler(
                cls._log_dir / 'youtube_thumbs.log',
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
                cls._log_dir / 'errors.log',
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
            logger.warning(f"Could not create file handlers: {e}")

        return logger

    @classmethod
    def _setup_user_action_logger(cls) -> logging.Logger:
        """Configure user action logger for filtering in Home Assistant."""
        logger = logging.getLogger(LogType.USER_ACTION.value)
        logger.setLevel(logging.INFO)
        logger.handlers = []
        logger.propagate = False

        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[USER_ACTION] %(message)s'))
        logger.addHandler(handler)

        return logger

    @classmethod
    def _setup_rating_logger(cls) -> logging.Logger:
        """Configure rating history logger for tracking all rating attempts."""
        logger = logging.getLogger(LogType.RATING.value)
        logger.setLevel(logging.INFO)
        logger.handlers = []
        logger.propagate = False

        try:
            # File handler for rating history
            rating_handler = RotatingFileHandler(
                cls._log_dir / 'ratings.log',
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
            console_handler.setFormatter(logging.Formatter('[RATING] %(message)s'))
            logger.addHandler(console_handler)
            logger.warning(f"Could not create rating file handler: {e}")

        return logger


# Initialize loggers on module import for backward compatibility
# This allows existing code to work without modification during migration
LoggingHelper.initialize()

# Export convenience references for easy migration
logger = LoggingHelper.get_logger(LogType.MAIN)
user_action_logger = LoggingHelper.get_logger(LogType.USER_ACTION)
rating_logger = LoggingHelper.get_logger(LogType.RATING)
