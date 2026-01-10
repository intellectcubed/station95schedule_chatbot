"""Workflow manager for executing and managing LangGraph workflows."""

import logging
from datetime import datetime

from langchain_core.messages import HumanMessage

from .calendar_client import CalendarClient
from .conversation_state_manager import ConversationStateManager
from .groupme_client import GroupMeClient
from .models import CalendarCommand, ConversationMessage, Workflow, WorkflowStateData
from .state_serializer import serialize_state, deserialize_state
from .workflows import create_shift_workflow

logger = logging.getLogger(__name__)


class WorkflowManager:
    """
    Manages workflow execution and lifecycle.

    This class:
    - Starts new workflows
    - Resumes paused workflows
    - Executes workflow steps using LangGraph
    - Persists state to Supabase
    - Sends messages to GroupMe
    - Executes calendar commands
    """

    def __init__(
        self,
        state_manager: ConversationStateManager,
        calendar_client: CalendarClient,
        groupme_client: GroupMeClient,
    ):
        """
        Initialize the workflow manager.

        Args:
            state_manager: For persisting workflow state
            calendar_client: For executing calendar commands
            groupme_client: For sending messages to chat
        """
        self.state_manager = state_manager
        self.calendar_client = calendar_client
        self.groupme_client = groupme_client

        # Create the workflow graph (compiled LangGraph)
        self.workflow_graph = create_shift_workflow()

        logger.info("WorkflowManager initialized with LangGraph workflow")

    def start_workflow(
        self,
        group_id: str,
        message: ConversationMessage,
        sender_squad: int | None,
        sender_role: str | None,
        resolved_days: list[str] | None = None,
        schedule_state: dict | None = None
    ) -> Workflow:
        """
        Start a new workflow.

        Args:
            group_id: GroupMe group ID
            message: The message that triggered the workflow
            sender_squad: Squad number of sender (from roster)
            sender_role: Role of sender (from roster)
            resolved_days: Days resolved from intent detection (YYYY-MM-DD format)
            schedule_state: Current schedule state from calendar service

        Returns:
            The created Workflow object

        Raises:
            Exception: If workflow creation or execution fails
        """
        logger.info(f"Starting new workflow for group {group_id}, squad {sender_squad}")

        # Create initial state as a plain dict
        # (LangGraph will handle message objects internally)
        initial_state = {
            "workflow_id": "",  # Will be set after DB creation
            "group_id": group_id,
            "sender_name": message.user_name,
            "sender_squad": sender_squad,
            "sender_role": sender_role,
            "resolved_days": resolved_days or [],  # From intent detection
            "schedule_state": schedule_state,  # From calendar service
            "messages": [],  # Will be populated by workflow
            "squad": None,
            "date": None,
            "shift_start": None,
            "shift_end": None,
            "action": None,
            "parsed_requests": [],  # List of all actions to execute
            "validation_warnings": [],
            "validation_passed": True,
            "execution_result": None,
            "current_step": "extract_parameters",
            "missing_parameters": [],
            "clarification_question": None,
            "interaction_count": 0,  # Track clarification interactions
        }

        # Create workflow in database with user_id and squad_id
        workflow = self.state_manager.create_workflow(
            group_id=group_id,
            workflow_type="shift_coverage",
            initial_state=initial_state,
            user_id=message.user_id,
            squad_id=sender_squad
        )

        logger.info(f"Created workflow {workflow.id}")

        # Update state with workflow_id and add initial message
        initial_state["workflow_id"] = workflow.id
        initial_state["messages"] = [HumanMessage(content=message.message_text)]

        # Execute first step
        result_state = self._execute_workflow_step(workflow, initial_state)

        # Serialize state before saving to database
        serialized_state = serialize_state(result_state)

        # Update workflow in database
        self._update_workflow_from_state(workflow, serialized_state)

        # Handle any outputs (clarification questions, warnings, etc.)
        self._handle_workflow_outputs(workflow, result_state)

        logger.info(f"Workflow {workflow.id} started and executed first step")

        return workflow

    def resume_workflow(
        self,
        workflow: Workflow,
        message: ConversationMessage
    ) -> Workflow:
        """
        Resume a paused workflow with new user input.

        Args:
            workflow: The workflow to resume
            message: New message from user

        Returns:
            Updated Workflow object

        Raises:
            Exception: If workflow execution fails
        """
        logger.info(f"Resuming workflow {workflow.id}")

        # Load current state and deserialize
        state_dict = workflow.state_data
        state_dict = deserialize_state(state_dict)

        # Clean up messages - remove tool-related messages from previous run
        # Keep only SystemMessage and reconstruct the full user message
        if "messages" in state_dict and state_dict["messages"]:
            from langchain_core.messages import SystemMessage, HumanMessage as HM, AIMessage, ToolMessage

            # Find the system message and first human message
            system_message = None
            original_human_message = None

            for msg in state_dict["messages"]:
                if isinstance(msg, SystemMessage):
                    system_message = msg
                elif isinstance(msg, HM) and original_human_message is None:
                    # Get the first human message (the original request)
                    original_human_message = msg

            # Reconstruct full context by combining original message + clarification
            if original_human_message:
                # Combine original message with the clarification answer
                missing_params = state_dict.get("missing_parameters", [])
                param_name = missing_params[0] if missing_params else "information"

                reconstructed_content = (
                    f"{original_human_message.content}\n\n"
                    f"The {param_name} is {message.message_text}"
                )

                logger.info(
                    f"Reconstructing message context: original + clarification for '{param_name}'"
                )

                # Start fresh with system message and reconstructed human message
                state_dict["messages"] = []
                if system_message:
                    state_dict["messages"].append(system_message)
                state_dict["messages"].append(HumanMessage(content=reconstructed_content))
            else:
                # Fallback: just use the new message
                state_dict["messages"] = []
                if system_message:
                    state_dict["messages"].append(system_message)
                state_dict["messages"].append(HumanMessage(content=message.message_text))
        else:
            # No previous messages, start fresh
            state_dict["messages"] = [HumanMessage(content=message.message_text)]

        # Execute next step
        result_state = self._execute_workflow_step(workflow, state_dict)

        # Serialize state before saving to database
        serialized_state = serialize_state(result_state)

        # Update workflow in database
        self._update_workflow_from_state(workflow, serialized_state)

        # Handle any outputs
        self._handle_workflow_outputs(workflow, result_state)

        logger.info(f"Workflow {workflow.id} resumed and executed")

        return workflow

    def _execute_workflow_step(
        self,
        workflow: Workflow,
        state: dict
    ) -> dict:
        """
        Execute one step of the workflow using LangGraph.

        Args:
            workflow: The workflow being executed
            state: Current state dictionary

        Returns:
            Updated state dictionary after execution
        """
        logger.debug(f"Executing workflow step for {workflow.id}")

        try:
            # Invoke the LangGraph workflow
            result = self.workflow_graph.invoke(state)

            logger.debug(f"Workflow step completed: current_step={result.get('current_step')}")

            return result

        except Exception as e:
            logger.error(f"Error executing workflow step: {e}", exc_info=True)
            raise

    def _update_workflow_from_state(
        self,
        workflow: Workflow,
        state: dict
    ) -> None:
        """
        Update workflow in database based on execution result.

        Determines new status and updates both status and state.

        Args:
            workflow: The workflow to update
            state: The result state from LangGraph execution
        """
        current_step = state.get("current_step", "")
        missing_params = state.get("missing_parameters", [])
        validation_passed = state.get("validation_passed", True)
        execution_result = state.get("execution_result")

        # Determine new status
        new_status = workflow.status

        if current_step == "request_clarification":
            new_status = "WAITING_FOR_INPUT"
        elif current_step == "complete_no_action":
            new_status = "COMPLETED"
        elif current_step == "validate" and validation_passed:
            new_status = "READY"
        elif current_step == "execute":
            if execution_result and execution_result.get("status") == "prepared":
                new_status = "EXECUTING"
            else:
                new_status = "COMPLETED"

        logger.debug(f"Updating workflow {workflow.id}: status={new_status}, current_step={current_step}")

        # Update in database (state is already serialized by caller)
        self.state_manager.update_workflow(
            workflow_id=workflow.id,
            status=new_status,
            state=state
        )

        # Update local workflow object
        workflow.status = new_status
        workflow.state_data = state

    def _handle_workflow_outputs(
        self,
        workflow: Workflow,
        state: dict
    ) -> None:
        """
        Handle workflow outputs (send messages, execute commands, etc.).

        Args:
            workflow: The workflow
            state: Current state with outputs
        """
        # Handle clarification questions
        clarification = state.get("clarification_question")
        if clarification:
            logger.info(f"Sending clarification question: {clarification}")
            try:
                self.groupme_client.send_message(
                    clarification,
                    workflow_id=workflow.id,
                    group_id=workflow.group_id
                )
            except Exception as e:
                logger.error(f"Failed to send clarification question: {e}")

        # Handle warnings
        warnings = state.get("validation_warnings", [])
        for warning in warnings:
            logger.info(f"Sending warning: {warning}")
            try:
                self.groupme_client.send_warning(
                    warning,
                    workflow_id=workflow.id,
                    group_id=workflow.group_id
                )
            except Exception as e:
                logger.error(f"Failed to send warning: {e}")

        # Handle command execution (supports multiple commands)
        execution_result = state.get("execution_result")
        if execution_result and execution_result.get("status") == "prepared":
            # Support both old "command" (singular) and new "commands" (plural)
            commands_list = execution_result.get("commands") or [execution_result.get("command")]
            commands_list = [cmd for cmd in commands_list if cmd is not None]

            if commands_list:
                logger.info(f"Executing {len(commands_list)} calendar command(s)")

                results = []
                successful = 0
                failed = 0

                for idx, command_dict in enumerate(commands_list, 1):
                    try:
                        command = CalendarCommand(**command_dict)
                        logger.info(
                            f"Executing command {idx}/{len(commands_list)}: "
                            f"{command.action} for Squad {command.squad} on {command.date}"
                        )

                        result = self.calendar_client.send_command_with_retry(command)
                        results.append({
                            "command": command_dict,
                            "status": "success",
                            "response": result
                        })
                        successful += 1

                    except Exception as e:
                        logger.error(f"Failed to execute command {idx}: {e}", exc_info=True)
                        results.append({
                            "command": command_dict,
                            "status": "error",
                            "error": str(e)
                        })
                        failed += 1

                # Update state with all execution results
                state["execution_result"]["status"] = "success" if failed == 0 else "partial"
                state["execution_result"]["results"] = results
                state["execution_result"]["summary"] = {
                    "total": len(commands_list),
                    "successful": successful,
                    "failed": failed
                }

                # Serialize state before saving
                serialized_state = serialize_state(state)

                # Update workflow to COMPLETED
                self.state_manager.update_workflow(
                    workflow_id=workflow.id,
                    status="COMPLETED",
                    state=serialized_state
                )

                # Send confirmation to chat
                if successful > 0:
                    if successful == 1 and len(commands_list) == 1:
                        # Single command confirmation
                        cmd = CalendarCommand(**commands_list[0])
                        confirmation = (
                            f"✅ Updated schedule: {cmd.action} for Squad {cmd.squad} "
                            f"on {cmd.date} ({cmd.shift_start}-{cmd.shift_end})"
                        )
                    else:
                        # Multiple commands confirmation
                        confirmation = (
                            f"✅ Updated schedule: {successful} action(s) completed"
                        )
                        if failed > 0:
                            confirmation += f", {failed} failed"

                    self.groupme_client.send_message(
                        confirmation,
                        workflow_id=workflow.id,
                        group_id=workflow.group_id
                    )

                if failed > 0:
                    # Send error details
                    error_msg = f"❌ {failed} command(s) failed to execute"
                    self.groupme_client.send_message(
                        error_msg,
                        workflow_id=workflow.id,
                        group_id=workflow.group_id
                    )

                logger.info(
                    f"Calendar commands executed: {successful} successful, {failed} failed"
                )
