-- D1 Database Migration: Add Missing Indexes and Columns
-- Run this against the clickup-events D1 database

-- ============================================
-- PHASE 1: Add missing indexes (no downtime)
-- ============================================

-- Index for division breakdown queries
CREATE INDEX IF NOT EXISTS idx_events_list_id ON events(list_id);

-- Index for user activity queries
CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id);

-- Index for space-based queries
CREATE INDEX IF NOT EXISTS idx_events_space_id ON events(space_id);

-- Composite index for time-series analysis by event type
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, received_at);

-- Composite index for task history (most recent first)
CREATE INDEX IF NOT EXISTS idx_events_task_time ON events(task_id, received_at);

-- Index for assignee-based queries
CREATE INDEX IF NOT EXISTS idx_events_assignee_id ON events(assignee_id);

-- ============================================
-- PHASE 2: Add new columns (safe ALTERs)
-- ============================================

-- Add assignee_id column (extract from taskAssigneeUpdated events)
ALTER TABLE events ADD COLUMN assignee_id TEXT;

-- Add parent_task_id for subtask hierarchy
ALTER TABLE events ADD COLUMN parent_task_id TEXT;

-- Add priority column (extract from taskPriorityUpdated events)
ALTER TABLE events ADD COLUMN priority TEXT;

-- Add source column to track webhook vs snapshot data
ALTER TABLE events ADD COLUMN source TEXT DEFAULT 'webhook';

-- Add snapshot timestamp to list_space_map
ALTER TABLE list_space_map ADD COLUMN snapshot_ts TEXT;
ALTER TABLE list_space_map ADD COLUMN active INTEGER DEFAULT 1;

-- ============================================
-- PHASE 3: Backfill existing data
-- ============================================

-- Backfill assignee_id from existing payload data
-- This parses the raw JSON to extract assignee info from taskAssigneeUpdated events
UPDATE events 
SET assignee_id = json_extract(payload, '$.history_items[0].after.id')
WHERE event_type = 'taskAssigneeUpdated' 
  AND assignee_id IS NULL;

-- Backfill parent_task_id from existing payload data
UPDATE events
SET parent_task_id = json_extract(payload, '$.parent')
WHERE parent_task_id IS NULL;

-- Backfill priority from existing payload data
UPDATE events
SET priority = json_extract(payload, '$.history_items[0].after.priority.priority')
WHERE event_type = 'taskPriorityUpdated'
  AND priority IS NULL;

-- Mark historical data as 'webhook' source
UPDATE events SET source = 'webhook' WHERE source IS NULL;

-- Mark list_space_map entries as active (from latest snapshot)
UPDATE list_space_map SET active = 1, snapshot_ts = datetime('now');

-- ============================================
-- VERIFICATION QUERIES
-- ============================================

-- Verify indexes were created
SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events';

-- Verify new columns exist
PRAGMA table_info(events);

-- Check row counts for new columns
SELECT 
  'assignee_id populated' as metric,
  COUNT(*) as count
FROM events 
WHERE assignee_id IS NOT NULL
UNION ALL
SELECT 
  'parent_task_id populated',
  COUNT(*) 
FROM events 
WHERE parent_task_id IS NOT NULL
UNION ALL
SELECT 
  'priority populated',
  COUNT(*) 
FROM events 
WHERE priority IS NOT NULL;

-- ============================================
-- PERFORMANCE TEST QUERIES
-- ============================================

-- Test division breakdown (should use idx_events_list_id)
EXPLAIN QUERY PLAN
SELECT m.space_name, COUNT(*) as events
FROM events e
LEFT JOIN list_space_map m ON e.list_id = m.list_id
WHERE e.event_type NOT IN ('test', 'taskUpdated')
GROUP BY m.space_name;

-- Test user activity (should use idx_events_user_id)
EXPLAIN QUERY PLAN
SELECT user_name, COUNT(*) as actions
FROM events
WHERE user_id IS NOT NULL
GROUP BY user_name
ORDER BY actions DESC
LIMIT 10;

-- Test task history (should use idx_events_task_time)
EXPLAIN QUERY PLAN
SELECT * FROM events 
WHERE task_id = 'test123'
ORDER BY received_at DESC
LIMIT 10;
