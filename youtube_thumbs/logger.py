import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv

load_dotenv()


def _create_rotating_logger(
    name: str,
    log_file: str,
    log_level: int = logging.INFO,
    formatter_template: str = '[%(asctime)s] %(levelname)s: %(message)s',
    propagate: bool = True
) -> logging.Logger:
    """
    Create a logger with rotating file handler and console output.
    
    Args:
        name: Logger name
        log_file: Path to log file
        log_level: Logging level (default: INFO)
        formatter_template: Log message format template
        propagate: Whether to propagate to parent logger
    
    Returns:
        Configured logger instance
    """
    max_size_mb = int(os.getenv('LOG_MAX_SIZE_MB', '10'))
    backup_count = int(os.getenv('LOG_BACKUP_COUNT', '30'))
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.handlers = []  # Remove existing handlers to avoid duplicates
    logger.propagate = propagate
    
    # Create rotating file handler
    max_bytes = max_size_mb * 1024 * 1024
    file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    
    # Create formatter
    formatter = logging.Formatter(formatter_template, datefmt='%Y-%m-%d %H:%M:%S')
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def setup_logger() -> logging.Logger:
    """Configure and return the application logger with file rotation."""
    log_file = os.getenv('LOG_FILE', 'app.log')
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    return _create_rotating_logger(
        name='youtube_thumbs',
        log_file=log_file,
        log_level=getattr(logging, log_level),
        formatter_template='[%(asctime)s] %(levelname)s: %(message)s'
    )


def setup_user_action_logger() -> logging.Logger:
    """Configure and return the user action logger with file rotation."""
    log_file = os.getenv('USER_ACTION_LOG_FILE', 'user_actions.log')
    
    return _create_rotating_logger(
        name='youtube_thumbs.user_actions',
        log_file=log_file,
        log_level=logging.INFO,
        formatter_template='[%(asctime)s] %(message)s',
        propagate=False
    )


def setup_error_logger() -> logging.Logger:
    """Configure and return the error logger with file rotation."""
    log_file = os.getenv('ERROR_LOG_FILE', 'errors.log')
    
    return _create_rotating_logger(
        name='youtube_thumbs.errors',
        log_file=log_file,
        log_level=logging.ERROR,
        formatter_template='[%(asctime)s] ERROR: %(message)s',
        propagate=False
    )


# Create global logger instances
logger = setup_logger()
user_action_logger = setup_user_action_logger()
error_logger = setup_error_logger()
