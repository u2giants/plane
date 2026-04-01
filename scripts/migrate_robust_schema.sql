-- ============================================
-- PHASE 1: Core Entity Tables
-- ============================================

-- Workspaces
CREATE TABLE IF NOT EXISTS workspaces (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  created_at  TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);

-- Spaces (divisions)
CREATE TABLE IF NOT EXISTS spaces (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL,
  name          TEXT NOT NULL,
  url           TEXT,
  created_at    TEXT,
  fetched_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_spaces_workspace ON spaces(workspace_id);

-- Lists
CREATE TABLE IF NOT EXISTS lists (
  id          TEXT PRIMARY KEY,
  space_id    TEXT NOT NULL,
  folder_id   TEXT,
  name        TEXT NOT NULL,
  created_at  TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lists_space ON lists(space_id);
CREATE INDEX IF NOT EXISTS idx_lists_folder ON lists(folder_id);

-- Users
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  workspace_id   TEXT NOT NULL,
  username      TEXT,
  email         TEXT,
  color         TEXT,
  profile_url   TEXT,
  fetched_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_workspace ON users(workspace_id);

-- Tasks (main entity)
CREATE TABLE IF NOT EXISTS tasks (
  id              TEXT PRIMARY KEY,
  list_id         TEXT NOT NULL,
  parent_task_id  TEXT,
  name            TEXT NOT NULL,
  description     TEXT,
  status          TEXT,
  status_type     TEXT,
  priority        INTEGER,
  due_date        TEXT,
  start_date      TEXT,
  url             TEXT,
  creator_id      TEXT,
  created_at      TEXT,
  updated_at      TEXT,
  closed_at       TEXT,
  fetched_at      TEXT DEFAULT (datetime('now')),
  space_id        TEXT,
  workspace_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_list ON tasks(list_id);
CREATE INDEX IF NOT EXISTS idx_tasks_space ON tasks(space_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);

-- ============================================
-- PHASE 2: Audit/Event Tables
-- ============================================

-- Status transitions (workflow audit)
CREATE TABLE IF NOT EXISTS status_transitions (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id           TEXT NOT NULL,
  from_status       TEXT,
  to_status         TEXT NOT NULL,
  from_status_type  TEXT,
  to_status_type     TEXT,
  user_id           TEXT,
  user_name         TEXT,
  list_id           TEXT,
  space_id          TEXT,
  workspace_id      TEXT,
  event_id          TEXT,
  transitioned_at   TEXT NOT NULL DEFAULT (datetime('now')),
  source            TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_trans_task ON status_transitions(task_id);
CREATE INDEX IF NOT EXISTS idx_trans_space ON status_transitions(space_id);
CREATE INDEX IF NOT EXISTS idx_trans_time ON status_transitions(transitioned_at);
CREATE INDEX IF NOT EXISTS idx_trans_user ON status_transitions(user_id);
CREATE INDEX IF NOT EXISTS idx_trans_from ON status_transitions(from_status);
CREATE INDEX IF NOT EXISTS idx_trans_to ON status_transitions(to_status);

-- Task assignments
CREATE TABLE IF NOT EXISTS task_assignments (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id         TEXT NOT NULL,
  user_id         TEXT,
  assigned_at     TEXT NOT NULL DEFAULT (datetime('now')),
  assigned_by     TEXT,
  unassigned_at   TEXT,
  is_current      INTEGER DEFAULT 1,
  source          TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_assign_task ON task_assignments(task_id);
CREATE INDEX IF NOT EXISTS idx_assign_user ON task_assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_assign_current ON task_assignments(is_current);

-- Task comments
CREATE TABLE IF NOT EXISTS task_comments (
  id                TEXT PRIMARY KEY,
  task_id           TEXT NOT NULL,
  user_id           TEXT,
  user_name         TEXT,
  content           TEXT,
  comment_count     INTEGER DEFAULT 0,
  mention_count     INTEGER DEFAULT 0,
  attachment_count  INTEGER DEFAULT 0,
  created_at        TEXT,
  updated_at        TEXT,
  fetched_at        TEXT DEFAULT (datetime('now')),
  source            TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_comment_task ON task_comments(task_id);
CREATE INDEX IF NOT EXISTS idx_comment_user ON task_comments(user_id);
CREATE INDEX IF NOT EXISTS idx_comment_time ON task_comments(created_at);

-- Task attachments
CREATE TABLE IF NOT EXISTS task_attachments (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL,
  user_id         TEXT,
  filename        TEXT,
  filetype        TEXT,
  filesize        INTEGER,
  url             TEXT,
  thumbnail_url   TEXT,
  uploaded_at     TEXT,
  fetched_at      TEXT DEFAULT (datetime('now')),
  source          TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_attach_task ON task_attachments(task_id);
CREATE INDEX IF NOT EXISTS idx_attach_time ON task_attachments(uploaded_at);

-- Task checklists
CREATE TABLE IF NOT EXISTS task_checklists (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL,
  name            TEXT,
  position        INTEGER,
  created_at      TEXT,
  fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checklist_items (
  id              TEXT PRIMARY KEY,
  checklist_id    TEXT NOT NULL,
  name            TEXT,
  resolved        INTEGER DEFAULT 0,
  resolved_by     TEXT,
  resolved_at     TEXT,
  position        INTEGER,
  fetched_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_checklist_task ON task_checklists(task_id);
CREATE INDEX IF NOT EXISTS idx_item_checklist ON checklist_items(checklist_id);

-- Task links (dependencies)
CREATE TABLE IF NOT EXISTS task_links (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL,
  linked_task_id  TEXT NOT NULL,
  link_direction  TEXT NOT NULL,
  link_type       TEXT NOT NULL,
  created_by      TEXT,
  created_at      TEXT,
  source          TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_link_task ON task_links(task_id);
CREATE INDEX IF NOT EXISTS idx_link_linked ON task_links(linked_task_id);
CREATE INDEX IF NOT EXISTS idx_link_type ON task_links(link_type);

-- Task tags
CREATE TABLE IF NOT EXISTS task_tags (
  task_id         TEXT NOT NULL,
  tag_id          TEXT NOT NULL,
  tag_name        TEXT NOT NULL,
  created_at      TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (task_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_tag_task ON task_tags(task_id);
CREATE INDEX IF NOT EXISTS idx_tag_name ON task_tags(tag_name);

-- ============================================
-- PHASE 3: Custom Fields
-- ============================================

CREATE TABLE IF NOT EXISTS task_custom_fields (
  task_id         TEXT NOT NULL,
  field_id        TEXT NOT NULL,
  field_name      TEXT NOT NULL,
  field_type      TEXT,
  value_text      TEXT,
  value_number    REAL,
  value_date      TEXT,
  value_boolean   INTEGER,
  updated_at      TEXT,
  PRIMARY KEY (task_id, field_id)
);

CREATE INDEX IF NOT EXISTS idx_cf_task ON task_custom_fields(task_id);
CREATE INDEX IF NOT EXISTS idx_cf_field ON task_custom_fields(field_name);

-- ============================================
-- PHASE 4: Raw Event Log
-- ============================================

CREATE TABLE IF NOT EXISTS raw_events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type      TEXT NOT NULL,
  task_id         TEXT,
  list_id         TEXT,
  workspace_id    TEXT,
  user_id         TEXT,
  user_name       TEXT,
  field_changed   TEXT,
  from_value     TEXT,
  to_value       TEXT,
  space_id       TEXT,
  raw_payload    TEXT NOT NULL,
  received_at    TEXT NOT NULL DEFAULT (datetime('now')),
  processed      INTEGER DEFAULT 0,
  processed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_type ON raw_events(event_type);
CREATE INDEX IF NOT EXISTS idx_raw_task ON raw_events(task_id);
CREATE INDEX IF NOT EXISTS idx_raw_time ON raw_events(received_at);

-- ============================================
-- PHASE 5: Analysis Views
-- ============================================

-- Task completion times
CREATE VIEW IF NOT EXISTS task_completion_times AS
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

-- Workflow efficiency
CREATE VIEW IF NOT EXISTS workflow_efficiency AS
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

-- User activity
CREATE VIEW IF NOT EXISTS user_activity AS
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

-- ============================================
-- VERIFICATION
-- ============================================

SELECT 'Tables created:' as status;
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;

SELECT 'Indexes created:' as status;
SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;

SELECT 'Views created:' as status;
SELECT name FROM sqlite_master WHERE type='view' ORDER BY name;
