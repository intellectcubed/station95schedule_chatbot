"""Intent detection for determining if a message is shift-related and resolving dates.

This module provides Phase 1 of the two-phase LLM interaction:
1. Determine if message is shift coverage related
2. Resolve what day(s) the message refers to

This enables fetching the calendar state before the full workflow execution.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import settings

logger = logging.getLogger(__name__)
llm_logger = logging.getLogger("llm")


class IntentDetectionResult(TypedDict):
    """Result from intent detection."""
    is_shift_coverage_message: bool
    resolved_days: list[str]  # YYYY-MM-DD format
    confidence: int  # 0-100


def load_intent_prompt() -> str:
    """Load the intent detection prompt from file."""
    prompt_path = Path("ai_prompts/IntentDetectionPrompt.md")

    if not prompt_path.exists():
        logger.error(f"Intent detection prompt file not found: {prompt_path}")
        raise FileNotFoundError(f"Intent detection prompt not found: {prompt_path}")

    return prompt_path.read_text()


def create_intent_llm() -> ChatOpenAI:
    """Create a lightweight LLM for intent detection."""
    return ChatOpenAI(
        model="gpt-4o",  # Faster, cheaper model for simple classification
        # model="gpt-4o-mini",  # Faster, cheaper model for simple classification
        temperature=0.1,  # Low temperature for consistent classification
        api_key=settings.openai_api_key
    )


def detect_intent(
    message_text: str,
    current_timestamp: int | None = None
) -> IntentDetectionResult:
    """
    Detect if a message is shift coverage related and resolve the day(s).

    This is Phase 1 of the two-phase LLM interaction.

    Args:
        message_text: The message to analyze
        current_timestamp: Unix timestamp for date context (defaults to now)

    Returns:
        IntentDetectionResult with is_shift_coverage_message, resolved_days, and confidence
    """
    logger.info("🔍 Phase 1: Detecting intent and resolving days")

    try:
        # Get current time context
        if current_timestamp:
            current_time = datetime.fromtimestamp(current_timestamp)
        else:
            current_time = datetime.now()

        # Build day-of-week reference for next 7 days
        from datetime import timedelta
        day_week_reference_lines = []
        for i in range(7):
            future_date = current_time + timedelta(days=i)
            day_name = future_date.strftime("%A")
            date_str = future_date.strftime("%Y-%m-%d")
            if i == 0:
                day_week_reference_lines.append(f"  - Today: {day_name} ({date_str})")
            elif i == 1:
                day_week_reference_lines.append(f"  - Tomorrow: {day_name} ({date_str})")
            else:
                day_week_reference_lines.append(f"  - {day_name}: {date_str}")

        day_week_reference = "\n".join(day_week_reference_lines)

        # Load and format prompt
        prompt_template = load_intent_prompt()
        prompt = prompt_template.format(
            current_date=current_time.strftime("%Y-%m-%d"),
            current_day_of_week=current_time.strftime("%A"),
            current_time=current_time.strftime("%H:%M:%S"),
            day_week_reference=day_week_reference,
            message=message_text
        )

        # Create messages
        messages = [
            SystemMessage(content="You are a shift coverage message classifier."),
            HumanMessage(content=prompt)
        ]

        # Call LLM
        llm = create_intent_llm()

        # Log LLM request
        llm_logger.info("=" * 80)
        llm_logger.info("COMPONENT: Intent Detector")
        llm_logger.info("MODEL: gpt-4o-mini")
        llm_logger.info("LLM REQUEST")
        llm_logger.info(f"Number of messages: {len(messages)}")
        for i, msg in enumerate(messages):
            msg_type = msg.__class__.__name__
            llm_logger.info(f"  [{i}] {msg_type}:")
            llm_logger.info(msg.content)
        llm_logger.info("-" * 80)

        response = llm.invoke(messages)

        # Log LLM response
        llm_logger.info("LLM RESPONSE")
        llm_logger.info(f"Type: {response.__class__.__name__}")
        content = response.content if hasattr(response, "content") else str(response)
        llm_logger.info(f"Content: {content}")
        llm_logger.info("=" * 80)

        # Parse JSON response

        # Find JSON in response
        json_start = content.find("{")
        json_end = content.rfind("}") + 1

        if json_start != -1 and json_end > json_start:
            json_str = content[json_start:json_end]
            result = json.loads(json_str)

            intent_result: IntentDetectionResult = {
                "is_shift_coverage_message": result.get("is_shift_coverage_message", False),
                "resolved_days": result.get("resolved_days", []),
                "confidence": result.get("confidence", 0)
            }

            logger.info(
                f"✅ Intent detected: shift_coverage={intent_result['is_shift_coverage_message']}, "
                f"days={intent_result['resolved_days']}, confidence={intent_result['confidence']}"
            )

            return intent_result

        else:
            logger.warning("No JSON found in intent detection response")
            return {
                "is_shift_coverage_message": False,
                "resolved_days": [],
                "confidence": 0
            }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from intent detection: {e}")
        return {
            "is_shift_coverage_message": False,
            "resolved_days": [],
            "confidence": 0
        }

    except Exception as e:
        logger.error(f"Error in intent detection: {e}", exc_info=True)
        return {
            "is_shift_coverage_message": False,
            "resolved_days": [],
            "confidence": 0
        }
