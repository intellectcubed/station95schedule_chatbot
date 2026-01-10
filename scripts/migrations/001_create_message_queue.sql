-- Migration: Create message_queue table
-- Description: Add message queue for robust message processing
-- Date: 2025-01-03

CREATE TABLE IF NOT EXISTS message_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id TEXT UNIQUE NOT NULL,
    group_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    message_text TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RECEIVED',
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_message_queue_status
ON message_queue(status)
WHERE status IN ('PENDING', 'PROCESSING', 'FAILED');

CREATE INDEX IF NOT EXISTS idx_message_queue_created
ON message_queue(created_at);

-- Add comment
COMMENT ON TABLE message_queue IS 'Queue for GroupMe messages with status tracking';
COMMENT ON COLUMN message_queue.status IS 'Status: RECEIVED|PENDING|PROCESSING|DONE|FAILED|EXPIRED|SKIPPED';
