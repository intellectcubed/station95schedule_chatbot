#!/usr/bin/env python3
"""CLI script to poll GroupMe for new messages.

This script can be run periodically by cron or other schedulers.

Example cron entry (every 2 minutes):
    */2 * * * * cd /path/to/project && python -m src.poll_messages

Example systemd timer:
    rate(2 minutes)

Example while loop:
    while true; do python -m src.poll_messages; sleep 120; done
"""

import logging
import sys
from pathlib import Path

from .agentic_coordinator import AgenticCoordinator
from .config import settings
from .groupme_poller import GroupMePoller
from .logging_config import setup_logging

logger = logging.getLogger(__name__)


def validate_configuration() -> None:
    """Validate that all required configuration is present."""
    errors = []

    # Check roster file exists
    if not Path(settings.roster_file_path).exists():
        errors.append(f"Roster file not found: {settings.roster_file_path}")

    # Check system prompt exists
    if not Path(settings.system_prompt_path).exists():
        errors.append(f"System prompt not found: {settings.system_prompt_path}")

    # Validate configuration
    try:
        settings.validate_config()
    except ValueError as e:
        errors.append(str(e))

    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        raise ValueError(
            "Configuration validation failed. Please check your .env file and "
            "ensure all required variables are set."
        )

    logger.info("✅ Configuration validated successfully")


def main() -> None:
    """Main entry point for polling script."""
    # Setup logging
    setup_logging()
    logger.info("=" * 60)
    logger.info("Starting GroupMe message poll")
    logger.info("=" * 60)

    try:
        # Validate configuration
        validate_configuration()

        # Initialize agentic coordinator (does all the heavy lifting)
        coordinator = AgenticCoordinator()

        # Initialize and run poller
        poller = GroupMePoller(coordinator, coordinator.roster)

        # Poll for up to 20 recent messages
        result = poller.poll(limit=20)

        # Log summary
        if result.get("success"):
            logger.info("=" * 60)
            logger.info(
                f"✅ Poll completed successfully: "
                f"{result.get('messages_new', 0)} new messages, "
                f"{result.get('messages_processed', 0)} processed, "
                f"{result.get('messages_ignored', 0)} ignored"
            )
            logger.info("=" * 60)

            # Exit with success code
            sys.exit(0)
        else:
            logger.error("=" * 60)
            logger.error(f"❌ Poll failed: {result.get('error', 'Unknown error')}")
            logger.error("=" * 60)
            sys.exit(1)

    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"❌ Fatal error during poll: {e}", exc_info=True)
        logger.error("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
