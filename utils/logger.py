# Logging configuration
import logging
import logging.handlers
from pathlib import Path

def setup_logging(app):
    """Setup application logging."""
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Set level based on app config
    level = logging.DEBUG if app.debug else logging.INFO
    
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(level)
    
    # File handler (all logs)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'app.log',
        maxBytes=5*1024*1024,  # 5MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Console handler (only warnings and errors)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
