# Message Processing Flow - Implementation Specification

## Overview

We are modifying the GroupMe polling/processing flow to incorporate multi-step message processing with a database-backed queue mechanism. This ensures messages are not lost and are processed in order, while supporting squad-based workflows where multiple squad members can contribute to resolving shift coverage requests.

---

## Definitions

### Message Queue Statuses

```
RECEIVED → PENDING → PROCESSING → DONE | FAILED | EXPIRED
```

**State Descriptions:**
- **RECEIVED**: Message fetched from GroupMe API
- **PENDING**: Stored in queue, ready for processing
- **PROCESSING**: Currently being processed by workflow
- **DONE**: Successfully processed and completed
- **FAILED**: Processing error occurred (retryable)
- **EXPIRED**: Older than 24 hours (soft deleted)
- **SKIPPED**: System/bot message (soft deleted, audit trail)

### Workflow Statuses

- **NEW**: Workflow just created
- **WAITING_FOR_INPUT**: Asked clarification question, waiting for response
- **READY**: All parameters validated, ready to execute
- **EXECUTING**: Executing calendar commands
- **COMPLETED**: Workflow finished successfully
- **EXPIRED**: Workflow timed out (inactive too long)

### Key Terminology

- **HumanAdmin**: GroupMe user ID to receive admin notifications via DM when system encounters unresolvable situations
- **Poller Instance**: Single execution of the polling loop
- **Poller Lock**: File-based mechanism to prevent concurrent poller execution
- **Squad-based Workflow**: Workflows scoped to squad number, allowing multiple squad members to contribute

---

## Configuration Requirements

Add these settings to your configuration:

```python
# Admin Notifications
ADMIN_GROUPME_USER_ID = "137549805"  # User ID for admin DMs

# Poller Settings
POLLER_TIMEOUT_MINUTES = 30  # Max time before considering poller stale
POLLER_LOCK_FILE = "data/poller.lock"  # Lock file path

# Message Queue Settings
MESSAGE_EXPIRY_HOURS = 24  # Age at which messages expire
MAX_RETRY_ATTEMPTS = 3  # Max retries before admin notification

# Workflow Settings
WORKFLOW_INTERACTION_LIMIT = 2  # Max interactions before escalating to admin
```

---

## Database Schema Changes

### 1. Message Queue Table (NEW)

```sql
CREATE TABLE message_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id TEXT UNIQUE NOT NULL,  -- GroupMe message ID
    group_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    message_text TEXT NOT NULL,
    timestamp BIGINT NOT NULL,  -- GroupMe timestamp
    status TEXT NOT NULL DEFAULT 'RECEIVED',  -- RECEIVED|PENDING|PROCESSING|DONE|FAILED|EXPIRED|SKIPPED
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_message_queue_status ON message_queue(status) WHERE status IN ('PENDING', 'PROCESSING', 'FAILED');
CREATE INDEX idx_message_queue_created ON message_queue(created_at);
```

### 2. Workflows Table (MODIFY)

```sql
ALTER TABLE workflows ADD COLUMN user_id TEXT;
ALTER TABLE workflows ADD COLUMN squad_id INTEGER;

CREATE INDEX idx_workflows_squad_status ON workflows(squad_id, status)
WHERE status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING');
```

**Note:** `user_id` and `squad_id` are nullable and should be populated when available (from roster lookup).

### 3. Poller State (FILE-BASED)

```python
# data/poller.lock (JSON file)
{
    "poller_instance_id": "uuid",
    "started_at": "2025-12-30T11:00:00",
    "last_heartbeat": "2025-12-30T11:05:00"
}
```

---

## Error Handling

### LLM Call Failures
- **Timeout (>30s):** Retry once, then mark message as FAILED
- **Invalid JSON:** Log error, retry once, then mark FAILED
- **Rate limit:** Wait and retry with exponential backoff

### Queue Insertion Failures
- Log error with full context
- Continue polling (don't block)
- Notify admin if persistent (3+ failures)

### Multiple Active Workflows for Same Squad
- Choose most recent workflow (by created_at DESC)
- Log warning: "Multiple active workflows for squad X, using most recent"

### Ambiguous Workflow Resolution
- **Trigger admin notification when:**
  - After 2 workflow interactions, still ambiguous (missing parameters or unclear intent)
  - Workflow fails to determine if message is related
  - IsRelatedMessage confidence < 50 after 2 attempts

### Poller Lock Conflicts
- If lock file exists and timestamp > 30 minutes old: Override (assume crashed)
- If lock file exists and timestamp < 30 minutes: Exit gracefully (yield to active poller)
- On any uncaught exception: Ensure lock file is deleted in finally block

---

## Non-Message Flow Processing Changes

### 1. LLM Prompts in Separate Files

**All LLM prompts must be extracted to separate files:**
- Location: `ai_prompts/` directory
- Format: Markdown with embedded Python f-string placeholders
- Runtime: Load and format with actual values

**Example:**
```python
# Load prompt
prompt_template = Path("ai_prompts/IsRelatedMessagePrompt.md").read_text()

# Format with runtime values
prompt = prompt_template.format(
    original_message=workflow.original_message,
    follow_up_messages=formatted_history,
    sender=message.sender_name,
    new_message=message.message_text
)
```

### 2. HumanAdmin Actor

**Purpose:** Receive DM notifications when system encounters unresolvable situations

**Trigger Conditions:**
1. After 2 workflow interactions, still cannot determine course of action
2. Message cannot be interpreted (intent confidence < 30)
3. IsRelatedMessage check fails repeatedly
4. Calendar API down/failing
5. Poller running > 30 minutes
6. Message processing fails 3+ times

**Notification Format:**
```
⚠️ ADMIN ALERT

Issue: Workflow ambiguous after 2 interactions
Workflow ID: abc-123
Squad: 42
User: John Smith
Last Message: "Maybe we can cover Saturday"

Action Required: Manual review needed
```

**Implementation:**
```python
def notify_admin(issue_type: str, context: dict):
    """Send DM to HumanAdmin via GroupMe API"""
    message = format_admin_notification(issue_type, context)
    groupme_client.send_direct_message(
        user_id=settings.ADMIN_GROUPME_USER_ID,
        text=message
    )
```

### 3. Poller Lock Mechanism (File-Based)

**File:** `data/poller.lock`

**On Poller Start:**
```python
import json
from datetime import datetime, timedelta
from pathlib import Path

lock_file = Path("data/poller.lock")

# Check if lock exists
if lock_file.exists():
    lock_data = json.loads(lock_file.read_text())
    started_at = datetime.fromisoformat(lock_data["started_at"])

    # Check if stale (>30 minutes old)
    if datetime.now() - started_at > timedelta(minutes=30):
        logger.warning("Stale poller lock detected, overriding")
        notify_admin("poller_timeout", {"started_at": started_at})
    else:
        logger.info("Active poller detected, exiting")
        return  # Yield to active poller

# Create lock file
lock_file.write_text(json.dumps({
    "poller_instance_id": str(uuid.uuid4()),
    "started_at": datetime.now().isoformat(),
    "last_heartbeat": datetime.now().isoformat()
}))

try:
    # ... polling logic ...
finally:
    # Always delete lock file
    if lock_file.exists():
        lock_file.unlink()
```

---

## Message Processing Flow

### 1. POLL GROUPME

- Fetch up to 20 messages from GroupMe API
- Reverse order (oldest first)
- Filter out already-seen messages (track via `last_message_id.txt`)
- **Delete expired messages:** Soft delete (set status=EXPIRED) messages older than 24 hours from `message_queue`
- **Store new messages:** INSERT into `message_queue` table (status=RECEIVED → PENDING)
- **Read pending messages:** SELECT from `message_queue` WHERE status IN ('PENDING', 'FAILED') ORDER BY timestamp ASC
- **FOR EACH message** (serially):

---

### 2. FILTER MESSAGE

- **Update status:** PENDING → PROCESSING
- **IF** system message:
  - Soft delete: UPDATE status='SKIPPED'
  - Continue to next message
- **IF** bot message (sender_type=bot OR sender_id=bot_id):
  - Soft delete: UPDATE status='SKIPPED'
  - Continue to next message
- **IF** user impersonation enabled:
  - Check for `{{@username}}` prefix
  - Resolve user from roster
  - Strip prefix from message
- Convert to `GroupMeMessage` model

---

### 3. AUTHORIZE USER

- Check if sender in roster
- **IF NOT** authorized:
  - UPDATE status='SKIPPED'
  - Log: "Unauthorized user"
  - Continue to next message
- **IF** authorized:
  - Get `sender_squad` and `sender_role` from roster
  - **Populate workflow fields:** `user_id = sender.user_id`, `squad_id = sender.squad`

---

### 4. CHECK FOR ACTIVE WORKFLOW

Query database:
```sql
SELECT * FROM workflows
WHERE squad_id = :sender_squad
  AND status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING')
ORDER BY created_at DESC
LIMIT 1;
```

**Rationale:** Squad-based workflows allow any squad member to contribute. Example:
- User A (Squad 34): "I'm not sure if 34 will have coverage on Saturday"
- User B (Squad 34): "Yes, we will have coverage on Saturday" ← Can respond to same workflow

- **IF** active workflow exists → Go to **5A**
- **IF** no active workflow → Go to **5B**

---

### 5A. ACTIVE WORKFLOW EXISTS

#### **If workflow.status == 'WAITING_FOR_INPUT':**

**Step 5A.1: Determine if message is related to workflow**

1. Build historical message list from workflow
2. Call LLM with `IsRelatedMessagePrompt` (see prompt below)
3. Parse response: `{"related": true/false, "confidence": 0.0-1.0, "reason": "..."}`

**If related:**
- Link message to workflow: `message.workflow_id = workflow.id`
- Resume workflow with new message
- Go to **Step 7** (Execute Workflow)

**If NOT related:**
- Keep existing workflow active
- Treat message as new shift request
- Go to **Step 5B** (Intent Detection for new workflow)

#### **Else (workflow active but NOT waiting):**

1. Run intent detection
2. **IF** message is shift request (confidence ≥ 50):
   - Send rejection: "⏳ Please wait - workflow in progress for Squad X"
   - UPDATE message_queue status='DONE'
   - Continue to next message
3. **ELSE:**
   - UPDATE message_queue status='DONE' (noise, ignore)
   - Continue to next message

---

### 5A.1. IsRelatedMessage Prompt

**File:** `ai_prompts/IsRelatedMessagePrompt.md`

```markdown
You are a lightweight classifier.
Your only task is to decide whether a new chat message belongs to an existing workflow thread.

Do NOT interpret, solve, summarize, or expand the content.
Do NOT infer intent beyond topical continuity.
If the relationship is unclear, return false.

A workflow thread:
* Starts with one original message
* May include clarifications or answers from any squad member or the chatbot

A message is RELATED if it:
* Clarifies, answers, confirms, corrects, or adds detail to the same topic
* Responds to a question asked earlier in the thread
* Uses pronouns or shorthand referring to prior context ("that", "it", "yes", "no")

A message is NOT RELATED if it:
* Introduces a new topic or request
* Switches context, task, or subject
* Is general chatter unrelated to the workflow

---

WORKFLOW THREAD (chronological):

[ORIGINAL MESSAGE]
"{original_message}"

[FOLLOW-UP MESSAGES]
{follow_up_messages}

---

NEW MESSAGE:
* {sender}: "{new_message}"

---

Return ONLY valid JSON in this exact shape:

{{
  "related": true | false,
  "confidence": 0.85,
  "reason": "one short sentence"
}}
```

**Format at runtime (Python f-string):**

```python
# Build follow-up messages
follow_up_messages = "\n".join([
    f"* {msg['sender']}: \"{msg['text']}\""
    for msg in workflow_history
])

# Format prompt
prompt = template.format(
    original_message=workflow.initial_message,
    follow_up_messages=follow_up_messages,
    sender=message.sender_name,
    new_message=message.message_text
)
```

**LLM Configuration:**
- Model: `gpt-4o-mini`
- Temperature: 0.0 (deterministic)
- Max tokens: 100

**Error Handling:**
- **IF** LLM timeout or error: Retry once
- **IF** second failure: Assume NOT related, notify admin
- **IF** confidence < 0.5: Treat as NOT related

---

### 5B. NO ACTIVE WORKFLOW

#### **Phase 1: Intent Detection**

- LLM call (gpt-4o-mini) using existing intent detection prompt
- Determine: `is_shift_coverage_message` + `resolved_days` + `confidence`

**If NOT shift request OR confidence < 50:**
- UPDATE message_queue status='DONE' (noise)
- Continue to next message

**If IS shift request AND confidence ≥ 50:**

#### **Phase 2: Fetch Schedule**
- Convert date to YYYYMMDD format
- Call calendar API: `get_schedule_day(date=YYYYMMDD)`
- **IF** calendar returns error → Set `schedule_state = None`
- **ELSE** → Store `schedule_state`

#### **Phase 3: Start New Workflow**
- Build initial state (workflow_id, sender info, resolved_days, schedule_state, etc.)
- INSERT into workflows table:
  - `status = 'NEW'`
  - `user_id = sender.user_id`
  - `squad_id = sender.squad_id`
- Add user message to state
- Go to **Step 7** (Execute Workflow)

---

### 6. PREPARE WORKFLOW STATE

#### **If Starting New Workflow:**

- Create initial state dictionary
- INSERT workflow in DB (status: NEW, user_id, squad_id)
- Get workflow UUID
- Update state with workflow_id
- Add initial user message

#### **If Resuming Existing Workflow:**

- Load state from DB
- Deserialize state (convert dicts to LangChain messages)
- Clean up previous tool messages
- Add new user message
- Clear clarification_question

---

### 7. EXECUTE WORKFLOW

- Call: `workflow_graph.invoke(state)`
- LangGraph runs through nodes (see Step 8)

---

### 8. LANGGRAPH WORKFLOW NODES

#### **Node: extract_parameters**

- Load system prompt from file: `ai_prompts/ExtractParametersPrompt.md`
- Format with current context (sender, squad, resolved_days, schedule_state)
- LLM call (gpt-4o) with tools
- Parse JSON response
- Extract: `parsed_requests[]`, `warnings`, `missing_parameters`, `reasoning`
- Store in state

#### **Routing: route_after_extraction**

- **IF** `len(parsed_requests) == 0` → Go to `complete_no_action`
- **ELSE IF** `len(missing_parameters) > 0` → Go to `clarify`
- **ELSE** → Go to `validate`

#### **Node: complete_no_action** (no actions needed)

- Store LLM warnings/reasoning
- Set `execution_result: {"status": "no_action_needed"}`
- Set `current_step = "complete_no_action"`
- END

#### **Node: clarify** (missing parameters)

- Identify most important missing parameter (priority: squad, date, shift_start, shift_end)
- Generate clarification question
- Store in: `clarification_question`
- Set `current_step = "request_clarification"`
- **Track interaction count:** Increment `state["interaction_count"]`
- **IF** `interaction_count >= 2` AND still missing params:
  - Notify admin (ambiguous workflow)
- END

#### **Node: validate** (all parameters present)

- Check all required parameters exist (squad, date, shift_start, shift_end)
- Validate formats (YYYYMMDD, HHMM)
- Validate squad number (34, 35, 42, 43, 54)
- Set: `validation_passed` (true/false)
- Store: `validation_warnings[]`

#### **Routing: route_after_validation**

- **IF** `validation_passed` → Go to `execute`
- **ELSE** → END

#### **Node: execute** (validation passed)

- Loop through ALL `parsed_requests[]`
- For each: Build `CalendarCommand` object
- Store all commands in: `execution_result.commands[]`
- Set `execution_result: {"status": "prepared"}`
- Set `current_step = "execute"`
- END

---

### 9. DETERMINE & SAVE STATUS

#### **Determine New Status:**

- **IF** `current_step == "request_clarification"` → Status: `WAITING_FOR_INPUT`
- **ELSE IF** `current_step == "complete_no_action"` → Status: `COMPLETED`
- **ELSE IF** `current_step == "validate" AND validation_passed` → Status: `READY`
- **ELSE IF** `current_step == "execute"`:
  - **IF** `execution_result.status == "prepared"` → Status: `EXECUTING`
  - **ELSE** → Status: `COMPLETED`

#### **Save to Database:**

- Serialize state (convert LangChain messages to dicts)
- UPDATE workflows SET:
  - `status = new_status`
  - `state_data = serialized_state`
  - `updated_at = NOW()`

---

### 10. HANDLE WORKFLOW OUTPUTS

#### **If clarification_question exists:**

- POST to GroupMe: Send clarification question
- Store bot message in DB

#### **If validation_warnings[] not empty:**

- For each warning:
  - POST to GroupMe: Send warning message
  - Store bot message in DB

#### **If execution_result.commands[] exists:**

- For each command:
  - Call calendar API: `calendar_client.send_command(command)`
  - Log success/failure
  - Track counts (succeeded, failed)
- POST to GroupMe: Send summary ("✅ Updated X shift(s)")
- **IF** all succeeded → UPDATE workflow status='COMPLETED'

---

### 11. STORE MESSAGE IN DB

- UPDATE message_queue SET status='DONE', processed_at=NOW()
- INSERT INTO messages (message_id, group_id, user_id, user_name, message_text, timestamp, workflow_id)
- Link message to workflow via workflow_id

---

### 12. UPDATE POLL STATE

- Save `last_message_id` to `data/last_message_id.txt`
- Increment counters (processed_count or ignored_count)
- **IF** more messages in queue → Loop to next message (back to Step 2)
- **ELSE** → End poll, return summary

---

## Key Decision Points Summary

| Condition                              | Action                                           |
|----------------------------------------|--------------------------------------------------|
| System/bot message                     | Soft delete (status=SKIPPED)                     |
| Unauthorized user                      | Soft delete (status=SKIPPED)                     |
| Active workflow + WAITING_FOR_INPUT    | Check if related → Resume if yes, else new WF    |
| Active workflow + NOT waiting          | Reject if shift request, else ignore             |
| No active workflow + NOT shift request | Mark DONE (noise)                                |
| No active workflow + IS shift request  | Start new workflow                               |
| LLM returns 0 actions                  | Send warnings, mark COMPLETED                    |
| LLM returns missing params             | Ask clarification, mark WAITING_FOR_INPUT        |
| LLM returns valid actions              | Execute commands, mark COMPLETED                 |
| 2+ interactions still ambiguous        | Notify admin, continue workflow                  |
| Message queue insertion fails          | Log error, continue (don't block)                |
| Multiple workflows for same squad      | Use most recent, log warning                     |

---

## State Persistence Points

1. **Workflow created** → INSERT workflows (status: NEW, user_id, squad_id)
2. **After workflow execution** → UPDATE workflows (status + state_data)
3. **After sending messages** → INSERT messages (linked to workflow)
4. **Message processing complete** → UPDATE message_queue (status=DONE)
5. **Expired messages** → UPDATE message_queue (status=EXPIRED)
6. **After processing batch** → WRITE last_message_id.txt

---

## Implementation Checklist

- [ ] Create `message_queue` table
- [ ] Add `user_id` and `squad_id` columns to `workflows` table
- [ ] Implement file-based poller lock mechanism
- [ ] Extract all LLM prompts to `ai_prompts/` directory
- [ ] Implement `IsRelatedMessagePrompt` check
- [ ] Update `get_active_workflow()` to query by `squad_id`
- [ ] Implement HumanAdmin notification system
- [ ] Add interaction count tracking to workflows
- [ ] Implement 24-hour message expiry (soft delete)
- [ ] Update all status transitions to use new message queue statuses
- [ ] Add retry logic for failed messages
- [ ] Implement admin escalation after 2 ambiguous interactions
- [ ] Add comprehensive error handling as specified
- [ ] Update configuration with new settings
- [ ] Test squad-based workflow sharing (multiple users, same squad)
