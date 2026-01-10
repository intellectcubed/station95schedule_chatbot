"""Agentic coordinator - main orchestrator for the stateful chat system."""

import logging

from .calendar_client import CalendarClient
from .config import settings
from .conversation_router import ConversationRouter
from .conversation_state_manager import ConversationStateManager
from .groupme_client import GroupMeClient
from .models import ConversationMessage, GroupMeMessage
from .roster import Roster
from .workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


class AgenticCoordinator:
    """
    Main orchestrator for the stateful agentic chat system.

    This class:
    - Initializes all components
    - Expires old workflows on startup
    - Restores active workflows from database
    - Routes incoming messages
    - Coordinates end-to-end message processing

    This is the single entry point for processing messages.
    """

    def __init__(self):
        """Initialize the agentic coordinator and all its components."""
        logger.info("=" * 60)
        logger.info("Initializing AgenticCoordinator")

        # Initialize state manager (connects to Supabase)
        logger.info("→ Initializing ConversationStateManager")
        self.state_manager = ConversationStateManager()

        # Initialize external service clients
        logger.info("→ Initializing CalendarClient")
        self.calendar_client = CalendarClient()

        logger.info("→ Initializing GroupMeClient")
        self.groupme_client = GroupMeClient(state_manager=self.state_manager)

        # Load roster
        logger.info(f"→ Loading Roster from {settings.roster_file_path}")
        self.roster = Roster(settings.roster_file_path)
        logger.info(f"   Loaded {len(self.roster.members)} members")

        # Initialize workflow manager
        logger.info("→ Initializing WorkflowManager")
        self.workflow_manager = WorkflowManager(
            state_manager=self.state_manager,
            calendar_client=self.calendar_client,
            groupme_client=self.groupme_client,
        )

        # Initialize conversation router
        logger.info("→ Initializing ConversationRouter")
        self.router = ConversationRouter(
            state_manager=self.state_manager,
            workflow_manager=self.workflow_manager,
            groupme_client=self.groupme_client,
            roster=self.roster,
            calendar_client=self.calendar_client,
        )

        # Cleanup and restore workflows
        logger.info("→ Running startup tasks")
        self._expire_old_workflows()
        self._restore_workflows()

        logger.info("✅ AgenticCoordinator initialized successfully")
        logger.info("=" * 60)

    def _expire_old_workflows(self) -> None:
        """Mark expired workflows as EXPIRED."""
        logger.info("Checking for expired workflows...")
        count = self.state_manager.expire_old_workflows()

        if count > 0:
            logger.info(f"⏰ Expired {count} old workflow(s)")
        else:
            logger.debug("No workflows to expire")

    def _restore_workflows(self) -> None:
        """Restore active workflows from database on startup."""
        logger.info("Restoring active workflows from database...")
        workflows = self.state_manager.restore_active_workflows()

        if workflows:
            logger.info(f"🔄 Restored {len(workflows)} active workflow(s)")
            for wf in workflows:
                logger.debug(
                    f"   - {wf.id}: {wf.workflow_type} in group {wf.group_id}, "
                    f"status={wf.status}"
                )
        else:
            logger.debug("No active workflows to restore")

    def process_message(
        self,
        message: GroupMeMessage
    ) -> dict:
        """
        Process a message through the agentic system.

        This is the main entry point for message processing.

        Steps:
        1. Convert GroupMeMessage to ConversationMessage
        2. Store message in database
        3. Route to appropriate handler (router decides what to do)
        4. Return processing result

        Args:
            message: GroupMeMessage from GroupMe API

        Returns:
            Processing result dictionary with:
            - processed: bool
            - action: str (what happened)
            - workflow_id: str | None
        """
        logger.info("=" * 60)
        logger.info(
            f"Processing message from {message.sender_name}: "
            f"{message.message_text[:50]}..."
        )

        try:
            # Convert to ConversationMessage
            conv_message = ConversationMessage.from_groupme_message(message)

            # Route to appropriate handler (this may set workflow_id)
            result = self.router.route_message(conv_message)

            logger.info(
                f"Routing complete: action={result.get('action')}, "
                f"processed={result.get('processed')}"
            )

            # Store message in database (now with workflow_id set if applicable)
            message_id = self.state_manager.store_message(conv_message)

            logger.info(f"Stored message {message_id} in database")

            # Add message_id to result
            result["message_id"] = message_id

            return result

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return {
                "processed": False,
                "action": "error",
                "error": str(e)
            }

        finally:
            logger.info("=" * 60)

    def get_status(self) -> dict:
        """
        Get system status (for monitoring/debugging).

        Returns:
            Status dictionary with workflow and message counts
        """
        logger.debug("Getting system status")

        try:
            workflow_counts = self.state_manager.get_workflow_count_by_status()
            message_counts = self.state_manager.get_message_count_by_group(limit=5)

            return {
                "status": "healthy",
                "workflows_by_status": workflow_counts,
                "messages_by_group": message_counts,
                "roster_member_count": len(self.roster.members)
            }

        except Exception as e:
            logger.error(f"Error getting status: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
