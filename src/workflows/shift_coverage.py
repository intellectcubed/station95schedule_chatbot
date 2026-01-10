"""LangGraph workflow for shift coverage requests."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict, Annotated
import operator

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from ..config import settings
from ..models import WorkflowStateData, CalendarCommand
from ..tools import all_tools

logger = logging.getLogger(__name__)
llm_logger = logging.getLogger("llm")


# =============================================================================
# State Definition
# =============================================================================


class ShiftWorkflowState(TypedDict):
    """State that flows through the shift coverage workflow."""

    # Workflow metadata
    workflow_id: str
    group_id: str

    # User context
    sender_name: str
    sender_squad: int | None
    sender_role: str | None

    # Intent detection results (Phase 1)
    resolved_days: list[str]  # YYYY-MM-DD format from intent detection
    schedule_state: dict | None  # Current schedule from calendar service

    # Conversation history (accumulates messages)
    messages: Annotated[list, operator.add]

    # Extracted parameters (for single action or clarification)
    squad: int | None
    date: str | None  # YYYYMMDD
    shift_start: str | None  # HHMM
    shift_end: str | None  # HHMM
    action: Literal["noCrew", "addShift", "obliterateShift"] | None

    # Multiple parsed requests (all actions to execute)
    parsed_requests: list[dict]  # List of all actions from LLM

    # Validation
    validation_warnings: list[str]
    validation_passed: bool

    # Execution
    execution_result: dict | None

    # Control flow
    current_step: str
    missing_parameters: list[str]
    clarification_question: str | None
    reasoning: str | None  # LLM's reasoning (for no-action scenarios)


# =============================================================================
# Helper Functions
# =============================================================================


def load_system_prompt() -> str:
    """Load the system prompt from file."""
    prompt_path = Path(settings.system_prompt_path)

    if not prompt_path.exists():
        logger.error(f"System prompt file not found: {prompt_path}")
        raise FileNotFoundError(f"System prompt not found: {prompt_path}")

    return prompt_path.read_text()


def create_llm() -> ChatOpenAI:
    """Create and configure the LLM instance."""
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0.3,
        api_key=settings.openai_api_key
    )
    print(f'Here is the thingy: {settings.openai_api_key}')
    # Debug logging to verify actual model and API key presence
    logger.info(f"Created LLM with model_name attr: {getattr(llm, 'model_name', 'N/A')}")
    logger.info(f"Created LLM with model attr: {getattr(llm, 'model', 'N/A')}")
    logger.info(f"API key configured: {bool(settings.openai_api_key)}")
    logger.info(f"API key length: {len(settings.openai_api_key) if settings.openai_api_key else 0}")
    return llm


# =============================================================================
# Workflow Nodes
# =============================================================================


def extract_parameters_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Node 1: Extract parameters from the message using LLM.

    This node:
    - Uses the LLM with tools to extract squad, date, shift times, and action
    - Can extract multiple parameters from a single message
    - Identifies which parameters are still missing
    """
    logger.info("🤖 Node: Extract Parameters")

    try:
        # Load system prompt template
        system_prompt_template = load_system_prompt()

        # Format with current context
        message_time = datetime.now()

        # Format resolved days
        resolved_days = state.get("resolved_days", [])
        resolved_days_str = ", ".join(resolved_days) if resolved_days else "Not specified"

        # Format schedule state
        schedule_state = state.get("schedule_state")
        if schedule_state:
            # Parse the day_schedule JSON string if present
            if isinstance(schedule_state, dict) and "day_schedule" in schedule_state:
                try:
                    # Parse the nested JSON string
                    parsed_schedule = json.loads(schedule_state["day_schedule"])
                    # Create a clean format for the LLM
                    schedule_state_str = json.dumps({
                        "success": schedule_state.get("success"),
                        "action": schedule_state.get("action"),
                        "date": schedule_state.get("date"),
                        "schedule": parsed_schedule  # Now properly parsed
                    }, indent=2)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse day_schedule JSON: {e}")
                    schedule_state_str = json.dumps(schedule_state, indent=2)
            else:
                schedule_state_str = json.dumps(schedule_state, indent=2)
        else:
            schedule_state_str = "Schedule state not available"

        # Format the template first WITHOUT schedule_state (to avoid brace conflicts)
        system_prompt = system_prompt_template.format(
            current_datetime=message_time.strftime("%Y-%m-%d %H:%M:%S"),
            sender_name=state["sender_name"],
            sender_squad=state.get("sender_squad") or "Unknown",
            sender_role=state.get("sender_role") or "Unknown",
            resolved_days=resolved_days_str,
            schedule_state="PLACEHOLDER_FOR_SCHEDULE_STATE",
            user_message=state["messages"][-1].content if state["messages"] else ""
        )

        # Now replace the placeholder with the actual schedule (which contains braces)
        system_prompt = system_prompt.replace("PLACEHOLDER_FOR_SCHEDULE_STATE", schedule_state_str)

        # Create LLM with tools
        llm = create_llm()
        llm_with_tools = llm.bind_tools(all_tools)

        # Initialize messages if first call
        if not state.get("messages"):
            state["messages"] = []

        # Add system message if not present
        if not any(isinstance(msg, SystemMessage) for msg in state["messages"]):
            state["messages"] = [SystemMessage(content=system_prompt)] + state["messages"]

        # Log LLM request
        llm_logger.info("=" * 80)
        llm_logger.info("COMPONENT: Shift Coverage Workflow")
        llm_logger.info(f"MODEL: {llm.model_name}")
        llm_logger.info("LLM REQUEST (with tools)")
        llm_logger.info(f"Messages being sent ({len(state['messages'])} messages):")
        for i, msg in enumerate(state["messages"]):
            msg_type = msg.__class__.__name__
            llm_logger.info(f"  [{i}] {msg_type}:")
            llm_logger.info(msg.content)

        # Call LLM
        # Log the actual model being invoked
        logger.info(f"Invoking LLM - Model from object: {llm.model_name if hasattr(llm, 'model_name') else llm.model}")

        # Dump exact prompt for manual testing comparison
        # logger.info("=" * 80)
        # logger.info("EXACT PROMPT FOR MANUAL TESTING:")
        # for i, msg in enumerate(state["messages"]):
        #     logger.info(f"\n--- Message {i} ({msg.__class__.__name__}) ---")
        #     logger.info(msg.content)
        # logger.info("=" * 80)

        response = llm_with_tools.invoke(state["messages"])

        # Log LLM response
        llm_logger.info("-" * 80)
        llm_logger.info("LLM RESPONSE")
        llm_logger.info(f"Type: {response.__class__.__name__}")

        # Log what model OpenAI actually used (from response metadata)
        if hasattr(response, 'response_metadata'):
            actual_model = response.response_metadata.get('model_name', 'NOT_FOUND')
            llm_logger.info(f"ACTUAL MODEL USED BY API: {actual_model}")
            llm_logger.info(f"Full response_metadata: {response.response_metadata}")

        llm_logger.info(f"Content: {response.content}")
        if hasattr(response, "tool_calls") and response.tool_calls:
            llm_logger.info(f"Tool calls: {len(response.tool_calls)}")
            for tc in response.tool_calls:
                llm_logger.info(f"  - {tc.get('name', 'unknown')}: {tc.get('args', {})}")
        llm_logger.info("=" * 80)

        # Add response to messages
        new_messages = [response]

        # If LLM made tool calls, we need to execute them and call again
        if hasattr(response, "tool_calls") and response.tool_calls:
            logger.info(f"LLM made {len(response.tool_calls)} tool call(s)")

            # Execute tools (simplified - in production use ToolNode)
            from langgraph.prebuilt import ToolNode
            tool_node = ToolNode(all_tools)
            tool_result = tool_node.invoke({"messages": state["messages"] + [response]})

            if "messages" in tool_result:
                new_messages.extend(tool_result["messages"])

                # Call LLM again with tool results
                new_messages.append(
                    HumanMessage(content="Based on the tool results, provide your analysis in JSON format.")
                )

                # Log second LLM request
                all_messages = state["messages"] + new_messages
                llm_logger.info("=" * 80)
                llm_logger.info("COMPONENT: Shift Coverage Workflow")
                llm_logger.info(f"MODEL: {llm.model_name}")
                llm_logger.info("LLM REQUEST #2 (after tool execution)")
                llm_logger.info(f"Messages being sent ({len(all_messages)} messages):")
                for i, msg in enumerate(all_messages):  # Log all messages
                    msg_type = msg.__class__.__name__
                    content = msg.content if hasattr(msg, 'content') else str(msg)
                    llm_logger.info(f"  [{i}] {msg_type}:")
                    llm_logger.info(content)

                final_response = llm.invoke(all_messages)

                # Log second LLM response
                llm_logger.info("-" * 80)
                llm_logger.info("LLM RESPONSE #2")
                llm_logger.info(f"Type: {final_response.__class__.__name__}")
                llm_logger.info(f"Content: {final_response.content}")
                llm_logger.info("=" * 80)

                new_messages.append(final_response)
                response = final_response

        # Extract JSON from response
        content = response.content if hasattr(response, "content") else str(response)

        try:
            # Find JSON in response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1

            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                analysis = json.loads(json_str)

                logger.info(f"✅ Parsed LLM analysis: confidence={analysis.get('confidence', 0)}")

                # Store ALL parsed requests
                parsed_requests = analysis.get("parsed_requests", [])
                state["parsed_requests"] = parsed_requests

                logger.info(f"Extracted {len(parsed_requests)} action(s) to execute")

                # For clarification purposes, extract first request's parameters
                if parsed_requests and len(parsed_requests) > 0:
                    req = parsed_requests[0]  # First request for clarification context
                    state["squad"] = req.get("squad")
                    state["date"] = req.get("date")
                    state["shift_start"] = req.get("shift_start")
                    state["shift_end"] = req.get("shift_end")
                    state["action"] = req.get("action")

                # Extract missing parameters
                state["missing_parameters"] = analysis.get("missing_parameters", [])

                # Extract warnings and reasoning
                state["validation_warnings"] = analysis.get("warnings", [])

                # Store reasoning from LLM (used when no action needed)
                if "reasoning" in analysis:
                    state["reasoning"] = analysis["reasoning"]

                logger.info(
                    f"First action: squad={state.get('squad')}, date={state.get('date')}, "
                    f"shift={state.get('shift_start')}-{state.get('shift_end')}, action={state.get('action')}"
                )
                logger.info(f"Missing: {state['missing_parameters']}")
                if state.get("validation_warnings"):
                    logger.info(f"Warnings: {state['validation_warnings']}")

            else:
                logger.warning("No JSON found in LLM response")
                state["missing_parameters"] = ["squad", "date", "shift_start", "shift_end"]

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            state["missing_parameters"] = ["squad", "date", "shift_start", "shift_end"]

        # Update state
        state["messages"] = new_messages
        state["current_step"] = "extract_parameters"

        return state

    except Exception as e:
        logger.error(f"Error in extract_parameters_node: {e}", exc_info=True)
        state["missing_parameters"] = ["squad", "date", "shift_start", "shift_end"]
        return state


def request_clarification_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Node 2: Generate and send clarification question for missing parameter.

    This node:
    - Identifies the most important missing parameter
    - Generates a natural language question
    - Sets the clarification_question field
    - Marks workflow as WAITING_FOR_INPUT (caller will update status)
    """
    logger.info("❓ Node: Request Clarification")

    missing = state.get("missing_parameters", [])

    if not missing:
        logger.warning("request_clarification_node called but no missing parameters")
        return state

    # Priority order for asking questions
    priority_order = ["squad", "date", "shift_start", "shift_end", "action"]

    # Find first missing parameter in priority order
    param_to_ask = None
    for param in priority_order:
        if param in missing:
            param_to_ask = param
            break

    if not param_to_ask:
        param_to_ask = missing[0]

    # Generate question based on parameter
    questions = {
        "squad": f"Which squad won't be available? (34, 35, 42, 43, or 54)",
        "date": "What date are you referring to? (e.g., 'Saturday', 'December 25', or '12/25')",
        "shift_start": "What time does the shift start? (e.g., '6 PM' or '1800')",
        "shift_end": "What time does the shift end? (e.g., '6 AM' or '0600')",
        "action": "Do you want to remove the shift, add a shift, or obliterate it completely?"
    }

    question = questions.get(param_to_ask, f"Can you provide the {param_to_ask}?")

    logger.info(f"Asking for: {param_to_ask}")
    logger.info(f"Question: {question}")

    state["clarification_question"] = question
    state["current_step"] = "request_clarification"

    return state


def validate_parameters_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Node 3: Validate that all parameters are present and valid.

    This node:
    - Verifies all required parameters are present
    - Validates formats (date, times, squad number)
    - Sets validation_passed flag
    """
    logger.info("✅ Node: Validate Parameters")

    warnings = []
    passed = True

    # Check all parameters are present
    required = ["squad", "date", "shift_start", "shift_end"]
    for param in required:
        if not state.get(param):
            warnings.append(f"Missing required parameter: {param}")
            passed = False

    # Validate squad number
    squad = state.get("squad")
    if squad and squad not in [34, 35, 42, 43, 54]:
        warnings.append(f"Invalid squad number: {squad}")
        passed = False

    # Validate date format (YYYYMMDD)
    date = state.get("date")
    if date and (len(date) != 8 or not date.isdigit()):
        warnings.append(f"Invalid date format: {date} (expected YYYYMMDD)")
        passed = False

    # Validate time formats (HHMM)
    for time_field in ["shift_start", "shift_end"]:
        time_val = state.get(time_field)
        if time_val and (len(time_val) != 4 or not time_val.isdigit()):
            warnings.append(f"Invalid {time_field} format: {time_val} (expected HHMM)")
            passed = False

    # Infer action if not set
    if not state.get("action"):
        state["action"] = "noCrew"  # Default action
        logger.info("Action not specified, defaulting to 'noCrew'")

    state["validation_warnings"] = warnings
    state["validation_passed"] = passed
    state["current_step"] = "validate"

    if passed:
        logger.info("✅ Validation PASSED")
    else:
        logger.warning(f"❌ Validation FAILED: {warnings}")

    return state


def execute_command_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Node 4: Execute the calendar commands.

    This node:
    - Loops through ALL parsed_requests
    - Builds CalendarCommand for each
    - Sends to calendar service
    - Stores execution results
    - Marks workflow as COMPLETED (caller will update status)
    """
    logger.info("⚡ Node: Execute Commands")

    try:
        parsed_requests = state.get("parsed_requests", [])

        if not parsed_requests:
            # Fallback to single command from state fields
            parsed_requests = [{
                "action": state["action"],
                "squad": state["squad"],
                "date": state["date"],
                "shift_start": state["shift_start"],
                "shift_end": state["shift_end"]
            }]

        logger.info(f"Preparing {len(parsed_requests)} command(s) for execution")

        commands = []
        for idx, req in enumerate(parsed_requests, 1):
            command = CalendarCommand(
                action=req.get("action"),
                squad=req.get("squad"),
                date=req.get("date"),
                shift_start=req.get("shift_start"),
                shift_end=req.get("shift_end"),
                preview=False
            )

            logger.info(
                f"Command {idx}/{len(parsed_requests)}: {command.action} for squad {command.squad} "
                f"on {command.date} ({command.shift_start}-{command.shift_end})"
            )

            commands.append(command.model_dump())

        # Note: Actual execution will be done by WorkflowManager
        # This node just prepares the commands
        state["execution_result"] = {
            "commands": commands,  # List of commands (not single "command")
            "status": "prepared",
            "message": f"Prepared {len(commands)} command(s) for execution"
        }

        state["current_step"] = "execute"

        logger.info(f"✅ Prepared {len(commands)} command(s) for execution")

    except Exception as e:
        logger.error(f"Error preparing commands: {e}", exc_info=True)
        state["execution_result"] = {
            "status": "error",
            "error": str(e)
        }

    return state


def complete_no_action_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Node 5: Complete workflow when no action is needed.

    This node:
    - Sends the LLM's warnings/reasoning to the user
    - Marks the workflow as completed
    - Used when LLM determines no calendar changes are necessary
    """
    logger.info("ℹ️  Node: Complete No Action")

    # Store the LLM's message for the workflow manager to send
    warnings = state.get("validation_warnings", [])
    reasoning = state.get("reasoning", "")

    if warnings:
        # The workflow manager will send these warnings
        logger.info(f"LLM provided {len(warnings)} warning(s) to send to user")
        for warning in warnings:
            logger.info(f"  - {warning}")
    elif reasoning:
        # If no warnings but there's reasoning, use that
        state["validation_warnings"] = [reasoning]
        logger.info(f"Using reasoning as message: {reasoning[:100]}...")
    else:
        # Fallback message
        state["validation_warnings"] = ["No action needed based on the current schedule."]
        logger.info("No warnings or reasoning - using fallback message")

    # Mark as completed (no execution needed)
    state["execution_result"] = {
        "status": "no_action_needed",
        "message": "No calendar changes required"
    }
    state["current_step"] = "complete_no_action"

    logger.info("✅ Workflow completed with no action needed")

    return state


# =============================================================================
# Conditional Routing
# =============================================================================


def route_after_extraction(state: ShiftWorkflowState) -> Literal["validate", "clarify", "complete_no_action"]:
    """
    Route after parameter extraction.

    If no actions needed (empty parsed_requests), complete with warnings.
    If parameters are missing, ask for clarification.
    Otherwise, proceed to validation.
    """
    parsed_requests = state.get("parsed_requests", [])
    missing = state.get("missing_parameters", [])

    # Check if LLM determined no action is needed
    if len(parsed_requests) == 0:
        logger.info("→ Route to COMPLETE_NO_ACTION (0 actions to execute)")
        return "complete_no_action"
    elif missing:
        logger.info(f"→ Route to CLARIFY ({len(missing)} missing parameters)")
        return "clarify"
    else:
        logger.info("→ Route to VALIDATE")
        return "validate"


def route_after_validation(state: ShiftWorkflowState) -> Literal["execute", "end"]:
    """
    Route after validation.

    If validation passed, execute the command.
    Otherwise, end (warnings will be sent by caller).
    """
    passed = state.get("validation_passed", False)

    if passed:
        logger.info("→ Route to EXECUTE")
        return "execute"
    else:
        logger.info("→ Route to END (validation failed)")
        return "end"


# =============================================================================
# Graph Construction
# =============================================================================


def create_shift_workflow() -> StateGraph:
    """
    Create and compile the shift coverage workflow.

    Workflow flow:
    1. extract_parameters → (no actions?) → complete_no_action OR (has missing?) → clarify OR validate
    2. complete_no_action → END (no action needed)
    3. clarify → END (pause for user input)
    4. validate → (passed?) → execute OR end
    5. execute → END

    Returns:
        Compiled LangGraph workflow
    """
    logger.info("Building shift coverage workflow graph")

    # Create graph
    workflow = StateGraph(ShiftWorkflowState)

    # Add nodes
    workflow.add_node("extract_parameters", extract_parameters_node)
    workflow.add_node("clarify", request_clarification_node)
    workflow.add_node("validate", validate_parameters_node)
    workflow.add_node("execute", execute_command_node)
    workflow.add_node("complete_no_action", complete_no_action_node)

    # Set entry point
    workflow.set_entry_point("extract_parameters")

    # Add conditional edges
    workflow.add_conditional_edges(
        "extract_parameters",
        route_after_extraction,
        {
            "complete_no_action": "complete_no_action",
            "clarify": "clarify",
            "validate": "validate"
        }
    )

    workflow.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "execute": "execute",
            "end": END
        }
    )

    # Simple edges (always go to END)
    workflow.add_edge("complete_no_action", END)  # No action needed
    workflow.add_edge("clarify", END)  # Pause here for user input
    workflow.add_edge("execute", END)  # Done after execution

    # Compile
    compiled = workflow.compile()

    logger.info("✅ Shift coverage workflow compiled")

    return compiled
