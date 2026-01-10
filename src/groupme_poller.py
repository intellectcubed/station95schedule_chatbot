"""GroupMe message poller for periodic message checking."""

import json
import logging
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import Any

from .admin_notifier import notify_admin
from .agentic_coordinator import AgenticCoordinator
from .config import settings
from .message_queue_manager import MessageQueueManager
from .models import GroupMeMessage
from .poller_lock import PollerLock
from .roster import Roster
from .supabase_client import get_supabase

logger = logging.getLogger(__name__)
groupme_logger = logging.getLogger("groupme")


class GroupMePoller:
    """
    Polls GroupMe for new messages and processes them.

    This poller:
    - Fetches recent messages from GroupMe API
    - Tracks the last processed message ID
    - Processes new messages through AgenticCoordinator
    - Handles system messages and bot messages appropriately
    """

    def __init__(
        self,
        coordinator: AgenticCoordinator,
        roster: Roster,
        state_file: str = "data/last_message_id.txt"
    ):
        """
        Initialize the GroupMe poller.

        Args:
            coordinator: AgenticCoordinator for processing messages
            roster: Roster for user impersonation lookup
            state_file: Path to file storing the last processed message ID
        """
        self.coordinator = coordinator
        self.roster = roster
        self.state_file = Path(state_file)
        self.api_token = settings.groupme_api_token
        self.group_id = settings.groupme_group_id
        self.bot_id = settings.groupme_bot_id
        self.api_url = f"https://api.groupme.com/v3/groups/{self.group_id}/messages"

        # Initialize message queue manager
        supabase = get_supabase()
        self.queue_manager = MessageQueueManager(supabase)

        # Initialize poller lock
        self.poller_lock = PollerLock()

        # Ensure state directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized GroupMePoller for group {self.group_id}")
        logger.info(f"Bot ID for filtering: {self.bot_id}")
        if settings.enable_user_impersonation:
            logger.warning("⚠️  User impersonation is ENABLED - for testing only!")

    def _load_last_message_id(self) -> str | None:
        """
        Load the last processed message ID from state file.

        Returns:
            The last message ID, or None if not found
        """
        try:
            if self.state_file.exists():
                last_id = self.state_file.read_text().strip()
                logger.info(f"Loaded last message ID: {last_id}")
                return last_id
            else:
                logger.info("No previous message ID found, starting fresh")
                return None
        except Exception as e:
            logger.error(f"Error loading last message ID: {e}")
            return None

    def _save_last_message_id(self, message_id: str) -> None:
        """
        Save the last processed message ID to state file.

        Args:
            message_id: The message ID to save
        """
        try:
            self.state_file.write_text(message_id)
            logger.debug(f"Saved last message ID: {message_id}")
        except Exception as e:
            logger.error(f"Error saving last message ID: {e}")

    def _fetch_messages(
        self,
        limit: int = 100,
        before_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Fetch messages from GroupMe API.

        Args:
            limit: Maximum number of messages to fetch (default 100, max 100)
            before_id: Fetch messages before this message ID (for pagination)

        Returns:
            List of message dictionaries from GroupMe API

        Raises:
            requests.RequestException: If the API request fails
        """
        params = {
            "token": self.api_token,
            "limit": min(limit, 100),  # GroupMe max is 100
        }

        if before_id:
            params["before_id"] = before_id

        logger.debug(f"Fetching messages from GroupMe (limit={limit}, before_id={before_id})")

        try:
            response = requests.get(
                self.api_url,
                params=params,
                timeout=30,
            )

            response.raise_for_status()

            data = response.json()

            if data.get("meta", {}).get("code") != 200:
                logger.error(f"GroupMe API error: {data}")
                raise requests.RequestException(
                    f"GroupMe API returned code {data.get('meta', {}).get('code')}"
                )

            messages = data.get("response", {}).get("messages", [])
            logger.info(f"Fetched {len(messages)} messages from GroupMe")

            return messages

        except requests.RequestException as e:
            logger.error(f"Error fetching messages from GroupMe: {e}")
            raise

    def _should_skip_message(self, message_data: dict[str, Any]) -> bool:
        """
        Determine if a message should be skipped (not queued for processing).

        Args:
            message_data: Message data from GroupMe API

        Returns:
            True if message should be skipped, False otherwise
        """
        # Skip system messages
        if message_data.get("system", False):
            return True

        # Skip bot messages (sender_type == "bot")
        if message_data.get("sender_type") == "bot":
            return True

        # Skip messages from our bot_id
        if message_data.get("sender_id") == self.bot_id or message_data.get("user_id") == self.bot_id:
            return True

        # Skip messages from Station95Bot username
        if message_data.get("name", "").lower() == "station95bot":
            return True

        return False

    def _resolve_calling_user(
        self,
        sender_name: str,
        message_text: str
    ) -> tuple[str, str]:
        """
        Resolve the calling user based on impersonation feature flag.

        If impersonation is enabled and message starts with {{@username}},
        resolve username from roster and strip the prefix from the message.

        Args:
            sender_name: Original sender name from GroupMe
            message_text: Original message text

        Returns:
            Tuple of (resolved_sender_name, cleaned_message_text)
        """
        # If impersonation is disabled, return original values
        if not settings.enable_user_impersonation:
            return sender_name, message_text

        # Check for impersonation prefix: {{@username}} or {{username}}
        # Supports names with spaces: {{@Diane Chrinko}} or {{Diane Chrinko}}
        match = re.match(r'^\{\{@?([^}]+)\}\}\s*', message_text)

        if not match:
            # No impersonation prefix found
            return sender_name, message_text

        # Extract username from prefix (strip whitespace)
        impersonated_username = match.group(1).strip()

        # Strip the prefix from message
        cleaned_message = message_text[match.end():]

        # Look up user in roster
        member = self.roster.find_member_by_name(impersonated_username)

        if member:
            logger.info(
                f"🎭 Impersonating user: {impersonated_username} "
                f"(squad {member.squad}, {member.title})"
            )
            # Use the groupme_name from roster
            return member.groupme_name, cleaned_message
        else:
            logger.warning(
                f"⚠️  Impersonation failed: user '{impersonated_username}' "
                f"not found in roster. Using original sender."
            )
            # User not found in roster, use original sender but still clean message
            return sender_name, cleaned_message

    def _process_message_dict(self, message_data: dict[str, Any]) -> dict:
        """
        Convert GroupMe API message format to GroupMeMessage and process it.

        Args:
            message_data: Message data from GroupMe API

        Returns:
            Processing result dictionary
        """
        # Skip system messages
        if message_data.get("system", False):
            logger.debug(f"Skipping system message: {message_data.get('id')}")
            return {"status": "ignored", "reason": "system message"}

        # Skip bot messages (avoid loops)
        # Check both sender_type and user_id/sender_id to catch all bot messages
        if message_data.get("sender_type") == "bot":
            logger.debug(f"Skipping bot message (sender_type=bot): {message_data.get('id')}")
            return {"status": "ignored", "reason": "bot message"}

        # Also check if the sender_id matches our bot_id
        if message_data.get("sender_id") == self.bot_id or message_data.get("user_id") == self.bot_id:
            logger.info(f"Skipping bot's own message (sender_id matches bot_id): {message_data.get('id')}")
            return {"status": "ignored", "reason": "bot's own message"}

        # Skip messages from Station95Bot user name (additional safety check)
        if message_data.get("name", "").lower() == "station95bot":
            logger.info(f"Skipping message from Station95Bot user: {message_data.get('id')}")
            return {"status": "ignored", "reason": "bot user name"}

        # Resolve calling user (handles impersonation if enabled)
        original_sender = message_data.get("name", "Unknown")
        original_message = message_data.get("text", "")
        resolved_sender, cleaned_message = self._resolve_calling_user(
            original_sender,
            original_message
        )

        # Convert to GroupMeMessage model
        try:
            message = GroupMeMessage(
                sender_name=resolved_sender,
                message_text=cleaned_message,
                timestamp=message_data.get("created_at", 0),
                group_id=message_data.get("group_id", ""),
                message_id=message_data.get("id", ""),
                sender_id=message_data.get("sender_id", ""),
                preview=False,  # Poller doesn't use preview mode
            )
        except Exception as e:
            logger.error(f"Error parsing message data: {e}")
            return {"status": "error", "reason": f"Invalid message data: {e}"}

        # Process the message through the agentic coordinator
        logger.info(
            f"Processing message {message.message_id} from {message.sender_name}"
        )
        result = self.coordinator.process_message(message)

        return result

    def poll(self, limit: int = 20) -> dict[str, Any]:
        """
        Poll GroupMe for new messages and process them using message queue.

        This method:
        1. Acquires poller lock (yields if another poller is running)
        2. Fetches new messages from GroupMe
        3. Inserts new messages into message queue (status: PENDING)
        4. Processes all PENDING messages from queue
        5. Expires old messages from queue
        6. Updates last processed message ID
        7. Releases poller lock

        Args:
            limit: Maximum number of messages to fetch (default 20)

        Returns:
            Dictionary with polling results
        """
        logger.info("=" * 60)
        logger.info(f"Starting poll at {datetime.now().isoformat()}")

        # Try to acquire poller lock
        if not self.poller_lock.acquire():
            logger.info("Another poller is active, yielding")
            return {
                "success": True,
                "yielded": True,
                "reason": "another_poller_active"
            }

        try:
            # === Step 1: Fetch new messages from GroupMe ===
            last_message_id = self._load_last_message_id()

            try:
                messages = self._fetch_messages(limit=limit)
            except Exception as e:
                logger.error(f"Failed to fetch messages: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "messages_fetched": 0,
                }

            if not messages:
                logger.info("No messages retrieved from GroupMe")
            else:
                # GroupMe returns messages in reverse chronological order
                messages.reverse()

                # Filter out already-seen messages
                new_messages = []
                for msg in messages:
                    msg_id = msg.get("id")
                    if last_message_id and msg_id <= last_message_id:
                        continue
                    new_messages.append(msg)

                logger.info(f"Found {len(new_messages)} new messages")

                # === Step 2: Insert new messages into queue ===
                queued_count = 0
                for message_data in new_messages:
                    # Skip system messages and bot messages
                    if self._should_skip_message(message_data):
                        logger.debug(f"Skipping message {message_data.get('id')}")
                        continue

                    # Resolve calling user (handles impersonation)
                    original_sender = message_data.get("name", "Unknown")
                    original_message = message_data.get("text", "")
                    resolved_sender, cleaned_message = self._resolve_calling_user(
                        original_sender,
                        original_message
                    )

                    # Log received message to GroupMe communications log
                    msg_timestamp = message_data.get("created_at", 0)
                    msg_datetime = datetime.fromtimestamp(msg_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                    groupme_logger.info(
                        f"RECEIVED FROM GROUPME | Timestamp: {msg_datetime} | "
                        f"From: {resolved_sender} | Message: {cleaned_message}"
                    )

                    # Insert into queue
                    try:
                        self.queue_manager.insert_message(
                            message_id=message_data.get("id"),
                            group_id=message_data.get("group_id", self.group_id),
                            user_id=message_data.get("sender_id", ""),
                            user_name=resolved_sender,
                            message_text=cleaned_message,
                            timestamp=msg_timestamp
                        )
                        queued_count += 1
                    except Exception as e:
                        logger.error(f"Failed to queue message: {e}")

                    # Update last message ID
                    last_message_id = message_data.get("id")
                    self._save_last_message_id(last_message_id)

                logger.info(f"Queued {queued_count} new messages")

            # === Step 3: Process all PENDING messages from queue ===
            pending_messages = self.queue_manager.get_pending_messages()
            logger.info(f"Processing {len(pending_messages)} pending messages from queue")

            processed_count = 0
            failed_count = 0

            for queue_msg in pending_messages:
                # Update status to PROCESSING
                self.queue_manager.update_status(queue_msg.message_id, "PROCESSING")

                try:
                    # Convert to GroupMeMessage
                    groupme_msg = GroupMeMessage(
                        sender_name=queue_msg.user_name,
                        message_text=queue_msg.message_text,
                        timestamp=queue_msg.timestamp,
                        group_id=queue_msg.group_id,
                        message_id=queue_msg.message_id,
                        sender_id=queue_msg.user_id,
                        preview=False
                    )

                    # Process through coordinator
                    result = self.coordinator.process_message(groupme_msg)

                    # Mark as DONE
                    self.queue_manager.update_status(queue_msg.message_id, "DONE")
                    processed_count += 1

                except Exception as e:
                    logger.error(f"Failed to process message {queue_msg.message_id}: {e}")

                    # Mark as FAILED
                    self.queue_manager.update_status(
                        queue_msg.message_id,
                        "FAILED",
                        error_message=str(e)
                    )
                    failed_count += 1

                    # Check if retry limit exceeded
                    retry_count = self.queue_manager.get_retry_count(queue_msg.message_id)
                    if retry_count >= settings.max_retry_attempts:
                        logger.error(
                            f"Message {queue_msg.message_id} exceeded retry limit ({retry_count})"
                        )
                        notify_admin(
                            "message_retry_exceeded",
                            {
                                "message_id": queue_msg.message_id,
                                "retry_count": retry_count,
                                "error_message": str(e)
                            }
                        )

            # === Step 4: Expire old messages ===
            expired_count = self.queue_manager.expire_old_messages()

            logger.info(
                f"Poll complete: {processed_count} processed, "
                f"{failed_count} failed, {expired_count} expired"
            )
            logger.info("=" * 60)

            return {
                "success": True,
                "messages_fetched": len(messages) if messages else 0,
                "messages_queued": queued_count if messages else 0,
                "messages_processed": processed_count,
                "messages_failed": failed_count,
                "messages_expired": expired_count,
            }

        finally:
            # Always release the lock
            self.poller_lock.release()

    def reset_state(self) -> None:
        """
        Reset the poller state by deleting the last message ID.

        Use this to reprocess all messages or start fresh.
        """
        if self.state_file.exists():
            self.state_file.unlink()
            logger.info("Reset poller state - deleted last message ID")
        else:
            logger.info("No state to reset")
