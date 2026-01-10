# Miltiple messages processing and handling responses Modifications

A poller that reads multiple GroupMe messages at once

A handler that must process messages one at a time

# Messages can:

- start workflows
- advance workflows
- complete workflows

Processing can be slow

You must not lose messages if the process crashes

The Group poller currently pull 

Handle 
 - Create message queue with database?  If I pull 10 messages, then I can determine if new workflow, or response to workflow.
 - Have pending workflows
 - pick up 10 messages, Each message is a continuation of a workflow, or a new workflow.  
 

## Messages will be stored in a table called message-queue.
```
create table message_queue (
  id bigserial primary key,
  source_message_id text not null,      -- GroupMe message id
  sender_id text not null,
  payload jsonb not null,
  status text not null default 'PENDING', -- PENDING | PROCESSING | DONE | FAILED
  workflow_id text,
  created_at timestamptz default now(),
  locked_at timestamptz
);

create index on message_queue (status, created_at);

```

Messages should have a ttl - maybe should be deleted after a day.  Since there is no TTL mechanism 

Workflow-Aware Expiration (More Important)

Time-based TTL alone will still fail in this scenario:

User answers a question
Workflow already closed
Message arrives late

You need workflow context checks

For each incoming message:

Is there an open workflow for this user/squad?

Is that workflow in AWAITING_RESPONSE?

Does the message plausibly answer that question?

If no, then:

Treat as a new message, or

Discard as stale/noise

## Recommended Message Lifecycle

Use a lightweight message state machine:

RECEIVED
  ↓
QUEUED
  ↓
PROCESSED
  ↓
COMPLETED | STALE | EXPIRED

