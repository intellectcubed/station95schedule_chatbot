"""IsRelatedMessage checker for determining if a message is related to an existing workflow."""

import json
import logging
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import settings
from .models import Workflow, ConversationMessage

logger = logging.getLogger(__name__)
llm_logger = logging.getLogger("llm")


def load_is_related_prompt() -> str:
    """Load the IsRelatedMessage prompt from file."""
    prompt_path = Path("ai_prompts/IsRelatedMessagePrompt.md")

    if not prompt_path.exists():
        logger.error(f"IsRelatedMessage prompt file not found: {prompt_path}")
        raise FileNotFoundError(f"IsRelatedMessage prompt not found: {prompt_path}")

    return prompt_path.read_text()


def create_is_related_llm() -> ChatOpenAI:
    """Create a lightweight LLM for IsRelatedMessage check."""
    return ChatOpenAI(
        model="gpt-4o-mini",  # Fast, cheap model for classification
        temperature=0.1,  # Low temperature for consistent classification
        api_key=settings.openai_api_key
    )


def is_message_related_to_workflow(
    message: ConversationMessage,
    workflow: Workflow,
    conversation_history: list[ConversationMessage]
) -> tuple[bool, int, str]:
    """
    Determine if a message is related to an existing workflow.

    Args:
        message: The new message to check
        workflow: The existing workflow
        conversation_history: Recent messages in the conversation

    Returns:
        Tuple of (is_related, confidence, reasoning)
    """
    logger.info(f"Checking if message is related to workflow {workflow.id}")

    try:
        # Load prompt template
        prompt_template = load_is_related_prompt()

        # Format conversation history
        history_lines = []
        for msg in conversation_history[-10:]:  # Last 10 messages
            history_lines.append(f"{msg.user_name}: {msg.message_text}")
        conversation_history_str = "\n".join(history_lines) if history_lines else "No previous messages"

        # Extract workflow details from state_data
        state_data = workflow.state_data or {}
        workflow_squad = state_data.get("sender_squad") or workflow.squad_id or "Unknown"
        workflow_date = state_data.get("date") or "Unknown"
        initiating_user = state_data.get("sender_name", "Unknown")

        # Format prompt
        prompt = prompt_template.format(
            workflow_type=workflow.workflow_type,
            workflow_status=workflow.status,
            squad=workflow_squad,
            date=workflow_date,
            initiating_user=initiating_user,
            conversation_history=conversation_history_str,
            new_message_user=message.user_name,
            new_message_text=message.message_text
        )

        # Create messages
        messages = [
            SystemMessage(content="You are a conversation continuity analyzer."),
            HumanMessage(content=prompt)
        ]

        # Call LLM
        llm = create_is_related_llm()

        # Log LLM request
        llm_logger.info("=" * 80)
        llm_logger.info("COMPONENT: IsRelatedMessage Checker")
        llm_logger.info("MODEL: gpt-4o-mini")
        llm_logger.info("LLM REQUEST")
        llm_logger.info(f"Number of messages: {len(messages)}")
        for i, msg in enumerate(messages):
            msg_type = msg.__class__.__name__
            llm_logger.info(f"  [{i}] {msg_type}:")
            llm_logger.info(msg.content[:500])  # Truncate to avoid too much logging
        llm_logger.info("-" * 80)

        response = llm.invoke(messages)

        # Log LLM response
        llm_logger.info("LLM RESPONSE")
        llm_logger.info(f"Type: {response.__class__.__name__}")
        content = response.content if hasattr(response, "content") else str(response)
        llm_logger.info(f"Content: {content}")
        llm_logger.info("=" * 80)

        # Parse JSON response
        json_start = content.find("{")
        json_end = content.rfind("}") + 1

        if json_start != -1 and json_end > json_start:
            json_str = content[json_start:json_end]
            result = json.loads(json_str)

            is_related = result.get("is_related", False)
            confidence = result.get("confidence", 0)
            reasoning = result.get("reasoning", "")

            logger.info(
                f"✅ IsRelatedMessage result: related={is_related}, "
                f"confidence={confidence}, reasoning={reasoning}"
            )

            return (is_related, confidence, reasoning)

        else:
            logger.warning("No JSON found in IsRelatedMessage response")
            return (False, 0, "Failed to parse LLM response")

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from IsRelatedMessage check: {e}")
        return (False, 0, "JSON parse error")

    except Exception as e:
        logger.error(f"Error in IsRelatedMessage check: {e}", exc_info=True)
        return (False, 0, f"Error: {str(e)}")
