# ClickUp Data Model - Robust Schema Design

## Design Principles

1. **Capture entities** - Tasks, users, lists, spaces as first-class entities
2. **Track relationships** - Task hierarchy (subtasks), linked tasks, assignments
3. **Audit everything** - Status transitions, field changes, comment threads
4. **Query-friendly** - Avoid JSON parsing in common queries
5. **Immutable events** - Append-only log for audit trail

---

## Entity Relationship Diagram

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   spaces    │────<│   lists     │────<│    tasks    │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                           │                   ├────< task_assignments
                           │                   ├────< task_status_log
                           │                   ├────< task_comments
                           │                   ├────< task_attachments
                           │                   ├────< task_checklists
                           │                   └────< task_links
                           │
┌─────────────┐     ┌─────────────┐
│   users     │────<│  assignments│
└─────────────┘     └─────────────┘
```

---

## Core Tables

### workspaces
```sql
CREATE TABLE workspaces (
  id          TEXT PRIMARY KEY,           -- ClickUp team ID (2298436)
  name        TEXT NOT NULL,
  created_at  TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);
```

### spaces
```sql
CREATE TABLE spaces (
  id            TEXT PRIMARY KEY,
  workspace_id   TEXT NOT NULL REFERENCES workspaces(id),
  name          TEXT NOT NULL,
  url           TEXT,
  created_at    TEXT,
  fetched_at    TEXT DEFAULT (datetime('now'))
);
```

### lists
```sql
CREATE TABLE lists (
  id          TEXT PRIMARY KEY,
  space_id    TEXT NOT NULL REFERENCES spaces(id),
  folder_id   TEXT,
  name        TEXT NOT NULL,
  created_at  TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);
```

### users
```sql
CREATE TABLE users (
  id          TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  username    TEXT,
  email       TEXT,
  color       TEXT,
  profile_url TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);
```

### tasks
```sql
CREATE TABLE tasks (
  id              TEXT PRIMARY KEY,
  list_id         TEXT NOT NULL REFERENCES lists(id),
  parent_task_id  TEXT REFERENCES tasks(id),  -- For subtasks
  name            TEXT NOT NULL,
  description     TEXT,
  status          TEXT,
  status_type     TEXT,           -- open, closed, null
  priority        INTEGER,         -- 1=urgent, 2=high, 3=normal, 4=low, null=none
  due_date        TEXT,
  start_date      TEXT,
  url             TEXT,
  creator_id      TEXT REFERENCES users(id),
  created_at      TEXT,
  updated_at      TEXT,
  closed_at       TEXT,
  fetched_at      TEXT DEFAULT (datetime('now')),
  
  -- Flattened for easy querying
  space_id        TEXT,            -- Denormalized from list join
  workspace_id     TEXT            -- Denormalized for quick filters
);
```

---

## Audit/Event Tables

### status_transitions
Captures every status change for workflow analysis.
```sql
CREATE TABLE status_transitions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  from_status     TEXT,
  to_status       TEXT NOT NULL,
  from_status_type TEXT,
  to_status_type   TEXT,
  user_id         TEXT REFERENCES users(id),
  user_name       TEXT,
  list_id         TEXT,
  space_id        TEXT,
  workspace_id    TEXT,
  event_id        TEXT,            -- Link to events.raw_event_id
  transitioned_at  TEXT NOT NULL DEFAULT (datetime('now')),
  source          TEXT DEFAULT 'webhook'  -- 'webhook', 'snapshot', 'backfill'
);

CREATE INDEX idx_trans_task ON status_transitions(task_id);
CREATE INDEX idx_trans_space ON status_transitions(space_id);
CREATE INDEX idx_trans_time ON status_transitions(transitioned_at);
CREATE INDEX idx_trans_user ON status_transitions(user_id);
```

### task_assignments
Current and historical assignments.
```sql
CREATE TABLE task_assignments (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  user_id         TEXT REFERENCES users(id),
  assigned_at     TEXT NOT NULL DEFAULT (datetime('now')),
  assigned_by     TEXT REFERENCES users(id),
  unassigned_at   TEXT,                    -- NULL if currently assigned
  is_current      INTEGER DEFAULT 1,
  source          TEXT DEFAULT 'webhook'
);

CREATE INDEX idx_assign_task ON task_assignments(task_id);
CREATE INDEX idx_assign_user ON task_assignments(user_id);
CREATE INDEX idx_assign_current ON task_assignments(is_current);
```

### task_comments
Full comment threads with metadata.
```sql
CREATE TABLE task_comments (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  user_id         TEXT REFERENCES users(id),
  user_name       TEXT,
  content         TEXT,                    -- Plain text extracted
  comment_count   INTEGER DEFAULT 0,        -- Replies in thread
  mention_count   INTEGER DEFAULT 0,        -- @mentions in comment
  attachment_count INTEGER DEFAULT 0,       -- Files attached
  created_at      TEXT,
  updated_at      TEXT,
  fetched_at      TEXT DEFAULT (datetime('now')),
  source          TEXT DEFAULT 'webhook'
);

CREATE INDEX idx_comment_task ON task_comments(task_id);
CREATE INDEX idx_comment_user ON task_comments(user_id);
CREATE INDEX idx_comment_time ON task_comments(created_at);
```

### task_attachments
File attachments with metadata.
```sql
CREATE TABLE task_attachments (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  user_id         TEXT REFERENCES users(id),
  filename        TEXT,
  filetype        TEXT,
  filesize        INTEGER,
  url             TEXT,
  thumbnail_url   TEXT,
  uploaded_at     TEXT,
  fetched_at      TEXT DEFAULT (datetime('now')),
  source          TEXT DEFAULT 'webhook'
);

CREATE INDEX idx_attach_task ON task_attachments(task_id);
CREATE INDEX idx_attach_time ON task_attachments(uploaded_at);
```

### task_checklists
Checklist progress tracking.
```sql
CREATE TABLE task_checklists (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  name            TEXT,
  position        INTEGER,
  created_at      TEXT,
  fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE checklist_items (
  id              TEXT PRIMARY KEY,
  checklist_id    TEXT NOT NULL REFERENCES task_checklists(id),
  name            TEXT,
  resolved        INTEGER DEFAULT 0,        -- 1=completed, 0=pending
  resolved_by     TEXT REFERENCES users(id),
  resolved_at     TEXT,
  position        INTEGER,
  fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_checklist_task ON task_checklists(task_id);
CREATE INDEX idx_item_checklist ON checklist_items(checklist_id);
```

### task_links
Dependency and relationship tracking.
```sql
CREATE TABLE task_links (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  linked_task_id  TEXT NOT NULL REFERENCES tasks(id),
  link_direction  TEXT NOT NULL,           -- 'outward' or 'inward'
  link_type       TEXT NOT NULL,           -- 'blocked_by', 'blocks', 'relates_to', etc.
  created_by      TEXT REFERENCES users(id),
  created_at      TEXT,
  source          TEXT DEFAULT 'webhook'
);

CREATE INDEX idx_link_task ON task_links(task_id);
CREATE INDEX idx_link_type ON task_links(link_type);
```

### task_tags
```sql
CREATE TABLE task_tags (
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  tag_id          TEXT NOT NULL,
  tag_name        TEXT NOT NULL,
  created_at      TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (task_id, tag_id)
);

CREATE INDEX idx_tag_task ON task_tags(task_id);
CREATE INDEX idx_tag_name ON task_tags(tag_name);
```

---

## Custom Fields (Denormalized for Querying)

For the specific custom fields in use (SMPL Req, Revision received, etc.)
```sql
CREATE TABLE task_custom_fields (
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  field_id        TEXT NOT NULL,           -- ClickUp field ID
  field_name      TEXT NOT NULL,           -- 'SMPL Req', 'Customer / Retailer', etc.
  field_type      TEXT,                    -- 'number', 'date', 'dropdown', 'text'
  value_text      TEXT,                    -- For text, dropdown
  value_number    REAL,                    -- For numbers
  value_date      TEXT,                    -- For dates
  value_boolean   INTEGER,                 -- For checkboxes
  updated_at      TEXT,
  
  PRIMARY KEY (task_id, field_id)
);

CREATE INDEX idx_cf_task ON task_custom_fields(task_id);
CREATE INDEX idx_cf_field ON task_custom_fields(field_name);
```

---

## Raw Event Log (for debugging/reprocessing)

```sql
CREATE TABLE raw_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type      TEXT NOT NULL,
  task_id         TEXT,
  list_id         TEXT,
  workspace_id    TEXT,
  user_id         TEXT,
  user_name       TEXT,
  field_changed   TEXT,
  from_value      TEXT,
  to_value        TEXT,
  space_id        TEXT,
  raw_payload     TEXT NOT NULL,
  received_at     TEXT NOT NULL DEFAULT (datetime('now')),
  processed       INTEGER DEFAULT 0,
  processed_at    TEXT
);

CREATE INDEX idx_raw_type ON raw_events(event_type);
CREATE INDEX idx_raw_task ON raw_events(task_id);
CREATE INDEX idx_raw_time ON raw_events(received_at);
```

---

## Analysis Views

```sql
-- Task completion times by status
CREATE VIEW task_completion_times AS
SELECT 
  t.id,
  t.name,
  t.space_id,
  s.to_status,
  s.to_status_type,
  s.transitioned_at,
  LAG(s.transitioned_at) OVER (PARTITION BY t.id ORDER BY s.transitioned_at) as prev_transition,
  JULIANDAY(s.transitioned_at) - JULIANDAY(LAG(s.transitioned_at) OVER (PARTITION BY t.id ORDER BY s.transitioned_at)) as days_in_prev_status
FROM tasks t
JOIN status_transitions s ON t.id = s.task_id;

-- User activity summary
CREATE VIEW user_activity AS
SELECT 
  u.id,
  u.username,
  COUNT(DISTINCT s.task_id) as tasks_transitioned,
  COUNT(s.id) as total_transitions,
  COUNT(c.id) as comments_made,
  COUNT(a.id) as assignments_made
FROM users u
LEFT JOIN status_transitions s ON u.id = s.user_id
LEFT JOIN task_comments c ON u.id = c.user_id
LEFT JOIN task_assignments a ON u.id = a.user_id
GROUP BY u.id;

-- Workflow efficiency (time in each status)
CREATE VIEW workflow_efficiency AS
SELECT 
  space_id,
  from_status,
  to_status,
  COUNT(*) as transition_count,
  AVG(JULIANDAY(transitioned_at) - JULIANDAY(prev_transition)) as avg_days,
  AVG(JULIANDAY(transitioned_at) - JULIANDAY(prev_transition)) * 24 as avg_hours
FROM task_completion_times
WHERE prev_transition IS NOT NULL
GROUP BY space_id, from_status, to_status
ORDER BY avg_days DESC;
```

---

## Summary

| Table | Purpose | Rows Est. |
|-------|---------|-----------|
| workspaces | Team/org | 1 |
| spaces | Divisions | 3 |
| lists | Project lists | 50 |
| users | Team members | 64 |
| tasks | Work items | 17,746 |
| status_transitions | Workflow audit | ~100K |
| task_assignments | Who does what | ~50K |
| task_comments | Communication | ~10K |
| task_attachments | Files shared | ~1K |
| task_checklists | Progress tracking | ~5K |
| checklist_items | Checklist items | ~20K |
| task_links | Dependencies | ~500 |
| task_custom_fields | Product data | ~50K |
| raw_events | Debug/reprocess | Growing |

**Why this is robust:**
1. **Normalized entities** - Easy to join and filter
2. **Immutable audit logs** - Can trace history of any change
3. **Proper indexes** - All foreign keys indexed
4. **Denormalized for queries** - space_id on tasks for quick filtering
5. **Custom fields flattened** - Easy to query product-specific data
6. **Views for analysis** - Pre-built queries for common reports
