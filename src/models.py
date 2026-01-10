"""Data models for the chatbot."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


# =============================================================================
# Calendar/Schedule Models (from original implementation)
# =============================================================================


class CalendarCommand(BaseModel):
    """Represents a command to send to the calendar service."""

    action: Literal["noCrew", "addShift", "obliterateShift"]
    date: str = Field(pattern=r"^\d{8}$", description="Date in YYYYMMDD format")
    shift_start: str = Field(pattern=r"^\d{4}$", description="Start time in HHMM format")
    shift_end: str = Field(pattern=r"^\d{4}$", description="End time in HHMM format")
    squad: Literal[34, 35, 42, 43, 54]
    preview: bool = False  # Preview mode flag

    def to_query_params(self) -> dict[str, str]:
        """Convert to query parameters for HTTP request."""
        return {
            "action": self.action,
            "date": self.date,
            "shift_start": self.shift_start,
            "shift_end": self.shift_end,
            "squad": str(self.squad),
            "preview": str(self.preview),
        }


class GroupMeMessage(BaseModel):
    """Represents a GroupMe message."""

    sender_name: str
    message_text: str
    timestamp: int  # Unix timestamp
    group_id: str
    message_id: str
    sender_id: str
    preview: bool = False  # Preview mode flag


# =============================================================================
# Conversation/Workflow Models (new for stateful agentic system)
# =============================================================================


class ConversationMessage(BaseModel):
    """Message stored in Supabase conversations table."""

    message_id: str  # GroupMe message ID (primary key)
    group_id: str
    user_id: str
    user_name: str
    message_text: str
    timestamp: int  # Unix timestamp from GroupMe
    workflow_id: str | None = None  # Links to workflow if part of one
    created_at: datetime | None = None  # Set by database

    @classmethod
    def from_groupme_message(
        cls,
        msg: GroupMeMessage,
        workflow_id: str | None = None
    ) -> "ConversationMessage":
        """Create a ConversationMessage from a GroupMeMessage."""
        return cls(
            message_id=msg.message_id,
            group_id=msg.group_id,
            user_id=msg.sender_id,
            user_name=msg.sender_name,
            message_text=msg.message_text,
            timestamp=msg.timestamp,
            workflow_id=workflow_id,
        )


class Workflow(BaseModel):
    """Workflow instance stored in Supabase workflows table."""

    id: str | None = None  # UUID, set by database
    group_id: str
    workflow_type: Literal["shift_coverage"]
    status: Literal["NEW", "WAITING_FOR_INPUT", "READY", "EXECUTING", "COMPLETED", "EXPIRED"]
    state_data: dict = Field(default_factory=dict)  # Serialized LangGraph state
    created_at: datetime | None = None  # Set by database
    updated_at: datetime | None = None  # Set explicitly in code
    expires_at: datetime | None = None  # Set on creation
    metadata: dict = Field(default_factory=dict)  # Additional context
    user_id: str | None = None  # GroupMe user ID who initiated workflow
    squad_id: int | None = None  # Squad number for squad-scoped workflows


class MessageQueue(BaseModel):
    """Message queue entry stored in Supabase message_queue table."""

    id: str | None = None  # UUID, set by database
    message_id: str  # GroupMe message ID (unique)
    group_id: str
    user_id: str
    user_name: str
    message_text: str
    timestamp: int  # GroupMe timestamp
    status: Literal["RECEIVED", "PENDING", "PROCESSING", "DONE", "FAILED", "EXPIRED", "SKIPPED"] = "RECEIVED"
    retry_count: int = 0
    error_message: str | None = None
    created_at: datetime | None = None  # Set by database
    updated_at: datetime | None = None  # Set by database
    processed_at: datetime | None = None


class WorkflowStateData(BaseModel):
    """Typed structure for workflow state_data (what goes in the JSONB column)."""

    # Workflow metadata
    workflow_id: str
    group_id: str

    # User context
    sender_name: str
    sender_squad: int | None = None
    sender_role: str | None = None

    # Conversation (list of message dicts for LLM)
    messages: list[dict] = Field(default_factory=list)

    # Extracted parameters
    squad: int | None = None
    date: str | None = None  # YYYYMMDD
    shift_start: str | None = None  # HHMM
    shift_end: str | None = None  # HHMM
    action: Literal["noCrew", "addShift", "obliterateShift"] | None = None

    # Validation
    validation_warnings: list[str] = Field(default_factory=list)
    validation_passed: bool = True

    # Execution
    execution_result: dict | None = None

    # Control flow
    current_step: str = "extract_parameters"
    missing_parameters: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    interaction_count: int = 0  # Number of clarification interactions


# =============================================================================
# LLM Response Models
# =============================================================================


class LLMAnalysis(BaseModel):
    """Structure for LLM analysis response."""

    is_shift_request: bool
    confidence: int = Field(ge=0, le=100)
    parsed_requests: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    critical_warnings: list[str] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    reasoning: str = ""
