# Station 95 Schedule Chatbot — Developer Guide

## What This System Does

The Station 95 Collaborative is a group of 5 local EMS squads (34, 35, 42, 43, 54) that share overnight and weekend duty coverage. A shared calendar tracks which squads are on duty for each shift:

- **Weeknight shifts**: Monday–Friday, 1800–0600
- **Weekend shifts**: Saturday and Sunday, split into day (0600–1800) and night (1800–0600)

Each shift has one or two squads on duty (up to 4), and the 5 service territories are divided among whichever squads are covering.

Squad representatives coordinate schedule changes through a **GroupMe group chat** — messages like _"42 can't make it tonight"_ or _"54 is adding a crew for Saturday night."_ This chatbot monitors that GroupMe chat, interprets the scheduling intent, and automatically updates the shared calendar via API calls.

The chat also contains non-scheduling chatter (social messages, questions, etc.) which the chatbot silently ignores. When a message is ambiguous, the chatbot asks clarifying questions in the group chat and waits for a response. If the conversation becomes too complex (too many back-and-forth clarifications), it escalates to a human admin.

---

## High-Level Use Cases

1. **Squad reports no crew** — _"42 doesn't have a crew for tonight"_ → chatbot removes Squad 42 from tonight's shift on the calendar.

2. **Squad adds a crew** — _"54 is adding for Saturday night"_ → chatbot adds Squad 54 to Saturday night's shift.

3. **Ambiguous message requiring clarification** — _"We can't make it"_ → chatbot asks _"Which squad won't be available?"_ and waits for a reply.

4. **Multi-action message** — _"42 is out tonight and tomorrow"_ → chatbot processes both calendar changes in a single workflow.

5. **Noise filtering** — _"Great job tonight everyone!"_ → chatbot ignores this completely.

6. **Schedule conflict detection** — _"42 is out tonight"_ but Squad 42 isn't on tonight's schedule → chatbot reports the discrepancy as a warning rather than blindly modifying the calendar.

---

## Architecture Overview

The system is a **poll-based, stateful agentic chatbot** that runs on a cron schedule (not a long-running server). Each poll cycle:

1. Fetches new messages from GroupMe
2. Queues them for processing
3. Runs each message through an NLP pipeline (LLM-backed)
4. Executes calendar updates as needed
5. Persists all state to Supabase so it can resume across poll cycles

### External Services

| Service | Purpose |
|---------|---------|
| **GroupMe API** | Message source (polling) and message output (bot replies) |
| **OpenAI API** | LLM for intent detection (gpt-4o-mini) and parameter extraction (gpt-4o) |
| **Supabase** | Persistent storage for conversations, workflows, and message queue |
| **Calendar Service** | HTTP API for reading/modifying the shared schedule |

### Key Design Principles

- **`poll_messages.py` is stateless** — all state lives in Supabase
- **LangGraph manages workflow logic, not persistence** — state is serialized externally
- **Two-phase LLM approach** — a cheap/fast model classifies messages, a capable model extracts parameters
- **Squad-scoped workflows** — each squad can have one active workflow at a time
- **Workflows survive restarts** — active workflows are restored from the database on startup

---

## Message Processing Flow

This section traces the lifecycle of a message from GroupMe through the system. Each subsection notes the class and file where the logic lives.

### 1. Polling and Queueing

**`GroupMePoller.poll()`** — `src/groupme_poller.py`

A cron job invokes `python -m src.poll_messages`, which calls `GroupMePoller.poll()`. The poller:

1. **Acquires a file-based lock** (`PollerLock` in `src/poller_lock.py`) to prevent concurrent polling. If another poller is running, this invocation yields immediately. Stale locks (older than 30 minutes) are auto-overridden and trigger an admin notification.

2. **Fetches messages** from the GroupMe API (up to 100 per call), filtering out messages already seen by comparing against a persisted `last_message_id` stored in `data/last_message_id.txt`.

3. **Filters** out system messages, bot messages, and the chatbot's own messages.

4. **Handles impersonation** (testing feature): messages prefixed with `{{@username}}` are treated as if sent by that roster member. This allows a developer to test as any squad rep.

5. **Inserts** each new message into the **message queue** (`MessageQueueManager` in `src/message_queue_manager.py`, backed by a Supabase `message_queue` table) with status `PENDING`.

6. **Processes** all `PENDING` messages sequentially, passing each to `AgenticCoordinator.process_message()`. On success, the queue entry is marked `DONE`; on failure, `FAILED` with a retry count. After 3 failures, an admin is notified.

7. **Expires** old queue entries (>24 hours) and **releases the lock**.

### 2. Coordination

**`AgenticCoordinator.process_message()`** — `src/agentic_coordinator.py`

The coordinator is the single entry point for processing. It:

1. Converts the `GroupMeMessage` into a `ConversationMessage` (the internal model)
2. Delegates to `ConversationRouter.route_message()` for all routing decisions
3. Stores the message in the Supabase `conversations` table (with `workflow_id` if one was assigned)

On startup, the coordinator also expires old workflows and restores active ones from the database.

### 3. Routing

**`ConversationRouter.route_message()`** — `src/conversation_router.py`

This is where the core decision tree lives. For each incoming message:

```
Is sender in the roster?
├─ NO → Ignore (unauthorized user)
└─ YES → Get sender's squad and role from roster
         │
         Does sender's squad have an active workflow?
         ├─ YES → Is this message related to that workflow?
         │        (LLM call: IsRelatedMessageChecker)
         │        ├─ YES, confidence >= 50 → Resume workflow
         │        │   └─ Has interaction count exceeded limit?
         │        │       ├─ YES → Escalate to admin, expire workflow
         │        │       └─ NO  → WorkflowManager.resume_workflow()
         │        └─ NO → Fall through to "new message" path below
         │
         └─ NO active squad workflow →
              Is there any active group-level workflow?
              ├─ YES, WAITING_FOR_INPUT → Resume it
              ├─ YES, other status → Is this a new shift request?
              │   ├─ YES → Reject ("please wait, workflow in progress")
              │   └─ NO  → Ignore
              │
              └─ NO active workflow →
                   *** INTENT DETECTION (Phase 1) ***
                   Is this a shift coverage message?
                   ├─ YES, confidence >= 50 →
                   │     Fetch schedule from calendar service
                   │     WorkflowManager.start_workflow()
                   └─ NO → Ignore (noise)
```

### 4. Intent Detection (Phase 1 — Is This a Scheduling Message?)

**`detect_intent()`** — `src/intent_detector.py`

This is the "noise filter." It uses a **fast, cheap LLM call (gpt-4o-mini)** with a carefully crafted prompt (`ai_prompts/IntentDetectionPrompt.md`) to determine two things:

1. **Is this a shift coverage message?** (boolean + confidence score 0–100)
2. **What date(s) is it about?** (resolved to exact `YYYY-MM-DD` values)

The date resolution works as a **hybrid of code and LLM**:

- **Code** computes a 7-day lookup table anchored to the current date:
  ```
  Today: Saturday (2026-01-03)
  Tomorrow: Sunday (2026-01-04)
  Monday: 2026-01-05
  Tuesday: 2026-01-06
  ...
  ```
- This table is injected into the prompt, so the **LLM's only job is to match** natural language ("tonight", "next Tuesday", "this weekend") to entries in the table.
- The LLM never invents dates — it picks from a code-generated list.

The function returns an `IntentDetectionResult`:
```python
{
    "is_shift_coverage_message": True,
    "resolved_days": ["2026-01-03"],
    "confidence": 92
}
```

If `confidence >= 50` and `is_shift_coverage_message` is true, the message proceeds to workflow creation.

### 5. Schedule Fetching

**`ConversationRouter`** — `src/conversation_router.py` (lines ~300–323)

Before starting a workflow, the router fetches the current schedule for the resolved date:

```python
resolved_day = intent["resolved_days"][0]       # "2026-01-03"
date_yyyymmdd = resolved_day.replace("-", "")    # "20260103"
schedule_state = self.calendar_client.get_schedule(
    start_date=date_yyyymmdd, end_date=date_yyyymmdd
)
```

This schedule data is passed into the workflow so the LLM has full context of who is currently on duty.

### 6. Workflow Execution (Phase 2 — Parameter Extraction)

**`WorkflowManager.start_workflow()`** → LangGraph graph — `src/workflow_manager.py` and `src/workflows/shift_coverage.py`

The workflow manager creates a `Workflow` record in Supabase, then invokes the LangGraph state graph. The graph has 5 nodes:

```
                    ┌─────────────────────┐
                    │ extract_parameters  │  ← LLM call (gpt-4o)
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌───────────┐  ┌──────────────────┐
     │  clarify   │  │ validate  │  │ complete_no_action│
     │  (ask Q)   │  │           │  │  (send warning)   │
     └─────┬──────┘  └─────┬─────┘  └────────┬─────────┘
           │               │                  │
           ▼          ┌────┴────┐             ▼
          END         ▼         ▼            END
                 ┌─────────┐   END
                 │ execute  │
                 │(prepare  │
                 │ commands)│
                 └────┬─────┘
                      ▼
                     END
```

**Node details:**

| Node | File:Line | What It Does |
|------|-----------|-------------|
| `extract_parameters_node` | `shift_coverage.py:178` | Calls gpt-4o with the message, schedule CSV, and resolved dates. The system prompt (`ai_prompts/system_prompt.md`) instructs the LLM to return structured JSON with `parsed_requests` (list of actions), `missing_parameters`, and `warnings`. |
| `request_clarification_node` | `shift_coverage.py:390` | Picks the highest-priority missing parameter and generates a question (e.g., _"Which squad won't be available?"_). Sets `clarification_question` in state. |
| `validate_parameters_node` | `shift_coverage.py:441` | Pure code validation: checks squad is in [34,35,42,43,54], date is YYYYMMDD, times are HHMM. |
| `execute_command_node` | `shift_coverage.py:498` | Builds `CalendarCommand` objects from `parsed_requests`. Does not execute — just prepares them. |
| `complete_no_action_node` | `shift_coverage.py:566` | Handles cases where no calendar change is needed (e.g., squad isn't on the schedule). Sends the LLM's warnings/reasoning to the chat. |

**Routing logic between nodes:**
- After extraction: 0 actions → `complete_no_action` | missing params → `clarify` | otherwise → `validate`
- After validation: passed → `execute` | failed → `END`

### 7. Handling Workflow Outputs

**`WorkflowManager._handle_workflow_outputs()`** — `src/workflow_manager.py:301`

After the LangGraph graph completes a step, the workflow manager inspects the resulting state and:

- **If `clarification_question` is set**: sends it to GroupMe, marks workflow `WAITING_FOR_INPUT`
- **If `validation_warnings` exist**: sends each as a warning to GroupMe
- **If `execution_result.status == "prepared"`**: executes each `CalendarCommand` via `CalendarClient.send_command_with_retry()` (up to 3 retries with backoff), sends a confirmation message, marks workflow `COMPLETED`

### 8. Resuming a Paused Workflow

**`WorkflowManager.resume_workflow()`** — `src/workflow_manager.py:139`

When a new message arrives and the router determines it's a response to a pending clarification:

1. The original message and the clarification response are **reconstructed** into a single combined message (e.g., _"42 doesn't have a crew tonight\n\nThe squad is 42"_)
2. The LangGraph graph is re-invoked from the `extract_parameters` node with the enriched context
3. The workflow proceeds as normal (validate → execute or clarify again)

The `is_message_related_to_workflow()` function (`src/is_related_message_checker.py`) uses gpt-4o-mini with conversation history to determine if a new message is a response to the chatbot's question.

---

## Data Models

**`src/models.py`**

| Model | Purpose |
|-------|---------|
| `GroupMeMessage` | Raw message from GroupMe API |
| `ConversationMessage` | Message stored in Supabase `conversations` table |
| `Workflow` | Workflow record in Supabase `workflows` table |
| `WorkflowStateData` | Typed structure for the workflow's `state_data` JSONB column |
| `MessageQueue` | Entry in Supabase `message_queue` table |
| `CalendarCommand` | Command to send to the calendar service |
| `LLMAnalysis` | Structured LLM response |

### Calendar Actions

| Action | Meaning |
|--------|---------|
| `noCrew` | Squad cannot provide coverage — remove from schedule |
| `addShift` | Squad is committing coverage — add to schedule |
| `obliterateShift` | Remove shift entirely (rare) |

### Workflow Statuses

```
NEW → WAITING_FOR_INPUT → READY → EXECUTING → COMPLETED
                │                                  ↑
                └──────────────────────────────────┘
                        (or → EXPIRED at any point)
```

---

## Configuration

**`src/config.py`** — Pydantic `Settings` class loading from `.env`

### Required Environment Variables

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (bypasses RLS) |
| `OPENAI_API_KEY` | OpenAI API key |
| `GROUPME_API_TOKEN` | GroupMe API token for reading messages |
| `GROUPME_GROUP_ID` | GroupMe group to monitor |
| `GROUPME_BOT_ID` | GroupMe bot ID for sending messages |
| `CALENDAR_SERVICE_URL` | Base URL of the calendar HTTP service |

### Key Tuning Parameters

| Variable | Default | Purpose |
|----------|---------|---------|
| `CONFIDENCE_THRESHOLD` | 70 | Minimum confidence for intent detection |
| `WORKFLOW_EXPIRATION_HOURS` | 24 | Time before a workflow auto-expires |
| `WORKFLOW_INTERACTION_LIMIT` | 2 | Max clarification rounds before admin escalation |
| `POLLER_TIMEOUT_MINUTES` | 30 | Stale lock detection threshold |
| `MAX_RETRY_ATTEMPTS` | 3 | Message processing retries before admin notification |
| `ENABLE_USER_IMPERSONATION` | true | Testing feature: `{{@name}}` prefix |
| `ENABLE_GROUPME_POSTING` | true | Set false for dry-run (log only) |

---

## LLM Prompts

All prompts live in `ai_prompts/` and are loaded from disk at runtime.

| File | Used By | Model | Purpose |
|------|---------|-------|---------|
| `IntentDetectionPrompt.md` | `intent_detector.py` | gpt-4o-mini | Classify message as shift-related or noise; resolve dates |
| `system_prompt.md` | `shift_coverage.py` | gpt-4o | Extract structured parameters from message + schedule context |
| `IsRelatedMessagePrompt.md` | `is_related_message_checker.py` | gpt-4o-mini | Determine if a new message continues an existing conversation |

---

## Frameworks and Libraries

| Library | Version | Role |
|---------|---------|------|
| **LangChain** | 0.3.13 | LLM abstraction layer (ChatOpenAI, message types) |
| **LangGraph** | 0.2.60 | Workflow state graph framework (nodes, edges, conditional routing). [Docs](https://langchain-ai.github.io/langgraph/) |
| **langchain-openai** | 0.2.14 | OpenAI-specific LangChain integration |
| **Supabase** | 2.10.0 | Python client for Supabase (Postgres + REST API) |
| **Pydantic** | 2.10.4 | Data validation and settings management |
| **Requests** | 2.32.3 | HTTP client for GroupMe and calendar APIs |

---

## Deployment

The system runs as a **cron-scheduled Docker container**:

- **Dockerfile**: Python 3.11 slim image with cron installed
- **Entrypoint**: Starts cron in the foreground
- **Volumes**: `data/` (state files), `logs/` (log files)
- **Invocation**: Each cron tick runs `python -m src.poll_messages`

For local development:
```bash
# Single poll cycle
python -m src.poll_messages

# Continuous polling (every N seconds)
./scripts/poller_repl.sh 30
```

---

## Logging

**`src/logging_config.py`**

| Logger | Output File | Content |
|--------|------------|---------|
| Root | `chatbot.log` | All application logs |
| `llm` | `llm.log` | Full LLM request/response payloads |
| `groupme` | `groupme.log` | All messages received from and sent to GroupMe |
| `calendar` | `calendar.log` | All calendar service requests and responses |
| Errors | `errors.log` | ERROR-level entries only |

---

## Error Handling and Resilience

| Mechanism | Component | Behavior |
|-----------|-----------|----------|
| Concurrent poll prevention | `PollerLock` | File-based lock; stale lock auto-override + admin notification |
| Message retry | `MessageQueueManager` | Failed messages retried up to 3 times; admin notified on exhaustion |
| Workflow expiration | `ConversationStateManager` | Workflows older than 24 hours auto-expire on next startup |
| Escalation | `ConversationRouter` | After 2 clarification rounds, escalates to admin via DM and expires the workflow |
| Calendar retry | `WorkflowManager` | Calendar commands retried up to 3 times with exponential backoff |
| Dry-run mode | `GroupMeClient` | `ENABLE_GROUPME_POSTING=false` logs messages without sending |
| Admin DMs | `admin_notifier.py` | Sends direct messages to a configured admin GroupMe user |

---

## Excalidraw Diagram Description

Create a diagram with the following elements. Suggested layout: top-to-bottom flow with external services on the right side.

### Boxes (Classes/Components)

| Box | Label | Color Suggestion |
|-----|-------|-----------------|
| 1 | **GroupMe API** | Gray (external) |
| 2 | **poll_messages.py** | Light blue (entry point) |
| 3 | **GroupMePoller** | Light blue |
| 4 | **PollerLock** | Light gray (utility) |
| 5 | **MessageQueueManager** | Light gray (utility) |
| 6 | **AgenticCoordinator** | Orange (core) |
| 7 | **ConversationRouter** | Orange (core) |
| 8 | **Roster** | Light green (config/data) |
| 9 | **IntentDetector** | Yellow (LLM) |
| 10 | **IsRelatedMessageChecker** | Yellow (LLM) |
| 11 | **WorkflowManager** | Orange (core) |
| 12 | **LangGraph: Shift Coverage Workflow** | Yellow (LLM). Inside this box, show the 5 nodes as smaller boxes: `extract_parameters` → `clarify` / `validate` / `complete_no_action` → `execute` |
| 13 | **ConversationStateManager** | Purple (persistence) |
| 14 | **GroupMeClient** | Light blue |
| 15 | **CalendarClient** | Light blue |
| 16 | **Supabase** | Gray (external) |
| 17 | **Calendar Service** | Gray (external) |
| 18 | **OpenAI API** | Gray (external) |
| 19 | **AdminNotifier** | Light gray (utility) |

### Arrows (Collaborations)

```
GroupMe API  ──fetches messages──▶  GroupMePoller
poll_messages.py  ──creates──▶  AgenticCoordinator
poll_messages.py  ──creates──▶  GroupMePoller
GroupMePoller  ──acquires/releases──▶  PollerLock
GroupMePoller  ──queues messages──▶  MessageQueueManager
GroupMePoller  ──processes messages──▶  AgenticCoordinator
AgenticCoordinator  ──routes──▶  ConversationRouter
AgenticCoordinator  ──stores messages──▶  ConversationStateManager
ConversationRouter  ──checks authorization──▶  Roster
ConversationRouter  ──detects intent──▶  IntentDetector
ConversationRouter  ──checks relatedness──▶  IsRelatedMessageChecker
ConversationRouter  ──fetches schedule──▶  CalendarClient
ConversationRouter  ──starts/resumes──▶  WorkflowManager
ConversationRouter  ──checks active workflows──▶  ConversationStateManager
ConversationRouter  ──sends rejection/escalation──▶  GroupMeClient
ConversationRouter  ──escalates──▶  AdminNotifier
WorkflowManager  ──invokes──▶  LangGraph: Shift Coverage Workflow
WorkflowManager  ──persists state──▶  ConversationStateManager
WorkflowManager  ──sends messages──▶  GroupMeClient
WorkflowManager  ──executes commands──▶  CalendarClient
IntentDetector  ──calls──▶  OpenAI API  (gpt-4o-mini)
IsRelatedMessageChecker  ──calls──▶  OpenAI API  (gpt-4o-mini)
LangGraph: Shift Coverage Workflow  ──calls──▶  OpenAI API  (gpt-4o)
ConversationStateManager  ──reads/writes──▶  Supabase
MessageQueueManager  ──reads/writes──▶  Supabase
CalendarClient  ──HTTP──▶  Calendar Service
GroupMeClient  ──posts messages──▶  GroupMe API
AdminNotifier  ──sends DM──▶  GroupMe API
```

### Layout Suggestion

```
              ┌──────────────┐
              │  GroupMe API  │ (external, top-right)
              └──────┬───────┘
                     │ fetches
              ┌──────▼───────┐
              │ GroupMePoller │──────▶ PollerLock
              └──────┬───────┘──────▶ MessageQueueManager ──▶ Supabase
                     │ processes
          ┌──────────▼────────────┐
          │  AgenticCoordinator   │
          └──────────┬────────────┘
                     │ routes
          ┌──────────▼────────────┐
          │  ConversationRouter   │──▶ Roster
          │                       │──▶ IntentDetector ──────▶ OpenAI (mini)
          │                       │──▶ IsRelatedChecker ───▶ OpenAI (mini)
          └──────────┬────────────┘
                     │ starts/resumes
          ┌──────────▼────────────┐
          │   WorkflowManager     │──▶ GroupMeClient ──▶ GroupMe API
          │                       │──▶ CalendarClient ─▶ Calendar Service
          └──────────┬────────────┘
                     │ invokes
     ┌───────────────▼─────────────────┐
     │  LangGraph: Shift Coverage      │──▶ OpenAI (gpt-4o)
     │  ┌────────┐ ┌────────┐ ┌─────┐ │
     │  │extract │→│validate│→│exec │ │
     │  └───┬────┘ └────────┘ └─────┘ │
     │      ├──→┌────────┐             │
     │      │   │clarify │             │
     │      │   └────────┘             │
     │      └──→┌──────────┐           │
     │          │no_action │           │
     │          └──────────┘           │
     └─────────────────────────────────┘
                     │
          ┌──────────▼────────────┐
          │ConversationStateManager│──▶ Supabase
          └───────────────────────┘
```

---

## File Reference

| File | Primary Class/Function | Purpose |
|------|----------------------|---------|
| `src/poll_messages.py` | `main()` | CLI entry point — validates config, runs one poll cycle |
| `src/agentic_coordinator.py` | `AgenticCoordinator` | Top-level orchestrator — initializes components, processes messages |
| `src/conversation_router.py` | `ConversationRouter` | Decision tree — routes messages to workflows or ignores them |
| `src/intent_detector.py` | `detect_intent()` | Phase 1 LLM — classifies messages and resolves dates |
| `src/is_related_message_checker.py` | `is_message_related_to_workflow()` | LLM check — is a new message a reply to a pending question? |
| `src/workflow_manager.py` | `WorkflowManager` | Starts/resumes workflows, handles outputs, executes commands |
| `src/workflows/shift_coverage.py` | `create_shift_workflow()` | LangGraph state graph with 5 nodes for shift coverage |
| `src/conversation_state_manager.py` | `ConversationStateManager` | Supabase CRUD for conversations and workflows |
| `src/message_queue_manager.py` | `MessageQueueManager` | Supabase-backed message queue with retry logic |
| `src/groupme_poller.py` | `GroupMePoller` | Polls GroupMe API, queues messages, drives processing |
| `src/groupme_client.py` | `GroupMeClient` | Sends messages to GroupMe (with dry-run support) |
| `src/calendar_client.py` | `CalendarClient` | HTTP client for schedule reads and command execution |
| `src/roster.py` | `Roster` | Loads squad members from JSON, provides authorization lookups |
| `src/models.py` | (multiple) | Pydantic data models for all entities |
| `src/config.py` | `Settings` | Environment-based configuration via Pydantic |
| `src/state_serializer.py` | `serialize_state()` / `deserialize_state()` | Converts LangChain messages to/from JSON for Supabase storage |
| `src/tools.py` | `parse_time_reference` | LangChain tool for edge-case time parsing |
| `src/poller_lock.py` | `PollerLock` | File-based lock preventing concurrent poll cycles |
| `src/admin_notifier.py` | `notify_admin()` | Sends admin DMs for escalations and failures |
| `src/logging_config.py` | `setup_logging()` | Configures file and console loggers |
| `src/supabase_client.py` | `get_supabase()` | Singleton Supabase client |
