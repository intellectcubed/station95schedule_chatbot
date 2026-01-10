# Implementation Plan — Stateful Agentic Chat Processor

This document provides a detailed implementation plan for building the MVP stateful agentic chat processor as defined in the requirements document.

---

## Implementation Overview

**Deployment Model**: Local HTTP only (no Lambda/AWS deployment for MVP)

**Tech Stack**:
- Python 3.11+
- LangGraph for workflow orchestration
- Supabase (via supabase-py) for persistence
- OpenAI GPT-4 (ChatGPT) for LLM
- GroupMe API for messaging
- Pydantic for data validation
- Custom calendar service API (local HTTP)

---

## Phase 1: Foundation & Infrastructure

### 1.1 Database Schema Design

**Location**: `scripts/supabase_schema.sql`

Two tables:
1. **workflows** - Workflow instances, metadata, and serialized state (includes `state_data` JSONB column)
2. **conversations** - All messages from GroupMe

See schema file for complete DDL.

### 1.2 Configuration Management

**File**: `src/config.py`

- Extend existing config.py pattern from original implementation
- Add Supabase configuration
- Use pydantic-settings with .env file
- Remove Lambda/AWS-specific settings

**Configuration Variables**:
```
# Supabase
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_KEY

# OpenAI
OPENAI_API_KEY

# GroupMe
GROUPME_BOT_ID
GROUPME_API_TOKEN
GROUPME_GROUP_ID

# Calendar Service (local HTTP)
CALENDAR_SERVICE_URL

# Bot Configuration
CONFIDENCE_THRESHOLD=70
LOG_LEVEL=INFO
ROSTER_FILE_PATH=data/roster.json
WORKFLOW_EXPIRATION_HOURS=24
```

### 1.3 System Prompt Externalization

**File**: `ai_prompts/system_prompt.txt`

Extract the system prompt from the original agentic_processor.py to an external file. This allows easy modification without code changes.

The prompt will be loaded at runtime and formatted with context variables:
- Current date/time
- Sender information
- Sender's squad and role

### 1.4 Logging Configuration

**File**: `src/logging_config.py`

Port from original implementation:
- Console + file logging
- Separate error log file
- Logs directory: `logs/`
- Files: `chatbot.log`, `errors.log`

---

## Phase 2: Data Layer

### 2.1 Data Models

**File**: `src/models.py`

Define Pydantic models for:

**Existing models to port**:
- `CalendarCommand`
- `GroupMeMessage`

**New models**:
```python
class ConversationMessage(BaseModel):
    """Message stored in Supabase"""
    id: str  # UUID
    group_id: str
    user_id: str
    user_name: str
    message_text: str
    timestamp: int
    workflow_id: str | None
    created_at: datetime

class Workflow(BaseModel):
    """Workflow instance"""
    id: str  # UUID
    group_id: str
    workflow_type: Literal["shift_coverage"]
    status: Literal["NEW", "WAITING_FOR_INPUT", "READY", "EXECUTING", "COMPLETED", "EXPIRED"]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    metadata: dict  # Additional context

```

Note: Workflow state is stored directly in the `workflows` table as a JSONB column (`state_data`), eliminating the need for a separate table.

### 2.2 Supabase Client

**File**: `src/supabase_client.py`

Wrapper around supabase-py client:
```python
class SupabaseClient:
    def __init__(self):
        # Initialize with credentials from config

    def get_client(self) -> Client:
        # Return authenticated Supabase client
```

### 2.3 ConversationStateManager

**File**: `src/conversation_state_manager.py`

This is the core persistence layer. Responsibilities:

**Message Operations**:
- `store_message(message: ConversationMessage) -> str` - Store a message
- `get_recent_messages(group_id: str, limit: int = 20) -> list[ConversationMessage]` - Get recent messages for context
- `get_workflow_messages(workflow_id: str) -> list[ConversationMessage]` - Get messages associated with a workflow

**Workflow Operations**:
- `create_workflow(group_id: str, workflow_type: str) -> Workflow` - Create new workflow
- `get_active_workflow(group_id: str) -> Workflow | None` - Get active workflow for group
- `update_workflow_status(workflow_id: str, status: str) -> None` - Update workflow status
- `expire_workflow(workflow_id: str) -> None` - Mark workflow as expired

**State Operations**:
- `update_workflow(workflow_id: str, status: str | None, state: dict | None) -> None` - Update workflow status and/or state atomically
- `restore_active_workflows() -> list[Workflow]` - Restore workflows on startup

**Workflow Expiration**:
- `expire_old_workflows() -> int` - Check for and mark expired workflows (returns count)
  - Called on startup and optionally during each poll cycle
  - Simple UPDATE query with WHERE expires_at < NOW()
  - Logs the number of workflows expired

**Implementation Notes**:
- Use Supabase service key for all operations (not anon key)
- Always set `updated_at` explicitly in Python when updating workflows (no DB triggers)
- Add proper error handling and logging for all DB operations
- Implement connection pooling/reuse
- Add retry logic for transient failures

---

## Phase 3: LangGraph Workflow

### 3.1 Workflow State Definition

**File**: `src/workflows/shift_coverage.py`

Define the state that flows through the workflow:

```python
class ShiftWorkflowState(TypedDict):
    # Workflow metadata
    workflow_id: str
    group_id: str

    # User context
    sender_name: str
    sender_squad: int | None
    sender_role: str | None

    # Conversation
    messages: Annotated[list, operator.add]  # LLM conversation history

    # Extracted parameters (None until extracted)
    squad: int | None
    date: str | None  # YYYYMMDD
    shift_start: str | None  # HHMM
    shift_end: str | None  # HHMM
    action: Literal["noCrew", "addShift", "obliterateShift"] | None

    # Validation
    validation_warnings: list[str]
    validation_passed: bool

    # Execution
    execution_result: dict | None

    # Control flow
    current_step: str
    missing_parameters: list[str]
    clarification_question: str | None
```

### 3.2 Workflow Nodes

**Node 1: Intent Detection & Parameter Extraction**
```python
def extract_parameters_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Use LLM to extract all parameters from the message.
    Can extract multiple parameters at once.
    """
    # Load system prompt from file
    # Call LLM with tools to extract: squad, date, shift_start, shift_end, action
    # Update state with extracted parameters
    # Identify missing parameters
```

**Node 2: Request Clarification**
```python
def request_clarification_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Generate clarification question for missing parameter.
    Ask for ONE missing parameter at a time.
    """
    # Identify the most important missing parameter
    # Generate natural language question
    # Send to GroupMe
    # Mark workflow as WAITING_FOR_INPUT
```

**Node 3: Validate Parameters**
```python
def validate_parameters_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Validate that all parameters are present and valid.
    Check schedule constraints.
    """
    # Verify squad is scheduled
    # Check crew counts
    # Validate date/time formats
    # Generate warnings if needed
```

**Node 4: Execute Command**
```python
def execute_command_node(state: ShiftWorkflowState) -> ShiftWorkflowState:
    """
    Execute the calendar command.
    """
    # Build CalendarCommand
    # Send to calendar service
    # Store execution result
    # Mark workflow as COMPLETED
```

### 3.3 Conditional Routing

```python
def route_after_extraction(state: ShiftWorkflowState) -> str:
    """Route based on whether parameters are complete"""
    if state["missing_parameters"]:
        return "request_clarification"
    else:
        return "validate"

def route_after_validation(state: ShiftWorkflowState) -> str:
    """Route based on validation result"""
    if state["validation_passed"]:
        return "execute"
    else:
        return "end"  # Send warnings and end
```

### 3.4 Graph Construction

```python
def create_shift_workflow() -> StateGraph:
    """Build the LangGraph workflow"""
    workflow = StateGraph(ShiftWorkflowState)

    # Add nodes
    workflow.add_node("extract_parameters", extract_parameters_node)
    workflow.add_node("request_clarification", request_clarification_node)
    workflow.add_node("validate", validate_parameters_node)
    workflow.add_node("execute", execute_command_node)

    # Entry point
    workflow.set_entry_point("extract_parameters")

    # Edges
    workflow.add_conditional_edges("extract_parameters", route_after_extraction)
    workflow.add_conditional_edges("validate", route_after_validation)
    workflow.add_edge("execute", END)
    workflow.add_edge("request_clarification", END)  # Pause here

    return workflow.compile()
```

**Important**: The workflow does NOT persist state internally. State is serialized and stored in Supabase via ConversationStateManager.

---

## Phase 4: Orchestration Layer

### 4.1 WorkflowManager

**File**: `src/workflow_manager.py`

Manages workflow execution and lifecycle:

```python
class WorkflowManager:
    def __init__(
        self,
        state_manager: ConversationStateManager,
        calendar_client: CalendarClient,
        groupme_client: GroupMeClient,
    ):
        self.state_manager = state_manager
        self.calendar_client = calendar_client
        self.groupme_client = groupme_client
        self.workflow_graph = create_shift_workflow()

    def start_workflow(
        self,
        group_id: str,
        message: ConversationMessage,
        sender_squad: int | None,
        sender_role: str | None
    ) -> Workflow:
        """Create and start a new workflow"""

    def resume_workflow(
        self,
        workflow: Workflow,
        message: ConversationMessage
    ) -> Workflow:
        """Resume a paused workflow with new input"""

    def execute_step(
        self,
        workflow: Workflow,
        state: dict
    ) -> dict:
        """Execute one step of the workflow"""
        # Invoke LangGraph
        # Serialize and save state
        # Update workflow status
```

### 4.2 ConversationRouter

**File**: `src/conversation_router.py`

Routes messages to appropriate handlers:

```python
class ConversationRouter:
    def __init__(
        self,
        state_manager: ConversationStateManager,
        workflow_manager: WorkflowManager,
        roster: Roster,
    ):
        self.state_manager = state_manager
        self.workflow_manager = workflow_manager
        self.roster = roster

    def route_message(
        self,
        message: ConversationMessage
    ) -> dict:
        """
        Route a message to the appropriate handler.

        Logic:
        1. Check for active workflow in this group
        2. If workflow exists and is WAITING_FOR_INPUT:
           - Resume workflow with this message
        3. Else:
           - Evaluate if this is a new shift request
           - If yes and confidence > threshold:
             - Start new workflow
           - Else:
             - Ignore (return early)
        """
```

### 4.3 AgenticCoordinator

**File**: `src/agentic_coordinator.py`

Main orchestrator - ties everything together:

```python
class AgenticCoordinator:
    def __init__(self):
        # Initialize all components
        self.state_manager = ConversationStateManager()
        self.calendar_client = CalendarClient()
        self.groupme_client = GroupMeClient()
        self.roster = Roster(settings.roster_file_path)

        self.workflow_manager = WorkflowManager(
            self.state_manager,
            self.calendar_client,
            self.groupme_client,
        )

        self.router = ConversationRouter(
            self.state_manager,
            self.workflow_manager,
            self.roster,
        )

        # Cleanup and restore on startup
        self._expire_old_workflows()
        self._restore_workflows()

    def _expire_old_workflows(self):
        """Mark expired workflows as EXPIRED"""
        count = self.state_manager.expire_old_workflows()
        if count > 0:
            logger.info(f"Expired {count} old workflow(s) on startup")

    def _restore_workflows(self):
        """Restore active workflows from DB on startup"""

    def process_message(
        self,
        message: GroupMeMessage
    ) -> dict:
        """
        Main entry point for processing a message.

        Steps:
        1. Store message in DB
        2. Resolve sender to squad/role via Roster
        3. Route to appropriate handler
        4. Return processing result
        """
```

---

## Phase 5: Integration

### 5.1 Update GroupMePoller

**File**: `src/groupme_poller.py`

Port from original implementation with changes:
- Replace MessageProcessor with AgenticCoordinator
- Messages are now stored in Supabase (not just state file)
- Keep the last_message_id tracking for polling

### 5.2 Update poll_messages.py

**File**: `src/poll_messages.py`

Simplify to use new architecture:

```python
def main() -> None:
    # Setup logging
    setup_logging()

    # Validate configuration
    validate_configuration()

    # Initialize coordinator (does all the heavy lifting)
    coordinator = AgenticCoordinator()

    # Initialize and run poller
    poller = GroupMePoller(coordinator)
    result = poller.poll(limit=20)

    # Log and exit
```

### 5.3 Reusable Components from Original

Port these files with minimal changes:
- `src/calendar_client.py` - **Remove Lambda/IAM auth code**, keep local HTTP
- `src/groupme_client.py` - Copy as-is
- `src/logging_config.py` - Copy as-is
- `src/roster.py` - Already in new project, keep as-is
- `src/tools.py` - Already in new project, may need adjustments

---

## Phase 6: Testing & Validation

### 6.1 Manual Testing Scenarios

**Scenario 1: Simple single-message request**
- Message: "Squad 42 can't make it Saturday night"
- Expected: Extract all parameters, validate, execute

**Scenario 2: Multi-turn conversation**
- Message 1: "Can't make it Saturday"
- Bot: "Which squad won't be available?"
- Message 2: "Squad 42"
- Bot: "What time on Saturday?"
- Message 3: "Night shift"
- Expected: Complete workflow after collecting all info

**Scenario 3: Overlapping workflow rejection**
- Message 1: "Squad 42 can't make Saturday night" (starts workflow)
- Bot: Asks clarifying question
- Message 2: "Squad 35 can't make Sunday morning" (different request)
- Expected: Reject second request, wait for first to complete

**Scenario 4: Workflow expiration**
- Start workflow
- Wait 24+ hours
- Try to respond
- Expected: Workflow expired, must start over

### 6.2 Logging Validation

Ensure all key operations are logged:
- Message received and stored
- Workflow created/resumed
- LLM calls and responses
- Parameter extraction
- Validation results
- Calendar API calls
- Errors with full context

---

## File Structure

```
station95schedule_chatbot/
├── ai_prompts/
│   ├── MVP Requirements — Stateful Agentic Chat Process.md
│   ├── Implementation Plan.md (this file)
│   └── system_prompt.txt (extracted from code)
├── data/
│   └── roster.json
├── logs/
│   ├── chatbot.log
│   └── errors.log
├── scripts/
│   ├── poll.sh
│   └── supabase_schema.sql (database schema)
├── src/
│   ├── __init__.py
│   ├── agentic_coordinator.py (main orchestrator)
│   ├── calendar_client.py (ported, no Lambda)
│   ├── config.py (extended with Supabase config)
│   ├── conversation_router.py (new)
│   ├── conversation_state_manager.py (new)
│   ├── groupme_client.py (ported as-is)
│   ├── groupme_poller.py (ported with changes)
│   ├── logging_config.py (ported as-is)
│   ├── models.py (extended with new models)
│   ├── poll_messages.py (simplified)
│   ├── roster.py (already exists)
│   ├── supabase_client.py (new)
│   ├── tools.py (already exists, may need updates)
│   ├── workflow_manager.py (new)
│   └── workflows/
│       ├── __init__.py
│       └── shift_coverage.py (LangGraph workflow)
├── .env (local config, not committed)
├── .env.template (template for .env)
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Implementation Order

**Day 1: Foundation**
1. Create .env.template
2. Create supabase_schema.sql
3. Extract system_prompt.txt
4. Port/create: config.py, logging_config.py, models.py

**Day 2: Data Layer**
5. Create supabase_client.py
6. Create conversation_state_manager.py
7. Test DB operations manually

**Day 3: Workflow**
8. Create workflows/shift_coverage.py
9. Test workflow in isolation with mock data

**Day 4: Orchestration**
10. Create workflow_manager.py
11. Create conversation_router.py
12. Create agentic_coordinator.py

**Day 5: Integration**
13. Port calendar_client.py, groupme_client.py
14. Update groupme_poller.py
15. Update poll_messages.py

**Day 6: Testing**
16. End-to-end manual testing
17. Fix bugs
18. Refine logging

---

## Success Criteria

MVP is complete when:
- ✅ A multi-turn shift request can be completed across multiple poll cycles
- ✅ Bot asks clarifying questions and waits for replies
- ✅ Workflow state persists and restores correctly
- ✅ Overlapping workflows are properly rejected
- ✅ Process can restart cleanly without losing context
- ✅ All messages are stored in Supabase
- ✅ Calendar commands execute successfully
- ✅ Logging provides clear visibility into all operations
