"""
Logging configuration for LXST Phone.

Provides centralized logging with proper levels, formatting, and optional file output.
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler


LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOGGER_NAMES = [
    "lxst_phone.app",
    "lxst_phone.ui",
    "lxst_phone.core.media",
    "lxst_phone.core.reticulum",
    "lxst_phone.core.call_state",
    "lxst_phone.config",
    "lxst_phone.identity",
    "lxst_phone.peers",
]


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    console: bool = True,
) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (optional, creates rotating log)
        console: Whether to log to console (default: True)
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger("lxst_phone")
    root_logger.setLevel(numeric_level)

    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if log_file:
        if isinstance(log_file, str):
            log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10MB
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    for logger_name in LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        logger.setLevel(numeric_level)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific component.

    Args:
        name: Component name (e.g., 'lxst_phone.ui' or just 'ui')

    Returns:
        Logger instance
    """
    if not name.startswith("lxst_phone."):
        name = f"lxst_phone.{name}"
    return logging.getLogger(name)


def get_log_directory() -> Path:
    """Get the default log directory."""
    return Path.home() / ".lxst_phone" / "logs"


def get_default_log_file() -> Path:
    """Get the default log file path."""
    return get_log_directory() / "lxst_phone.log"
