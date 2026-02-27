"""
Logging configuration for remy.
JSON structured logging for Azure Monitor; human-readable text for local dev.
Includes rotating file handler to manage log file size.
"""

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for Azure Monitor ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log)


def setup_logging(log_level: str, logs_dir: str, azure_environment: bool) -> None:
    """Configure root logger with appropriate format and handlers."""
    os.makedirs(logs_dir, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)

    handlers: list[logging.Handler] = []

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    if azure_environment:
        console.setFormatter(JsonFormatter())
    else:
        console.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    handlers.append(console)

    # Rotating file handler (best practice: prevents unbounded log growth)
    # 10MB per file, keep 5 backups = ~50MB total
    log_file = os.path.join(logs_dir, "remy.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,  # Keep remy.log.1 through remy.log.5
        encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
