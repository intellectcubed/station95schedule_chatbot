"""Client for sending messages to GroupMe."""

import logging
import requests
import time
from typing import Any, TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    from .conversation_state_manager import ConversationStateManager

logger = logging.getLogger(__name__)
groupme_logger = logging.getLogger("groupme")


class GroupMeClient:
    """Client for sending messages to GroupMe group chat."""

    def __init__(
        self,
        bot_id: str | None = None,
        state_manager: "ConversationStateManager | None" = None
    ):
        """
        Initialize the GroupMe client.

        Args:
            bot_id: Optional override for bot ID
            state_manager: Optional state manager for logging bot messages
        """
        self.bot_id = bot_id or settings.groupme_bot_id
        self.api_url = "https://api.groupme.com/v3/bots/post"
        self.state_manager = state_manager
        logger.info(f"Initialized GroupMeClient with bot_id: {self.bot_id}")

    def send_message(
        self,
        text: str,
        workflow_id: str | None = None,
        group_id: str | None = None
    ) -> dict[str, Any]:
        """
        Send a message to the GroupMe group chat.

        Args:
            text: The message text to send
            workflow_id: Optional workflow ID to link message to
            group_id: Optional group ID for logging (defaults to bot's group)

        Returns:
            Response from GroupMe API

        Raises:
            requests.RequestException: If the request fails
        """
        payload = {
            "bot_id": self.bot_id,
            "text": text,
        }

        logger.info(f"Sending message to GroupMe: {text[:100]}...")

        # Log to GroupMe communications log
        if settings.enable_groupme_posting:
            groupme_logger.info(f"SENT TO GROUPME: {text}")
        else:
            groupme_logger.info(f"[DRY RUN] WOULD SEND TO GROUPME: {text}")

        # Check if posting is enabled
        if not settings.enable_groupme_posting:
            logger.warning(
                "⚠️  GroupMe posting is DISABLED - message logged but not sent. "
                "Set ENABLE_GROUPME_POSTING=true to enable actual posting."
            )

            # Log bot message to conversations table (even in dry-run mode)
            if self.state_manager:
                self._log_bot_message(text, workflow_id, group_id)

            # Return success without actually posting
            return {"status": "success", "response": "dry_run", "dry_run": True}

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=10,
            )

            response.raise_for_status()

            logger.info(f"Message sent successfully: {response.status_code}")

            # Log bot message to conversations table
            if self.state_manager:
                self._log_bot_message(text, workflow_id, group_id)

            # GroupMe returns 202 Accepted for successful bot posts
            return {"status": "success", "response": response.text}

        except requests.RequestException as e:
            logger.error(f"Error sending message to GroupMe: {e}")
            raise

    def _log_bot_message(
        self,
        text: str,
        workflow_id: str | None,
        group_id: str | None
    ) -> None:
        """
        Log bot message to conversations table.

        Args:
            text: The message text
            workflow_id: Workflow ID if applicable
            group_id: Group ID
        """
        try:
            from .models import ConversationMessage

            # Use provided group_id or fall back to bot's group
            msg_group_id = group_id or settings.groupme_group_id

            # Create a ConversationMessage for the bot
            bot_message = ConversationMessage(
                message_id=f"bot_{int(time.time() * 1000)}_{hash(text) % 10000}",  # Synthetic ID
                group_id=msg_group_id,
                user_id=self.bot_id,
                user_name="Station95Bot",
                message_text=text,
                timestamp=int(time.time()),
                workflow_id=workflow_id
            )

            self.state_manager.store_message(bot_message)
            logger.debug(f"Logged bot message to conversations table")

        except Exception as e:
            # Don't fail the whole operation if logging fails
            logger.warning(f"Failed to log bot message to database: {e}")

    def send_message_with_retry(self, text: str, max_retries: int = 2) -> dict[str, Any]:
        """
        Send a message with retry logic.

        Args:
            text: The message text to send
            max_retries: Maximum number of retry attempts

        Returns:
            Response from GroupMe API
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                return self.send_message(text)
            except requests.RequestException as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")

                if attempt < max_retries - 1:
                    logger.info("Retrying...")
                    continue
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    raise last_error

        raise last_error

    def send_warning(
        self,
        warning_text: str,
        workflow_id: str | None = None,
        group_id: str | None = None
    ) -> dict[str, Any]:
        """
        Send a warning message to the GroupMe group chat with formatting.

        Args:
            warning_text: The warning message to send
            workflow_id: Optional workflow ID to link message to
            group_id: Optional group ID for logging

        Returns:
            Response from GroupMe API
        """
        formatted_message = f"⚠️ WARNING ⚠️\n{warning_text}"
        return self.send_message(formatted_message, workflow_id, group_id)

    def send_critical_alert(
        self,
        alert_text: str,
        workflow_id: str | None = None,
        group_id: str | None = None
    ) -> dict[str, Any]:
        """
        Send a critical alert message to the GroupMe group chat with formatting.

        Args:
            alert_text: The critical alert message to send
            workflow_id: Optional workflow ID to link message to
            group_id: Optional group ID for logging

        Returns:
            Response from GroupMe API
        """
        formatted_message = f"🚨 CRITICAL ALERT 🚨\n{alert_text}"
        return self.send_message(formatted_message, workflow_id, group_id)
