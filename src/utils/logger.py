"""
Structured Logging Configuration
=================================

Configures structured logging for the bot with JSON output support.
"""

import sys
import logging
import structlog
from typing import Optional


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[str] = None
):
    """
    Configure structured logging for the application.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        json_output: If True, output JSON formatted logs
        log_file: Optional file path for log output
    """
    # Convert level string to logging constant
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Configure standard logging
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=handlers,
        force=True
    )
    
    # Configure structlog
    if json_output:
        # JSON output for production
        processors = [
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ]
    else:
        # Pretty console output for development
        processors = [
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True)
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None):
    """
    Get a configured logger instance.
    
    Args:
        name: Optional logger name
    
    Returns:
        structlog BoundLogger instance
    """
    return structlog.get_logger(name)
