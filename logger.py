import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv

load_dotenv()

def setup_logger() -> logging.Logger:
    """Configure and return the application logger with file rotation."""
    log_file = os.getenv('LOG_FILE', 'app.log')
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    max_size_mb = int(os.getenv('LOG_MAX_SIZE_MB', '10'))
    backup_count = int(os.getenv('LOG_BACKUP_COUNT', '30'))
    
    # Create logger
    logger = logging.getLogger('youtube_thumbs')
    logger.setLevel(getattr(logging, log_level))
    
    # Remove existing handlers to avoid duplicates
    logger.handlers = []
    
    # Create rotating file handler
    max_bytes = max_size_mb * 1024 * 1024
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    
    # Create console handler
    console_handler = logging.StreamHandler()
    
    # Create formatter
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def setup_user_action_logger() -> logging.Logger:
    """Configure and return the user action logger with file rotation."""
    log_file = os.getenv('USER_ACTION_LOG_FILE', 'user_actions.log')
    max_size_mb = int(os.getenv('LOG_MAX_SIZE_MB', '10'))
    backup_count = int(os.getenv('LOG_BACKUP_COUNT', '30'))
    
    # Create logger
    action_logger = logging.getLogger('youtube_thumbs.user_actions')
    action_logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    action_logger.handlers = []
    
    # Prevent propagation to parent logger
    action_logger.propagate = False
    
    # Create rotating file handler
    max_bytes = max_size_mb * 1024 * 1024
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    
    # Create console handler
    console_handler = logging.StreamHandler()
    
    # Create simple formatter for structured user action logs
    formatter = logging.Formatter(
        '[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    action_logger.addHandler(file_handler)
    action_logger.addHandler(console_handler)
    
    return action_logger


def setup_error_logger() -> logging.Logger:
    """Configure and return the error logger with file rotation."""
    log_file = os.getenv('ERROR_LOG_FILE', 'errors.log')
    max_size_mb = int(os.getenv('LOG_MAX_SIZE_MB', '10'))
    backup_count = int(os.getenv('LOG_BACKUP_COUNT', '30'))
    
    # Create logger
    err_logger = logging.getLogger('youtube_thumbs.errors')
    err_logger.setLevel(logging.ERROR)
    
    # Remove existing handlers to avoid duplicates
    err_logger.handlers = []
    
    # Prevent propagation to parent logger
    err_logger.propagate = False
    
    # Create rotating file handler
    max_bytes = max_size_mb * 1024 * 1024
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    
    # Create console handler
    console_handler = logging.StreamHandler()
    
    # Create formatter with detailed error information
    formatter = logging.Formatter(
        '[%(asctime)s] ERROR: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    err_logger.addHandler(file_handler)
    err_logger.addHandler(console_handler)
    
    return err_logger


# Create global logger instances
logger = setup_logger()
user_action_logger = setup_user_action_logger()
error_logger = setup_error_logger()
