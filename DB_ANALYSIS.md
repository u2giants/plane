# Database Schema Analysis

## Current Design Assessment

The schema captures the minimum viable event log. Here's what's good and what needs improvement:

## Current Schema

```sql
-- events table (current)
CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type    TEXT NOT NULL,
  task_id       TEXT,
  list_id       TEXT,
  workspace_id  TEXT,
  payload       TEXT NOT NULL,
  received_at   TEXT NOT NULL DEFAULT (datetime('now')),
  processed     INTEGER DEFAULT 0,
  user_id       TEXT,
  user_name     TEXT,
  field_changed TEXT,
  from_value    TEXT,
  to_value      TEXT,
  space_id      TEXT
);

-- Missing indexes!
```

## What's Good ✅

1. **Raw payload always stored** - enables re-processing if enrichment logic changes
2. **Simple, flexible** - can capture any event type without schema changes
3. **list_space_map JOIN** - enables division-aware queries

## What's Missing or Wrong ❌

### Critical Index Gaps
| Column | Used For | Missing Index? |
|--------|---------|---------------|
| `list_id` | Division breakdown | ❌ **NO INDEX** |
| `user_id` | User activity analysis | ❌ **NO INDEX** |
| `space_id` | Division breakdown | ❌ **NO INDEX** |
| `(event_type, received_at)` | Time-series by type | ❌ **NO COMPOSITE** |
| `(task_id, received_at)` | Task history | ❌ **NO COMPOSITE** |

**Impact:** Queries filtering by list_id, user_id, or doing time-series analysis will do full table scans. With 1000+ events/day, this will become slow.

### Structural Data Gaps
1. **No `assignee_id`** - taskAssigneeUpdated events have no indexed column for "who was assigned"
2. **No `parent_task_id`** - subtask hierarchy not captured (96% of tasks are subtasks!)
3. **No `priority`** - priority changes not stored as a dedicated column
4. **No `team_id` (workspace)** - workspace_id is wrong in current data

### Data Quality Issues
1. **`from_value`/`to_value` JSON-stringified** - can't query "tasks that went to status X" without parsing
2. **`processed` column unused** - set to 0, never consumed
3. **list_space_map is static snapshot** - lists change over time, map becomes stale

## Recommended Schema Changes

```sql
-- events table (proposed)
CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type    TEXT NOT NULL,
  task_id       TEXT NOT NULL,
  list_id       TEXT,              -- add index
  workspace_id  TEXT NOT NULL,      -- should be team_id (2298436)
  payload       TEXT NOT NULL,
  received_at   TEXT NOT NULL DEFAULT (datetime('now')),
  
  -- Enrichment (current + new)
  user_id       TEXT,
  user_name     TEXT,
  field_changed TEXT,
  from_value    TEXT,
  to_value      TEXT,
  space_id      TEXT,
  
  -- New indexed columns for common queries
  assignee_id   TEXT,              -- who was assigned (taskAssigneeUpdated)
  priority      TEXT,              -- from taskPriorityUpdated
  parent_task_id TEXT,             -- for subtask relationships
  source        TEXT DEFAULT 'webhook',  -- 'webhook' or 'snapshot'
  
  -- Proper indexes
  INDEX idx_list_id      ON events(list_id),
  INDEX idx_user_id      ON events(user_id),
  INDEX idx_task_id      ON events(task_id),
  INDEX idx_event_type   ON events(event_type),
  INDEX idx_received_at  ON events(received_at),
  INDEX idx_assignee     ON events(assignee_id),
  INDEX idx_type_time    ON events(event_type, received_at),
  INDEX idx_task_time    ON events(task_id, received_at)
);

-- Keep list_space_map but add a timestamp
ALTER TABLE list_space_map ADD COLUMN snapshot_ts TEXT;
ALTER TABLE list_space_map ADD COLUMN active INTEGER DEFAULT 1;
```

## Key Queries That Need Indexes

Without indexes, these common queries will be slow:
```sql
-- User activity (full scan without idx_user_id)
SELECT user_name, COUNT(*) FROM events WHERE user_id = '123'

-- Division breakdown (full scan without idx_list_id)  
SELECT space_name, COUNT(*) FROM events e JOIN list_space_map m ON e.list_id = m.list_id

-- Recent task history (full scan without idx_task_time)
SELECT * FROM events WHERE task_id = 'xyz' ORDER BY received_at DESC LIMIT 10

-- Hourly activity (full scan without idx_type_time)
SELECT strftime('%H', received_at), COUNT(*) FROM events GROUP BY 1
```

## Summary

| Aspect | Current | Recommended |
|--------|---------|-------------|
| Basic indexes | 3 (type, task, time) | 9 (add list, user, assignee, composites) |
| Assignee tracking | In payload only | Dedicated column |
| Subtask hierarchy | Not captured | parent_task_id column |
| Division queries | Slow (no list_id index) | Fast (indexed list_id) |
| Re-processing | Full payload stored | Keep (good) |

**Action:** Run `scripts/migrate_schema.sql` to add all indexes and columns.
