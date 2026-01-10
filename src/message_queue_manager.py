"""Message queue manager for robust message processing."""

import logging
from datetime import datetime, timedelta
from typing import Any

from supabase import Client

from .config import settings
from .models import MessageQueue

logger = logging.getLogger(__name__)


class MessageQueueManager:
    """Manages message queue operations in Supabase."""

    def __init__(self, supabase_client: Client):
        """
        Initialize the message queue manager.

        Args:
            supabase_client: Supabase client instance
        """
        self.supabase = supabase_client

    def insert_message(
        self,
        message_id: str,
        group_id: str,
        user_id: str,
        user_name: str,
        message_text: str,
        timestamp: int
    ) -> MessageQueue:
        """
        Insert a new message into the queue.

        Args:
            message_id: GroupMe message ID
            group_id: GroupMe group ID
            user_id: GroupMe user ID
            user_name: User's name
            message_text: Message content
            timestamp: GroupMe timestamp

        Returns:
            Created MessageQueue object
        """
        try:
            data = {
                "message_id": message_id,
                "group_id": group_id,
                "user_id": user_id,
                "user_name": user_name,
                "message_text": message_text,
                "timestamp": timestamp,
                "status": "PENDING",
            }

            result = self.supabase.table("message_queue").insert(data).execute()

            if result.data:
                logger.debug(f"Inserted message {message_id} into queue")
                return MessageQueue(**result.data[0])
            else:
                raise Exception("No data returned from insert")

        except Exception as e:
            logger.error(f"Failed to insert message into queue: {e}")
            # Don't raise - we want to continue polling even if queue insert fails
            return None

    def get_pending_messages(self) -> list[MessageQueue]:
        """
        Get all pending messages from the queue.

        Returns:
            List of MessageQueue objects with status PENDING or FAILED
        """
        try:
            result = (
                self.supabase.table("message_queue")
                .select("*")
                .in_("status", ["PENDING", "FAILED"])
                .order("timestamp", desc=False)
                .execute()
            )

            if result.data:
                return [MessageQueue(**msg) for msg in result.data]
            return []

        except Exception as e:
            logger.error(f"Failed to get pending messages: {e}")
            return []

    def update_status(
        self,
        message_id: str,
        status: str,
        error_message: str | None = None
    ) -> None:
        """
        Update message status.

        Args:
            message_id: GroupMe message ID
            status: New status
            error_message: Optional error message for FAILED status
        """
        try:
            data = {
                "status": status,
                "updated_at": datetime.now().isoformat(),
            }

            if status == "DONE":
                data["processed_at"] = datetime.now().isoformat()

            if status == "FAILED":
                data["error_message"] = error_message
                # Increment retry count
                result = (
                    self.supabase.table("message_queue")
                    .select("retry_count")
                    .eq("message_id", message_id)
                    .execute()
                )
                if result.data:
                    current_retry = result.data[0].get("retry_count", 0)
                    data["retry_count"] = current_retry + 1

            self.supabase.table("message_queue").update(data).eq(
                "message_id", message_id
            ).execute()

            logger.debug(f"Updated message {message_id} status to {status}")

        except Exception as e:
            logger.error(f"Failed to update message status: {e}")

    def expire_old_messages(self) -> int:
        """
        Soft delete messages older than configured expiry time.

        Returns:
            Number of messages expired
        """
        try:
            expiry_time = datetime.now() - timedelta(hours=settings.message_expiry_hours)

            result = (
                self.supabase.table("message_queue")
                .update({"status": "EXPIRED", "updated_at": datetime.now().isoformat()})
                .lt("created_at", expiry_time.isoformat())
                .not_.in_("status", ["DONE", "EXPIRED", "SKIPPED"])
                .execute()
            )

            count = len(result.data) if result.data else 0
            if count > 0:
                logger.info(f"Expired {count} old messages")
            return count

        except Exception as e:
            logger.error(f"Failed to expire old messages: {e}")
            return 0

    def get_message_by_id(self, message_id: str) -> MessageQueue | None:
        """
        Get a message by its GroupMe message ID.

        Args:
            message_id: GroupMe message ID

        Returns:
            MessageQueue object or None
        """
        try:
            result = (
                self.supabase.table("message_queue")
                .select("*")
                .eq("message_id", message_id)
                .execute()
            )

            if result.data:
                return MessageQueue(**result.data[0])
            return None

        except Exception as e:
            logger.error(f"Failed to get message by ID: {e}")
            return None

    def get_retry_count(self, message_id: str) -> int:
        """
        Get the retry count for a message.

        Args:
            message_id: GroupMe message ID

        Returns:
            Retry count (0 if not found)
        """
        msg = self.get_message_by_id(message_id)
        return msg.retry_count if msg else 0
