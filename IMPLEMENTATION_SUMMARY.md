# Implementation Summary: Enhanced Message Processing System

## Overview
Successfully implemented squad-based workflow routing with message queue, poller locking, IsRelatedMessage checking, and admin escalation capabilities.

## Files Created

### 1. Database Migrations
- **`scripts/migrations/001_create_message_queue.sql`**
  - Creates `message_queue` table for robust message processing
  - Status tracking: RECEIVED → PENDING → PROCESSING → DONE|FAILED|EXPIRED|SKIPPED
  - Retry count tracking
  - Indexes for performance

- **`scripts/migrations/002_add_user_squad_to_workflows.sql`**
  - Adds `user_id` and `squad_id` columns to `workflows` table
  - Creates index for squad-based queries
  - Enables squad-scoped workflows (multiple squad members can contribute)

### 2. Core Infrastructure
- **`src/message_queue_manager.py`**
  - Complete CRUD operations for message queue
  - Status updates with retry counting
  - Message expiration (soft delete)
  - Handles PENDING/FAILED message retrieval

- **`src/poller_lock.py`**
  - File-based locking mechanism (data/poller.lock)
  - Stale lock detection (>30 minutes)
  - Automatic cleanup via context manager
  - Admin notification on timeout

- **`src/admin_notifier.py`**
  - GroupMe Direct Message notifications to admin
  - Formatted notifications for different event types:
    - `poller_timeout`: Stale poller detected
    - `workflow_escalation`: Too many clarification interactions
    - `message_retry_exceeded`: Message failed after max retries
    - `workflow_execution_failed`: Workflow execution error
  - Graceful error handling (doesn't crash main flow)

- **`src/is_related_message_checker.py`**
  - LLM-powered check to determine if message relates to active workflow
  - Uses gpt-4o-mini for fast, cost-effective classification
  - Returns (is_related, confidence, reasoning)
  - Enables squad members to collaborate on workflows

### 3. LLM Prompts (Externalized)
- **`ai_prompts/IntentDetectionPrompt.md`**
  - Extracted from `intent_detector.py`
  - Python f-string template format
  - Comprehensive examples and rules

- **`ai_prompts/IsRelatedMessagePrompt.md`**
  - New prompt for conversation continuity analysis
  - Handles squad member contributions
  - Time-based relevance decay

- **`ai_prompts/system_prompt.txt`**
  - Already existed (workflow orchestration)

## Files Modified

### 1. Configuration & Models
- **`src/config.py`**
  - Added admin notification settings
  - Added poller lock settings
  - Added message queue settings
  - Added workflow interaction limit

- **`src/models.py`**
  - Added `MessageQueue` model
  - Added `user_id` and `squad_id` to `Workflow` model
  - Added `interaction_count` to `WorkflowStateData`

### 2. State Management
- **`src/conversation_state_manager.py`**
  - Added `get_active_workflows_for_squad()` method
  - Updated `create_workflow()` to accept `user_id` and `squad_id`
  - Supports squad-based workflow querying

### 3. Routing & Workflow
- **`src/conversation_router.py`**
  - **MAJOR REFACTOR**: Squad-based routing logic
  - Checks for active workflows by sender's squad first
  - Uses IsRelatedMessage to determine workflow continuation
  - Tracks interaction_count on each clarification
  - Escalates to admin after `workflow_interaction_limit` (default: 2)
  - Marks escalated workflows as EXPIRED (soft delete)

- **`src/workflow_manager.py`**
  - Updated `start_workflow()` to pass `user_id` and `squad_id`
  - Initializes `interaction_count` to 0
  - Passes parameters through to state manager

### 4. Intent Detection
- **`src/intent_detector.py`**
  - Loads prompt from `ai_prompts/IntentDetectionPrompt.md`
  - Uses `load_intent_prompt()` function
  - Cleaner separation of concerns

### 5. Poller
- **`src/groupme_poller.py`**
  - **MAJOR REFACTOR**: Message queue pattern
  - Uses `PollerLock` to prevent concurrent polling
  - Inserts fetched messages into queue (status: PENDING)
  - Processes all PENDING messages from queue
  - Updates status: PENDING → PROCESSING → DONE|FAILED
  - Retry logic with admin notification after `max_retry_attempts`
  - Expires old messages (>24 hours)
  - Added `_should_skip_message()` helper method

## Key Behavioral Changes

### Squad-Based Workflows
- **Before**: Workflows were group-scoped (only one active workflow per group)
- **After**: Workflows are squad-scoped (each squad can have active workflows)
- **Benefit**: Multiple squads can request changes simultaneously

### IsRelatedMessage Check
- **Before**: Any message while workflow active would resume that workflow
- **After**: LLM determines if message is related before resuming
- **Benefit**: Prevents unrelated messages from interfering with workflows

### Interaction Tracking & Escalation
- **Before**: Unlimited clarification interactions
- **After**: After 2 clarifications, escalates to human admin
- **Benefit**: Prevents infinite loops of ambiguous exchanges

### Message Queue Robustness
- **Before**: Messages processed immediately, no retry on failure
- **After**: Messages queued, retried on failure, admin notified if max retries exceeded
- **Benefit**: No lost messages due to transient errors

### Poller Concurrency Control
- **Before**: No protection against concurrent pollers
- **After**: File-based lock, stale lock detection with admin notification
- **Benefit**: Prevents race conditions and duplicate processing

## Next Steps: Deployment

### 1. Run Database Migrations
```bash
# Connect to Supabase and run migrations
cd scripts/migrations

# Run migration 001
psql $SUPABASE_CONNECTION_STRING < 001_create_message_queue.sql

# Run migration 002
psql $SUPABASE_CONNECTION_STRING < 002_add_user_squad_to_workflows.sql
```

### 2. Update Environment Variables
Ensure `.env` has the new admin setting:
```bash
ADMIN_GROUPME_USER_ID=137549805  # Admin's GroupMe user ID
```

### 3. Test Plan

#### Test 1: Squad-Based Workflow Routing
1. Have Squad 42 member send: "We can't make Saturday"
2. Have Squad 54 member send: "We can't make Sunday"
3. **Expected**: Both workflows should start (squad-scoped)

#### Test 2: IsRelatedMessage Check
1. Start a workflow for Squad 42
2. Bot asks: "What time does the shift start?"
3. Squad 42 member responds: "1800"
4. **Expected**: Workflow resumes (related message)
5. Random user says: "What's for lunch?"
6. **Expected**: Workflow doesn't resume (unrelated message)

#### Test 3: Interaction Limit & Admin Escalation
1. Start a workflow
2. Provide ambiguous information twice
3. **Expected**: After 2nd clarification, admin gets DM, workflow marked EXPIRED

#### Test 4: Message Queue Retry
1. Simulate a temporary error during processing
2. **Expected**: Message status set to FAILED, retry_count incremented
3. On next poll, message reprocessed
4. After 3 failures, admin notified

#### Test 5: Poller Lock
1. Start poller process
2. Try to start second poller while first is running
3. **Expected**: Second poller yields (logs "Another poller is active")

#### Test 6: Stale Lock Detection
1. Create stale lock file: `echo '{"poller_instance_id":"test","started_at":"2026-01-03T00:00:00"}' > data/poller.lock`
2. Start poller
3. **Expected**: Detects stale lock (>30min), notifies admin, overrides lock

### 4. Monitoring

Check these logs for proper operation:
- **Poller lock operations**: Look for "Created poller lock" / "Released poller lock"
- **Message queue**: Look for "Queued N new messages" / "Processing N pending messages"
- **IsRelatedMessage checks**: Look for "IsRelatedMessage result: related=true/false"
- **Admin notifications**: Look for "Admin notification sent"
- **Workflow escalations**: Look for "Workflow has reached interaction limit"

### 5. Database Queries for Monitoring

```sql
-- Check message queue status distribution
SELECT status, COUNT(*) FROM message_queue GROUP BY status;

-- Check workflows by squad
SELECT squad_id, status, COUNT(*) FROM workflows
WHERE status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING')
GROUP BY squad_id, status;

-- Check failed messages needing attention
SELECT * FROM message_queue
WHERE status = 'FAILED' AND retry_count >= 3
ORDER BY created_at DESC;

-- Check expired messages
SELECT COUNT(*) FROM message_queue WHERE status = 'EXPIRED';
```

## Configuration Reference

### New Settings in `src/config.py`
```python
# Admin Notifications
admin_groupme_user_id: str = "137549805"

# Poller Settings
poller_timeout_minutes: int = 30
poller_lock_file: str = "data/poller.lock"

# Message Queue Settings
message_expiry_hours: int = 24
max_retry_attempts: int = 3

# Workflow Settings
workflow_interaction_limit: int = 2
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   GroupMe Message                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              GroupMe Poller (with Lock)                 │
│  1. Acquire poller lock                                 │
│  2. Fetch new messages                                  │
│  3. Insert into message_queue (status: PENDING)         │
│  4. Process PENDING messages                            │
│  5. Expire old messages                                 │
│  6. Release lock                                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Message Queue Manager                      │
│  - Get pending messages                                 │
│  - Update status (PENDING → PROCESSING → DONE/FAILED)  │
│  - Track retry_count                                    │
│  - Notify admin if max retries exceeded                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│            Conversation Router (Squad-Based)            │
│  1. Check for active workflows by sender's squad        │
│  2. If exists, use IsRelatedMessage check               │
│  3. If related, resume workflow                         │
│  4. Track interaction_count                             │
│  5. Escalate to admin if limit exceeded                 │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│        IsRelatedMessage Checker (gpt-4o-mini)           │
│  - Analyzes message vs workflow context                 │
│  - Returns (is_related, confidence, reasoning)          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│            Workflow Manager (LangGraph)                 │
│  - Start new workflow with squad_id                     │
│  - Resume existing workflow                             │
│  - Increment interaction_count on clarification         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                  Admin Notifier                         │
│  - Send GroupMe DM to admin on critical events          │
│  - poller_timeout, workflow_escalation, retry_exceeded  │
└─────────────────────────────────────────────────────────┘
```

## Summary

✅ **Completed**: All code changes and new modules
✅ **Database Migrations**: SQL files ready to run
⏳ **Pending**: Run migrations, deploy, test

The implementation follows the specification exactly as outlined in `ai_prompts/UpdatesForMessageProcessing.md` with squad-based workflows, message queue pattern, poller locking, IsRelatedMessage checking, and admin escalation.
