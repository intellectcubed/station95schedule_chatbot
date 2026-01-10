-- Migration: Add user_id and squad_id to workflows table
-- Description: Enable squad-based workflow scoping
-- Date: 2025-01-03

-- Add new columns
ALTER TABLE workflows
ADD COLUMN IF NOT EXISTS user_id TEXT,
ADD COLUMN IF NOT EXISTS squad_id INTEGER;

-- Add index for squad-based queries
CREATE INDEX IF NOT EXISTS idx_workflows_squad_status
ON workflows(squad_id, status)
WHERE status IN ('NEW', 'WAITING_FOR_INPUT', 'READY', 'EXECUTING');

-- Add comments
COMMENT ON COLUMN workflows.user_id IS 'GroupMe user ID who initiated the workflow (nullable)';
COMMENT ON COLUMN workflows.squad_id IS 'Squad number (34, 35, 42, 43, 54) for squad-scoped workflows (nullable)';
