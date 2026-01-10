"""Conversation state manager for persisting messages and workflows in Supabase."""

import logging
from datetime import datetime, timedelta
from typing import Any

from .config import settings
from .models import ConversationMessage, Workflow, WorkflowStateData
from .supabase_client import get_supabase

logger = logging.getLogger(__name__)


class ConversationStateManager:
    """
    Manages conversation state and workflow persistence in Supabase.

    This is the single source of truth for all conversation and workflow data.
    All database operations go through this class.
    """

    def __init__(self):
        """Initialize the conversation state manager."""
        self.supabase = get_supabase()
        logger.info("ConversationStateManager initialized")

    # =========================================================================
    # Message Operations
    # =========================================================================

    def store_message(
        self,
        message: ConversationMessage
    ) -> str:
        """
        Store a message in the conversations table.

        Uses upsert to prevent duplicates if same message is processed twice.

        Args:
            message: The ConversationMessage to store

        Returns:
            The GroupMe message_id

        Raises:
            Exception: If the database operation fails
        """
        logger.debug(
            f"Storing message {message.message_id} from {message.user_name} in group {message.group_id}"
        )

        try:
            data = {
                "message_id": message.message_id,
                "group_id": message.group_id,
                "user_id": message.user_id,
                "user_name": message.user_name,
                "message_text": message.message_text,
                "timestamp": message.timestamp,
                "workflow_id": message.workflow_id,
            }

            # Use upsert to handle duplicate message_ids gracefully
            result = self.supabase.table("conversations").upsert(data).execute()

            if result.data and len(result.data) > 0:
                logger.info(f"Stored message {message.message_id}")
                return message.message_id
            else:
                raise Exception("No data returned from upsert operation")

        except Exception as e:
            logger.error(f"Failed to store message: {e}", exc_info=True)
            raise

    def get_recent_messages(
        self,
        group_id: str,
        limit: int = 20
    ) -> list[ConversationMessage]:
        """
        Get recent messages for a group (for LLM context).

        Args:
            group_id: The GroupMe group ID
            limit: Maximum number of messages to retrieve

        Returns:
            List of ConversationMessage objects, ordered by timestamp (oldest first)
        """
        logger.debug(f"Fetching {limit} recent messages for group {group_id}")

        try:
            result = (
                self.supabase.table("conversations")
                .select("*")
                .eq("group_id", group_id)
                .order("timestamp", desc=True)
                .limit(limit)
                .execute()
            )

            # Reverse to get oldest-first order (for LLM context)
            messages = [
                ConversationMessage(**row)
                for row in reversed(result.data)
            ]

            logger.info(f"Retrieved {len(messages)} recent messages")
            return messages

        except Exception as e:
            logger.error(f"Failed to fetch recent messages: {e}", exc_info=True)
            return []

    def get_workflow_messages(
        self,
        workflow_id: str
    ) -> list[ConversationMessage]:
        """
        Get all messages associated with a specific workflow.

        Args:
            workflow_id: The workflow UUID

        Returns:
            List of ConversationMessage objects, ordered by timestamp
        """
        logger.debug(f"Fetching messages for workflow {workflow_id}")

        try:
            result = (
                self.supabase.table("conversations")
                .select("*")
                .eq("workflow_id", workflow_id)
                .order("timestamp", desc=False)
                .execute()
            )

            messages = [ConversationMessage(**row) for row in result.data]

            logger.info(f"Retrieved {len(messages)} messages for workflow")
            return messages

        except Exception as e:
            logger.error(f"Failed to fetch workflow messages: {e}", exc_info=True)
            return []

    def get_message_by_id(
        self,
        message_id: str
    ) -> ConversationMessage | None:
        """
        Get a specific message by its GroupMe message_id.

        Args:
            message_id: The GroupMe message ID

        Returns:
            ConversationMessage if found, None otherwise
        """
        logger.debug(f"Fetching message {message_id}")

        try:
            result = (
                self.supabase.table("conversations")
                .select("*")
                .eq("message_id", message_id)
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                return ConversationMessage(**result.data[0])
            else:
                return None

        except Exception as e:
            logger.error(f"Failed to fetch message: {e}", exc_info=True)
            return None

    # =========================================================================
    # Workflow Operations
    # =========================================================================

    def create_workflow(
        self,
        group_id: str,
        workflow_type: str = "shift_coverage",
        initial_state: dict | None = None,
        user_id: str | None = None,
        squad_id: int | None = None
    ) -> Workflow:
        """
        Create a new workflow.

        Args:
            group_id: The GroupMe group ID
            workflow_type: Type of workflow (default: shift_coverage)
            initial_state: Optional initial state data
            user_id: GroupMe user ID who initiated the workflow
            squad_id: Squad number for squad-scoped workflows

        Returns:
            The created Workflow object

        Raises:
            Exception: If the database operation fails
        """
        logger.info(f"Creating new {workflow_type} workflow for group {group_id}, squad {squad_id}")

        try:
            now = datetime.now()
            expires_at = now + timedelta(hours=settings.workflow_expiration_hours)

            data = {
                "group_id": group_id,
                "workflow_type": workflow_type,
                "status": "NEW",
                "state_data": initial_state or {},
                "updated_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "metadata": {},
                "user_id": user_id,
                "squad_id": squad_id,
            }

            result = self.supabase.table("workflows").insert(data).execute()

            if result.data and len(result.data) > 0:
                workflow = Workflow(**result.data[0])
                logger.info(f"Created workflow {workflow.id}")
                return workflow
            else:
                raise Exception("No data returned from insert operation")

        except Exception as e:
            logger.error(f"Failed to create workflow: {e}", exc_info=True)
            raise

    def get_active_workflow(
        self,
        group_id: str
    ) -> Workflow | None:
        """
        Get the active workflow for a group (if any).

        Active statuses: NEW, WAITING_FOR_INPUT, READY, EXECUTING

        Args:
            group_id: The GroupMe group ID

        Returns:
            Workflow object if found, None otherwise
        """
        logger.debug(f"Looking for active workflow in group {group_id}")

        try:
            result = (
                self.supabase.table("workflows")
                .select("*")
                .eq("group_id", group_id)
                .in_("status", ["NEW", "WAITING_FOR_INPUT", "READY", "EXECUTING"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                workflow = Workflow(**result.data[0])
                logger.info(f"Found active workflow {workflow.id} with status {workflow.status}")
                return workflow
            else:
                logger.debug("No active workflow found")
                return None

        except Exception as e:
            logger.error(f"Failed to fetch active workflow: {e}", exc_info=True)
            return None

    def get_active_workflows_for_squad(
        self,
        squad_id: int,
        group_id: str
    ) -> list[Workflow]:
        """
        Get all active workflows for a specific squad.

        This supports squad-based workflow scoping where multiple squad members
        can contribute to the same workflow.

        Active statuses: NEW, WAITING_FOR_INPUT, READY, EXECUTING

        Args:
            squad_id: The squad number (34, 35, 42, 43, 54)
            group_id: The GroupMe group ID

        Returns:
            List of active Workflow objects for the squad (most recent first)
        """
        logger.debug(f"Looking for active workflows for squad {squad_id} in group {group_id}")

        try:
            result = (
                self.supabase.table("workflows")
                .select("*")
                .eq("squad_id", squad_id)
                .eq("group_id", group_id)
                .in_("status", ["NEW", "WAITING_FOR_INPUT", "READY", "EXECUTING"])
                .order("created_at", desc=True)
                .execute()
            )

            workflows = [Workflow(**row) for row in result.data]

            if workflows:
                logger.info(f"Found {len(workflows)} active workflow(s) for squad {squad_id}")
            else:
                logger.debug(f"No active workflows found for squad {squad_id}")

            return workflows

        except Exception as e:
            logger.error(f"Failed to fetch squad workflows: {e}", exc_info=True)
            return []

    def get_workflow_by_id(
        self,
        workflow_id: str
    ) -> Workflow | None:
        """
        Get a workflow by its ID.

        Args:
            workflow_id: The workflow UUID

        Returns:
            Workflow object if found, None otherwise
        """
        logger.debug(f"Fetching workflow {workflow_id}")

        try:
            result = (
                self.supabase.table("workflows")
                .select("*")
                .eq("id", workflow_id)
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                workflow = Workflow(**result.data[0])
                logger.debug(f"Retrieved workflow {workflow_id}")
                return workflow
            else:
                logger.warning(f"Workflow {workflow_id} not found")
                return None

        except Exception as e:
            logger.error(f"Failed to fetch workflow: {e}", exc_info=True)
            return None

    def update_workflow(
        self,
        workflow_id: str,
        status: str | None = None,
        state: dict | None = None,
        metadata: dict | None = None
    ) -> None:
        """
        Update a workflow's status and/or state.

        This is the primary method for updating workflows.
        Always sets updated_at explicitly (no database trigger).

        Args:
            workflow_id: The workflow UUID
            status: Optional new status
            state: Optional new state_data
            metadata: Optional new metadata

        Raises:
            Exception: If the database operation fails
        """
        logger.debug(f"Updating workflow {workflow_id}")

        try:
            # Build update dict - always set updated_at
            updates: dict[str, Any] = {
                "updated_at": datetime.now().isoformat()
            }

            if status is not None:
                updates["status"] = status
                logger.debug(f"  → status: {status}")

            if state is not None:
                updates["state_data"] = state
                logger.debug(f"  → state updated ({len(state)} keys)")

            if metadata is not None:
                updates["metadata"] = metadata
                logger.debug(f"  → metadata updated")

            result = (
                self.supabase.table("workflows")
                .update(updates)
                .eq("id", workflow_id)
                .execute()
            )

            if result.data and len(result.data) > 0:
                logger.info(f"Updated workflow {workflow_id}")
            else:
                logger.warning(f"Workflow {workflow_id} not found for update")

        except Exception as e:
            logger.error(f"Failed to update workflow: {e}", exc_info=True)
            raise

    def update_workflow_status(
        self,
        workflow_id: str,
        status: str
    ) -> None:
        """
        Update only the workflow status (convenience method).

        Args:
            workflow_id: The workflow UUID
            status: New status
        """
        self.update_workflow(workflow_id, status=status)

    # =========================================================================
    # Workflow Expiration
    # =========================================================================

    def expire_old_workflows(self) -> int:
        """
        Mark expired workflows as EXPIRED.

        This is called on startup and optionally during each poll cycle.
        Workflows are expired if:
        - Status is active (NEW, WAITING_FOR_INPUT, READY, EXECUTING)
        - expires_at < NOW()

        Returns:
            Number of workflows that were expired
        """
        logger.debug("Checking for expired workflows")

        try:
            now = datetime.now().isoformat()

            result = (
                self.supabase.table("workflows")
                .update({
                    "status": "EXPIRED",
                    "updated_at": now
                })
                .in_("status", ["NEW", "WAITING_FOR_INPUT", "READY", "EXECUTING"])
                .lt("expires_at", now)
                .execute()
            )

            count = len(result.data) if result.data else 0

            if count > 0:
                logger.info(f"Expired {count} workflow(s)")
            else:
                logger.debug("No workflows to expire")

            return count

        except Exception as e:
            logger.error(f"Failed to expire workflows: {e}", exc_info=True)
            return 0

    # =========================================================================
    # Startup/Recovery Operations
    # =========================================================================

    def restore_active_workflows(self) -> list[Workflow]:
        """
        Restore all active workflows from the database.

        This is called on startup to recover from process restarts.

        Returns:
            List of active Workflow objects
        """
        logger.info("Restoring active workflows from database")

        try:
            result = (
                self.supabase.table("workflows")
                .select("*")
                .in_("status", ["NEW", "WAITING_FOR_INPUT", "READY", "EXECUTING"])
                .order("created_at", desc=False)
                .execute()
            )

            workflows = [Workflow(**row) for row in result.data]

            logger.info(f"Restored {len(workflows)} active workflow(s)")

            # Log details of each restored workflow
            for wf in workflows:
                logger.debug(
                    f"  - Workflow {wf.id}: {wf.workflow_type} "
                    f"in group {wf.group_id}, status={wf.status}"
                )

            return workflows

        except Exception as e:
            logger.error(f"Failed to restore workflows: {e}", exc_info=True)
            return []

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_workflow_count_by_status(self) -> dict[str, int]:
        """
        Get count of workflows by status (for monitoring/debugging).

        Returns:
            Dictionary mapping status -> count
        """
        logger.debug("Counting workflows by status")

        try:
            result = self.supabase.table("workflows").select("status").execute()

            counts: dict[str, int] = {}
            for row in result.data:
                status = row["status"]
                counts[status] = counts.get(status, 0) + 1

            logger.debug(f"Workflow counts: {counts}")
            return counts

        except Exception as e:
            logger.error(f"Failed to count workflows: {e}", exc_info=True)
            return {}

    def get_message_count_by_group(self, limit: int = 10) -> dict[str, int]:
        """
        Get message counts by group (for monitoring/debugging).

        Args:
            limit: Maximum number of groups to return

        Returns:
            Dictionary mapping group_id -> message count
        """
        logger.debug("Counting messages by group")

        try:
            result = self.supabase.table("conversations").select("group_id").execute()

            counts: dict[str, int] = {}
            for row in result.data:
                group_id = row["group_id"]
                counts[group_id] = counts.get(group_id, 0) + 1

            # Sort by count and limit
            sorted_counts = dict(
                sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
            )

            logger.debug(f"Message counts (top {limit}): {sorted_counts}")
            return sorted_counts

        except Exception as e:
            logger.error(f"Failed to count messages: {e}", exc_info=True)
            return {}
