"""Logging system with rotating file handler"""

import sys
from logging import getLogger, DEBUG, INFO, Formatter, StreamHandler
from logging.handlers import RotatingFileHandler
from os.path import join, isabs

from .fileio import ensure_private_dir
from .paths import get_user_data_dir, get_user_log_dir, APP_ID


def _use_console_logging() -> bool:
    """Yalnızca geliştirici terminalinde konsola yaz."""
    if getattr(sys, "frozen", False):
        return False
    if sys.executable.lower().endswith("pythonw.exe"):
        return False
    try:
        return sys.stdout is not None and sys.stdout.isatty()
    except Exception:
        return False


def get_app_directory():
    """Kullanıcı veri klasörü (veritabanı, kimlik; göreli günlük yolları buna bağlanır)."""
    return get_user_data_dir(APP_ID)


class Logger:
    """Custom logger with file rotation"""
    
    def __init__(self, name: str = "TransferTCP", log_dir: str = None, 
                 max_bytes: int = 10485760, backup_count: int = 5):
        """
        Initialize logger
        
        Args:
            name: Logger name
            log_dir: Directory for log files (if None, uses app_dir/logs)
            max_bytes: Maximum size per log file (default 10MB)
            backup_count: Number of backup files to keep
        """
        self.name = name
        
        # Use absolute path for log directory
        if log_dir is None:
            # Windows: <LOCALAPPDATA>/TransferTCP/logs; macOS: ~/Library/Logs/TransferTCP;
            # Linux: $XDG_STATE_HOME/TransferTCP/logs
            log_dir = get_user_log_dir(APP_ID)
        else:
            # If relative path provided, make it absolute relative to app directory
            if not isabs(log_dir):
                app_dir = get_app_directory()
                log_dir = join(app_dir, log_dir)
        
        self.log_dir = log_dir
        self.logger = getLogger(name)
        self.logger.setLevel(DEBUG)
        
        # Create logs directory if it doesn't exist
        try:
            ensure_private_dir(log_dir)
        except PermissionError:
            # Fallback to user's temp directory if app directory is not writable
            from tempfile import gettempdir
            log_dir = join(gettempdir(), APP_ID, "logs")
            ensure_private_dir(log_dir)
            self.log_dir = log_dir
        
        # Create formatters
        file_formatter = Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_formatter = Formatter(
            '%(levelname)s: %(message)s'
        )
        
        # File handler with rotation
        log_file = join(log_dir, f"{name}.log")
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(DEBUG)
        file_handler.setFormatter(file_formatter)
        
        self.logger.addHandler(file_handler)
        if _use_console_logging():
            console_handler = StreamHandler()
            console_handler.setLevel(INFO)
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)
    
    def debug(self, message: str, *args, **kwargs):
        """Log debug message"""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """Log info message"""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """Log warning message"""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """Log error message"""
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """Log critical message"""
        self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """Log exception with traceback"""
        self.logger.exception(message, *args, **kwargs)

    def set_level(self, level_name: str):
        """Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"""
        import logging
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        lvl = level_map.get(str(level_name).upper(), logging.INFO)
        self.logger.setLevel(lvl)
        for handler in self.logger.handlers:
            handler.setLevel(lvl)

    def set_enabled(self, enabled: bool):
        """Enable or disable logging handlers"""
        self.logger.disabled = not enabled


# Global logger instance
_logger_instance = None


def get_logger() -> Logger:
    """Get the global logger instance"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
    return _logger_instance

