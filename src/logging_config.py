"""Logging configuration for the Station 95 chatbot."""

import logging
import sys
from pathlib import Path

from .config import settings


def setup_logging() -> None:
    """Configure logging for the application."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_formatter = logging.Formatter(
        fmt="%(levelname)s: %(message)s",
    )

    # File handler for all logs
    file_handler = logging.FileHandler(log_dir / "chatbot.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)

    # File handler for errors only
    error_handler = logging.FileHandler(log_dir / "errors.log")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)

    # File handler for LLM interactions
    llm_handler = logging.FileHandler(log_dir / "llm.log")
    llm_handler.setLevel(logging.INFO)
    llm_handler.setFormatter(detailed_formatter)

    # File handler for GroupMe communications
    groupme_handler = logging.FileHandler(log_dir / "groupme.log")
    groupme_handler.setLevel(logging.INFO)
    groupme_handler.setFormatter(detailed_formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any existing handlers
    root_logger.handlers.clear()

    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    # Configure LLM logger with its own handler
    llm_logger = logging.getLogger("llm")
    llm_logger.setLevel(logging.INFO)
    llm_logger.addHandler(llm_handler)
    llm_logger.propagate = False  # Don't propagate to root logger

    # Configure GroupMe logger with its own handler
    groupme_logger = logging.getLogger("groupme")
    groupme_logger.setLevel(logging.INFO)
    groupme_logger.addHandler(groupme_handler)
    groupme_logger.propagate = False  # Don't propagate to root logger

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("supabase").setLevel(logging.WARNING)
    logging.getLogger("postgrest").setLevel(logging.WARNING)

    logging.info("Logging configured successfully")
