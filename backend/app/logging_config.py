"""
Centralized logging configuration for deez-forex-ai.

Provides structured JSON logging for production and colored console
logging for development. All modules should import the `logger`
instance from this module rather than creating their own.
"""

import logging
import sys
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# ANSI color codes for development console output
_COLORS = {
    "DEBUG": "\033[36m",      # Cyan
    "INFO": "\033[32m",       # Green
    "WARNING": "\033[33m",    # Yellow
    "ERROR": "\033[31m",      # Red
    "CRITICAL": "\033[35m",   # Magenta
    "RESET": "\033[0m",
}


class _JSONFormatter(logging.Formatter):
    """
    Structured JSON formatter for production logging.
    Outputs machine-parseable JSON lines for log aggregation.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # Include exception info if available
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include extra fields from LogRecord
        for key in ("symbol", "trade_id", "provider", "duration_ms"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        return json.dumps(log_entry, default=str)


class _ColorFormatter(logging.Formatter):
    """
    Colored console formatter for development.
    """

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelname, "")
        reset = _COLORS["RESET"]
        fmt = f"{color}[{record.levelname:8}]{reset} {record.name:24} {record.getMessage()}"
        if record.exc_info:
            fmt += "\n" + self.formatException(record.exc_info)
        return fmt


def setup_logging(
    level: str = "INFO",
    use_json: Optional[bool] = None,
) -> None:
    """
    Configure root logging for the application.

    Args:
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        use_json: If True, output JSON. If None, auto-detect based on APP_ENV.
    """
    if use_json is None:
        use_json = os.getenv("APP_ENV", "development").lower() == "production"

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Clear existing handlers to avoid duplicates on re-initialization
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if use_json:
        formatter = _JSONFormatter()
    else:
        formatter = _ColorFormatter()

    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)

    # Set our app loggers to the desired level
    for name in ("app", "app.main", "app.services", "app.analysis", "app.ai", "app.tasks"):
        logging.getLogger(name).setLevel(log_level)

    logging.getLogger("app").info("Logging initialized: level=%s, json=%s", level, use_json)


# Import os lazily to avoid circular imports on module load
import os  # noqa: E402

# Convenience: module-level logger factory
# Usage: from app.logging_config import get_logger; logger = get_logger(__name__)
def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name, pre-configured with app settings."""
    return logging.getLogger(name)
