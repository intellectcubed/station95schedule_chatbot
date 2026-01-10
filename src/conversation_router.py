"""Conversation router for routing messages to appropriate handlers."""

import logging

from .admin_notifier import notify_admin
from .calendar_client import CalendarClient
from .config import settings
from .conversation_state_manager import ConversationStateManager
from .groupme_client import GroupMeClient
from .intent_detector import detect_intent
from .is_related_message_checker import is_message_related_to_workflow
from .models import ConversationMessage
from .roster import Roster
from .workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


class ConversationRouter:
    """
    Routes incoming messages to the appropriate handler.

    Routing logic (squad-based):
    1. Check for active workflows for sender's squad
    2. If squad workflows exist, use IsRelatedMessage to check if message is related
    3. If related:
       → Resume workflow
       → Increment interaction_count if asking for clarification
       → Escalate to admin if interaction_count > limit
    4. Else:
       → Evaluate if this is a new shift request
       → If yes: Start new workflow for that squad
       → If no: Ignore
    """

    def __init__(
        self,
        state_manager: ConversationStateManager,
        workflow_manager: WorkflowManager,
        groupme_client: GroupMeClient,
        roster: Roster,
        calendar_client: CalendarClient,
    ):
        """
        Initialize the conversation router.

        Args:
            state_manager: For checking active workflows
            workflow_manager: For starting/resuming workflows
            groupme_client: For sending messages
            roster: For user authorization and context
            calendar_client: For fetching schedule state
        """
        self.state_manager = state_manager
        self.workflow_manager = workflow_manager
        self.groupme_client = groupme_client
        self.roster = roster
        self.calendar_client = calendar_client

        logger.info("ConversationRouter initialized")

    def route_message(
        self,
        message: ConversationMessage
    ) -> dict:
        """
        Route a message to the appropriate handler.

        Args:
            message: The message to route

        Returns:
            Processing result dictionary with:
            - processed: bool (whether message was processed)
            - action: str (what action was taken)
            - workflow_id: str | None (if workflow was involved)
        """
        logger.info(
            f"Routing message from {message.user_name} in group {message.group_id}"
        )

        # Check if sender is authorized (in roster)
        if not self.roster.is_authorized(message.user_name):
            logger.warning(f"Unauthorized user: {message.user_name}")
            return {
                "processed": False,
                "action": "ignored",
                "reason": "unauthorized_user"
            }

        # Get sender context from roster
        sender_squad = self.roster.get_member_squad(message.user_name)
        sender_role = self.roster.get_member_role(message.user_name)

        logger.debug(
            f"Sender context: squad={sender_squad}, role={sender_role}"
        )

        # NEW LOGIC: Squad-based workflow routing with IsRelatedMessage check

        # Step 1: Check for active workflows for sender's squad
        if sender_squad:
            squad_workflows = self.state_manager.get_active_workflows_for_squad(
                squad_id=sender_squad,
                group_id=message.group_id
            )

            if squad_workflows:
                logger.info(
                    f"Found {len(squad_workflows)} active workflow(s) for squad {sender_squad}"
                )

                # Use IsRelatedMessage to check if this message is related to any workflow
                for workflow in squad_workflows:
                    # Get conversation history for this workflow
                    conversation_history = self.state_manager.get_workflow_messages(workflow.id)

                    # Check if message is related
                    is_related, confidence, reasoning = is_message_related_to_workflow(
                        message=message,
                        workflow=workflow,
                        conversation_history=conversation_history
                    )

                    logger.info(
                        f"IsRelatedMessage check for workflow {workflow.id}: "
                        f"related={is_related}, confidence={confidence}"
                    )

                    if is_related and confidence >= 50:
                        # Message is related to this workflow - resume it
                        logger.info(f"Resuming workflow {workflow.id} (related message detected)")

                        try:
                            # Link message to workflow
                            message.workflow_id = workflow.id

                            # Check interaction count before resuming
                            state_data = workflow.state_data or {}
                            interaction_count = state_data.get("interaction_count", 0)

                            # Check if we need to escalate to admin
                            if interaction_count >= settings.workflow_interaction_limit:
                                logger.warning(
                                    f"Workflow {workflow.id} has reached interaction limit "
                                    f"({interaction_count} >= {settings.workflow_interaction_limit})"
                                )

                                # Notify admin
                                notify_admin(
                                    "workflow_escalation",
                                    {
                                        "workflow_id": workflow.id,
                                        "user_name": message.user_name,
                                        "interaction_count": interaction_count,
                                        "squad": sender_squad,
                                    }
                                )

                                # Send message to chat
                                escalation_msg = (
                                    f"🆘 This conversation has become too complex. "
                                    f"I've notified an admin for assistance. "
                                    f"Please stand by for human help."
                                )
                                self.groupme_client.send_message(
                                    escalation_msg,
                                    workflow_id=workflow.id,
                                    group_id=message.group_id
                                )

                                # Mark workflow as EXPIRED (soft delete)
                                self.state_manager.update_workflow_status(
                                    workflow_id=workflow.id,
                                    status="EXPIRED"
                                )

                                return {
                                    "processed": True,
                                    "action": "escalated_to_admin",
                                    "workflow_id": workflow.id
                                }

                            # Resume workflow normally
                            updated_workflow = self.workflow_manager.resume_workflow(
                                workflow,
                                message
                            )

                            return {
                                "processed": True,
                                "action": "resumed_workflow",
                                "workflow_id": updated_workflow.id
                            }

                        except Exception as e:
                            logger.error(f"Failed to resume workflow: {e}", exc_info=True)
                            return {
                                "processed": False,
                                "action": "error",
                                "error": str(e)
                            }

                # No related workflows found - fall through to create new workflow or ignore

        # Step 2: No active workflows for squad or message not related - check if new shift request
        active_workflow = self.state_manager.get_active_workflow(message.group_id)

        if active_workflow:
            logger.info(
                f"Found active workflow {active_workflow.id} "
                f"with status {active_workflow.status}"
            )

            # If workflow is waiting for input, resume it
            if active_workflow.status == "WAITING_FOR_INPUT":
                logger.info(f"Resuming workflow {active_workflow.id}")

                try:
                    # Link message to workflow
                    message.workflow_id = active_workflow.id

                    # Resume workflow
                    updated_workflow = self.workflow_manager.resume_workflow(
                        active_workflow,
                        message
                    )

                    return {
                        "processed": True,
                        "action": "resumed_workflow",
                        "workflow_id": updated_workflow.id
                    }

                except Exception as e:
                    logger.error(f"Failed to resume workflow: {e}", exc_info=True)
                    return {
                        "processed": False,
                        "action": "error",
                        "error": str(e)
                    }

            else:
                # Workflow exists but not waiting for input
                # Reject new shift requests until current workflow completes
                logger.info(
                    f"Workflow {active_workflow.id} is active but not waiting for input "
                    f"(status={active_workflow.status})"
                )

                # Check if this looks like a new shift request using intent detection
                intent = detect_intent(message.message_text, message.timestamp)

                if intent["is_shift_coverage_message"] and intent["confidence"] >= 50:
                    logger.warning("Rejecting new shift request - workflow in progress")
                    try:
                        rejection_msg = (
                            "⏳ Please wait - there's already a shift request in progress. "
                            "Let's finish that one first!"
                        )
                        self.groupme_client.send_message(
                            rejection_msg,
                            workflow_id=active_workflow.id,
                            group_id=message.group_id
                        )
                    except Exception as e:
                        logger.error(f"Failed to send rejection message: {e}")

                    return {
                        "processed": False,
                        "action": "rejected",
                        "reason": "workflow_in_progress",
                        "workflow_id": active_workflow.id
                    }

                # Not a shift request, just ignore
                return {
                    "processed": False,
                    "action": "ignored",
                    "reason": "non_shift_message_with_active_workflow"
                }

        else:
            # No active workflow - use intent detection to check if this is a new shift request
            logger.debug("No active workflow found - detecting intent")

            # Phase 1: Intent detection
            intent = detect_intent(message.message_text, message.timestamp)

            logger.info(
                f"Intent detection: shift_coverage={intent['is_shift_coverage_message']}, "
                f"confidence={intent['confidence']}, days={intent['resolved_days']}"
            )

            if intent["is_shift_coverage_message"] and intent["confidence"] >= 50:
                logger.info("Message is a shift request - fetching schedule and starting workflow")

                try:
                    # Phase 2: Fetch schedule state for resolved days
                    schedule_state = None
                    if intent["resolved_days"]:
                        logger.info(f"Fetching schedule for days: {intent['resolved_days']}")
                        try:
                            # Fetch schedule from calendar service for the resolved days
                            # Convert YYYY-MM-DD to YYYYMMDD format
                            resolved_day = intent["resolved_days"][0]  # Use first day for now
                            date_yyyymmdd = resolved_day.replace("-", "")

                            schedule_state = self.calendar_client.get_schedule(
                                start_date=date_yyyymmdd,
                                end_date=date_yyyymmdd
                            )

                            # Check if the response contains an error
                            if isinstance(schedule_state, dict) and schedule_state.get("status") == "error":
                                logger.error(f"Calendar service returned error: {schedule_state.get('message')}")
                                schedule_state = None
                            else:
                                logger.info(f"✅ Fetched schedule state for {resolved_day}")

                        except Exception as e:
                            logger.warning(f"Failed to fetch schedule state: {e}")
                            schedule_state = None

                    # Start workflow with schedule state
                    workflow = self.workflow_manager.start_workflow(
                        group_id=message.group_id,
                        message=message,
                        sender_squad=sender_squad,
                        sender_role=sender_role,
                        resolved_days=intent["resolved_days"],
                        schedule_state=schedule_state
                    )

                    # Update message to link to workflow
                    message.workflow_id = workflow.id

                    return {
                        "processed": True,
                        "action": "started_workflow",
                        "workflow_id": workflow.id
                    }

                except Exception as e:
                    logger.error(f"Failed to start workflow: {e}", exc_info=True)
                    return {
                        "processed": False,
                        "action": "error",
                        "error": str(e)
                    }

            else:
                # Not a shift request, ignore
                logger.debug("Message doesn't look like a shift request - ignoring")
                return {
                    "processed": False,
                    "action": "ignored",
                    "reason": "not_shift_request"
                }

