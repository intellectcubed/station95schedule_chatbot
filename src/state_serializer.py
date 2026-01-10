"""State serializer for converting LangGraph state to/from JSON."""

import logging
from typing import Any

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
    BaseMessage,
)

logger = logging.getLogger(__name__)


def serialize_state(state: dict) -> dict:
    """
    Serialize LangGraph state for storage in database.

    Converts LangChain message objects to dictionaries.

    Args:
        state: State dictionary from LangGraph (may contain Message objects)

    Returns:
        Serialized state dictionary (all values JSON-serializable)
    """
    serialized = state.copy()

    # Serialize messages if present
    if "messages" in serialized and serialized["messages"]:
        serialized["messages"] = [
            _serialize_message(msg) for msg in serialized["messages"]
        ]

    return serialized


def deserialize_state(state: dict) -> dict:
    """
    Deserialize state from database for use in LangGraph.

    Converts message dictionaries back to LangChain message objects.

    Args:
        state: Serialized state dictionary from database

    Returns:
        State dictionary with LangChain message objects
    """
    deserialized = state.copy()

    # Deserialize messages if present
    if "messages" in deserialized and deserialized["messages"]:
        deserialized["messages"] = [
            _deserialize_message(msg_dict) for msg_dict in deserialized["messages"]
        ]

    return deserialized


def _serialize_message(msg: BaseMessage) -> dict:
    """
    Serialize a LangChain message to a dictionary.

    Args:
        msg: LangChain message object

    Returns:
        Dictionary representation of the message
    """
    if isinstance(msg, dict):
        # Already serialized
        return msg

    serialized = {
        "type": msg.__class__.__name__,
        "content": msg.content,
        "additional_kwargs": getattr(msg, "additional_kwargs", {}),
    }

    # ToolMessage requires tool_call_id
    if isinstance(msg, ToolMessage):
        serialized["tool_call_id"] = msg.tool_call_id

    # AIMessage may have tool_calls
    if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls"):
        serialized["tool_calls"] = msg.tool_calls

    return serialized


def _deserialize_message(msg_dict: dict) -> BaseMessage:
    """
    Deserialize a message dictionary to a LangChain message object.

    Args:
        msg_dict: Dictionary representation of a message

    Returns:
        LangChain message object
    """
    if isinstance(msg_dict, BaseMessage):
        # Already a message object
        return msg_dict

    msg_type = msg_dict.get("type", "HumanMessage")
    content = msg_dict.get("content", "")
    additional_kwargs = msg_dict.get("additional_kwargs", {})

    # Map type name to class
    message_classes = {
        "HumanMessage": HumanMessage,
        "AIMessage": AIMessage,
        "SystemMessage": SystemMessage,
        "ToolMessage": ToolMessage,
    }

    message_class = message_classes.get(msg_type, HumanMessage)

    # ToolMessage requires tool_call_id
    if msg_type == "ToolMessage":
        tool_call_id = msg_dict.get("tool_call_id", "")
        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            additional_kwargs=additional_kwargs
        )

    # AIMessage may have tool_calls
    if msg_type == "AIMessage":
        tool_calls = msg_dict.get("tool_calls", [])
        return AIMessage(
            content=content,
            additional_kwargs=additional_kwargs,
            tool_calls=tool_calls
        )

    # All other message types
    return message_class(content=content, additional_kwargs=additional_kwargs)
