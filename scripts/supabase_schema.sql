-- Supabase Schema for Stateful Agentic Chat Processor
-- Run this SQL in your Supabase SQL editor to create the required tables

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Table: workflows
-- Purpose: Track workflow instances, their lifecycle, and serialized state
-- =============================================================================

CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id VARCHAR(255) NOT NULL,
    workflow_type VARCHAR(50) NOT NULL,  -- e.g., 'shift_unavailability'
    status VARCHAR(50) NOT NULL,  -- NEW, WAITING_FOR_INPUT, READY, EXECUTING, COMPLETED, EXPIRED
    state_data JSONB DEFAULT '{}',  -- Serialized LangGraph state
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,  -- Workflow expiration time
    metadata JSONB DEFAULT '{}',  -- Additional context/data

    -- Constraints
    CHECK (status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING', 'COMPLETED', 'EXPIRED')),
    CHECK (workflow_type IN ('shift_unavailability'))  -- Can be extended later
);

-- Indexes for efficient querying
CREATE INDEX idx_workflows_group_id ON workflows(group_id);
CREATE INDEX idx_workflows_status ON workflows(status);
CREATE INDEX idx_workflows_group_status ON workflows(group_id, status);
CREATE INDEX idx_workflows_expires_at ON workflows(expires_at);

-- Partial index for active workflows (most common query)
CREATE INDEX idx_workflows_active ON workflows(group_id, status)
WHERE status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING');

COMMENT ON TABLE workflows IS 'Tracks workflow instances, their lifecycle state, and serialized LangGraph state';
COMMENT ON COLUMN workflows.status IS 'Current workflow status: NEW, WAITING_FOR_INPUT, READY, EXECUTING, COMPLETED, EXPIRED';
COMMENT ON COLUMN workflows.state_data IS 'Serialized LangGraph state as JSON (conversation history, extracted parameters, etc.)';
COMMENT ON COLUMN workflows.expires_at IS 'When this workflow will expire (typically 24 hours after creation)';
COMMENT ON COLUMN workflows.metadata IS 'Additional workflow context stored as JSON';

-- =============================================================================
-- Table: conversations
-- Purpose: Store all messages from GroupMe for context and history
-- =============================================================================

CREATE TABLE conversations (
    message_id VARCHAR(255) PRIMARY KEY,  -- GroupMe's message ID (natural key)
    group_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    user_name VARCHAR(255) NOT NULL,
    message_text TEXT NOT NULL,
    timestamp BIGINT NOT NULL,  -- Unix timestamp from GroupMe
    workflow_id UUID NULL,  -- Reference to workflow if message is part of one
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Foreign key constraint
    CONSTRAINT fk_workflow FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE SET NULL
);

-- Indexes for efficient querying
CREATE INDEX idx_conversations_group_id ON conversations(group_id);
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_conversations_timestamp ON conversations(timestamp DESC);
CREATE INDEX idx_conversations_workflow_id ON conversations(workflow_id);
CREATE INDEX idx_conversations_group_timestamp ON conversations(group_id, timestamp DESC);

-- Composite index for getting recent messages by group
CREATE INDEX idx_conversations_group_created ON conversations(group_id, created_at DESC);

COMMENT ON TABLE conversations IS 'Stores all GroupMe messages for conversation context and history';
COMMENT ON COLUMN conversations.message_id IS 'GroupMe message ID (used as primary key to prevent duplicates)';
COMMENT ON COLUMN conversations.timestamp IS 'Unix timestamp from GroupMe message (created_at field)';
COMMENT ON COLUMN conversations.workflow_id IS 'Links message to a workflow if it is part of one';

-- =============================================================================
-- Row Level Security (RLS) - Optional but recommended
-- =============================================================================

-- Enable RLS on all tables
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;

-- Create policies for service role (full access)
-- Your application should use the service role key for all operations

CREATE POLICY "Service role has full access to conversations"
    ON conversations
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Service role has full access to workflows"
    ON workflows
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- Sample Queries (for reference/testing)
-- =============================================================================

-- Get recent messages for a group (for conversation context)
-- SELECT * FROM conversations
-- WHERE group_id = 'your_group_id'
-- ORDER BY timestamp DESC
-- LIMIT 20;

-- Get active workflow for a group (with state)
-- SELECT * FROM workflows
-- WHERE group_id = 'your_group_id'
-- AND status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING')
-- ORDER BY created_at DESC
-- LIMIT 1;

-- Get workflow by ID (includes state_data)
-- SELECT * FROM workflows
-- WHERE id = 'workflow_uuid';

-- Get all messages associated with a workflow
-- SELECT * FROM conversations
-- WHERE workflow_id = 'workflow_uuid'
-- ORDER BY timestamp ASC;

-- Update workflow state and status (application code sets updated_at explicitly)
-- UPDATE workflows
-- SET status = 'READY',
--     state_data = '{"squad": 42, "date": "20251223", ...}'::jsonb,
--     updated_at = NOW()
-- WHERE id = 'workflow_uuid';

-- Expire old workflows (done by application code, not database function)
-- UPDATE workflows
-- SET status = 'EXPIRED',
--     updated_at = NOW()
-- WHERE status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING')
-- AND expires_at < NOW();
