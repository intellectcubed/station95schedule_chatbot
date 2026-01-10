# MVP Requirements — Stateful Agentic Chat Processor (with LangGraph)

This section defines the **minimum viable product (MVP) requirements** for the new stateful agentic chat processor. These requirements are intentionally constrained to validate the architecture, persistence model, and multi-turn conversational workflows before expanding scope.

---

## 1. MVP Scope

### In Scope
- Stateful, multi-turn conversational workflows
- Persistent conversation context and workflow state
- LangGraph-managed workflows with pause/resume semantics
- Single active workflow per group
- One workflow type: **shift unavailability**
- ChatGPT as the sole LLM
- Supabase-backed persistence
- Group chat interaction (ask clarifying questions, receive replies)

### Explicitly Out of Scope
- Multiple concurrent workflows per group
- Workflow recovery after expiration
- Conflict resolution between workflows
- Advanced permission or role enforcement
- Multiple LLM providers or models
- Non–shift-related workflows
- Visual workflow inspection tools

---

## 2. High-Level Architecture (MVP)

poll_messages.py
↓
AgenticCoordinator
├── ConversationRouter
├── WorkflowManager (LangGraph-backed)
├── LLMClient (ChatGPT)
├── ToolExecutor
└── ConversationStateManager (Supabase implementation)


**Design Principles:**
- `poll_messages.py` remains stateless
- All orchestration occurs in `AgenticCoordinator`
- LangGraph manages workflow logic, not persistence
- Persistence is external and durable

---

## 3. Conversation & Workflow Constraints (MVP)

### 3.1 Workflow Concurrency
- **Only one active workflow per group**
- While a workflow is in `WAITING_FOR_INPUT`:
  - New shift-related requests are rejected with a user-facing message
  - Unrelated messages are ignored

### 3.2 Workflow Lifecycle States
- `NEW`
- `WAITING_FOR_INPUT`
- `READY`
- `EXECUTING`
- `COMPLETED`
- `EXPIRED`

---

## 4. Conversation State Management (MVP)

### Requirements
- Persist conversation messages and workflow state in Supabase
- Restore active workflows on process restart
- Maintain bounded message history (e.g., last 20 messages per group)
- Associate messages with workflows when applicable

### Responsibilities
- `ConversationStateManager` is the system of record
- LangGraph state is serialized and stored externally
- LLM context is reconstructed from persisted messages

---

## 5. LangGraph Usage (MVP)

### Role of LangGraph
- Model the **shift unavailability workflow** as a state graph
- Support pausing at clarification steps
- Resume execution when new input arrives
- Produce deterministic next-step outputs

### Constraints
- LangGraph must:
  - Accept serialized state
  - Return updated state after each step
- LangGraph must NOT:
  - Persist state internally
  - Call external tools directly (delegated to ToolExecutor)

---

## 6. MVP Workflow Definition

### Supported Workflow: Shift Unavailability

#### Required Inputs
- Squad
- Date
- Time range

#### Workflow Behavior
1. Detect shift-related intent
2. Resolve user → squad
3. Validate squad schedule
4. If information is missing:
   - Ask exactly one clarifying question at a time
   - Transition to `WAITING_FOR_INPUT`
5. When all inputs are present:
   - Transition to `READY`
   - Execute scheduling update
   - Transition to `COMPLETED`

---

## 7. Conversation Routing Rules (MVP)

For each incoming message:

1. Check for an active workflow for the group
2. If workflow is `WAITING_FOR_INPUT`:
   - Route message to workflow
3. Else:
   - Evaluate message as a new shift request
4. Ambiguous messages:
   - Are treated as non-actionable
   - Do not start new workflows

---

## 8. Workflow Expiration (MVP)

### Rules
- Workflows expire after a fixed timeout (e.g., 24 hours)
- On expiration:
  - Mark workflow as `EXPIRED`
  - Do not execute any pending actions
  - Allow new workflows to be created

### User Experience
- No automatic recovery
- User must restate request to restart

---

## 9. LLM Configuration (MVP)

- Provider: ChatGPT
- Model: Configurable (single model only)
- System prompt:
  - Loaded from external file
  - Static for MVP
- LLM responsibilities:
  - Intent detection
  - Parameter extraction
  - Next-step suggestion

---

## 10. Configuration & Secrets (MVP)

- All secrets stored in `.env`
- `.env` excluded from source control
- Centralized configuration loader required

---

## 11. MVP Success Criteria

The MVP is considered successful when it can:

- Sustain a multi-turn scheduling conversation across poll cycles
- Ask clarifying questions and wait for replies
- Persist and restore workflow state reliably
- Execute a shift unavailability update only when fully specified
- Prevent overlapping workflows in the same group
- Recover cleanly from restarts without losing context
