"""Admin notification system for sending alerts via GroupMe DM."""

import logging
import uuid
from datetime import datetime
from typing import Any

import requests

from .config import settings

logger = logging.getLogger(__name__)


def notify_admin(notification_type: str, context: dict[str, Any]) -> None:
    """
    Send a notification to the admin via GroupMe Direct Message.

    Args:
        notification_type: Type of notification (e.g., "poller_timeout", "workflow_escalation")
        context: Additional context data for the notification

    Note:
        This function logs errors but does not raise exceptions to avoid
        disrupting the main application flow.
    """
    try:
        message = _format_notification(notification_type, context)
        _send_dm_to_admin(message)
        logger.info(f"Admin notification sent: {notification_type}")
    except Exception as e:
        logger.error(f"Failed to send admin notification ({notification_type}): {e}")


def _format_notification(notification_type: str, context: dict[str, Any]) -> str:
    """
    Format notification message based on type and context.

    Args:
        notification_type: Type of notification
        context: Context data

    Returns:
        Formatted message string
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if notification_type == "poller_timeout":
        started_at = context.get("started_at", "unknown")
        age_seconds = context.get("age_seconds", 0)
        instance_id = context.get("instance_id", "unknown")

        return (
            f"🚨 POLLER TIMEOUT DETECTED\n"
            f"Time: {timestamp}\n"
            f"Instance ID: {instance_id}\n"
            f"Started at: {started_at}\n"
            f"Age: {age_seconds:.0f} seconds\n"
            f"Action: Stale lock overridden"
        )

    elif notification_type == "workflow_escalation":
        workflow_id = context.get("workflow_id", "unknown")
        user_name = context.get("user_name", "unknown")
        interaction_count = context.get("interaction_count", 0)
        squad = context.get("squad", "unknown")

        return (
            f"⚠️ WORKFLOW ESCALATION\n"
            f"Time: {timestamp}\n"
            f"User: {user_name}\n"
            f"Squad: {squad}\n"
            f"Workflow ID: {workflow_id}\n"
            f"Interactions: {interaction_count}\n"
            f"Reason: Too many ambiguous exchanges, requires human assistance"
        )

    elif notification_type == "message_retry_exceeded":
        message_id = context.get("message_id", "unknown")
        retry_count = context.get("retry_count", 0)
        error_message = context.get("error_message", "unknown")

        return (
            f"⚠️ MESSAGE RETRY LIMIT EXCEEDED\n"
            f"Time: {timestamp}\n"
            f"Message ID: {message_id}\n"
            f"Retry count: {retry_count}\n"
            f"Error: {error_message}"
        )

    elif notification_type == "workflow_execution_failed":
        workflow_id = context.get("workflow_id", "unknown")
        error_message = context.get("error_message", "unknown")
        squad = context.get("squad", "unknown")

        return (
            f"🚨 WORKFLOW EXECUTION FAILED\n"
            f"Time: {timestamp}\n"
            f"Workflow ID: {workflow_id}\n"
            f"Squad: {squad}\n"
            f"Error: {error_message}"
        )

    else:
        # Generic notification format
        context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
        return (
            f"ℹ️ ADMIN NOTIFICATION\n"
            f"Time: {timestamp}\n"
            f"Type: {notification_type}\n"
            f"{context_str}"
        )


def _send_dm_to_admin(message: str) -> None:
    """
    Send a Direct Message to the admin user via GroupMe API.

    Args:
        message: Message text to send

    Raises:
        requests.RequestException: If the API call fails
    """
    url = "https://api.groupme.com/v3/direct_messages"

    headers = {
        "Content-Type": "application/json",
        "X-Access-Token": settings.groupme_api_token,
    }

    payload = {
        "direct_message": {
            "source_guid": str(uuid.uuid4()),
            "recipient_id": settings.admin_groupme_user_id,
            "text": message,
        }
    }

    logger.debug(f"Sending DM to admin (user_id: {settings.admin_groupme_user_id})")

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=10,
    )

    response.raise_for_status()
    logger.debug(f"Admin DM sent successfully: {response.status_code}")
