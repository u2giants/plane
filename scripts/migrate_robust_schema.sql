-- ============================================
-- FULL SCHEMA — clickup-events D1 database
-- Apply via: wrangler d1 execute clickup-events --file migrate_robust_schema.sql --remote
-- Or via the migrate-database GitHub Actions workflow.
-- Safe to re-run: all statements use CREATE ... IF NOT EXISTS / INSERT OR REPLACE.
-- ============================================

-- ============================================
-- PHASE 1: Core Entity Tables
-- ============================================

CREATE TABLE IF NOT EXISTS workspaces (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  created_at  TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spaces (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL,
  name          TEXT NOT NULL,
  url           TEXT,
  created_at    TEXT,
  fetched_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_spaces_workspace ON spaces(workspace_id);

CREATE TABLE IF NOT EXISTS lists (
  id          TEXT PRIMARY KEY,
  space_id    TEXT NOT NULL,
  folder_id   TEXT,
  name        TEXT NOT NULL,
  created_at  TEXT,
  fetched_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lists_space  ON lists(space_id);
CREATE INDEX IF NOT EXISTS idx_lists_folder ON lists(folder_id);

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL,
  username      TEXT,
  email         TEXT,
  color         TEXT,
  profile_url   TEXT,
  role_id       INTEGER,   -- 1=owner 2=admin 3=member 4=viewer
  role_name     TEXT,      -- "owner" | "admin" | "member" | "viewer"
  date_joined   TEXT,      -- ISO timestamp of workspace join
  last_active   TEXT,      -- ISO timestamp of last ClickUp activity
  fetched_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_workspace ON users(workspace_id);
CREATE INDEX IF NOT EXISTS idx_users_role      ON users(role_id);

CREATE TABLE IF NOT EXISTS tasks (
  id              TEXT PRIMARY KEY,
  list_id         TEXT NOT NULL,
  parent_task_id  TEXT,
  name            TEXT,
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
  workspace_id    TEXT,
  licensor        TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_list    ON tasks(list_id);
CREATE INDEX IF NOT EXISTS idx_tasks_space   ON tasks(space_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent  ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);

-- ============================================
-- PHASE 2: Audit / Event Tables
-- ============================================

CREATE TABLE IF NOT EXISTS status_transitions (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id           TEXT NOT NULL,
  from_status       TEXT,
  to_status         TEXT NOT NULL,
  from_status_type  TEXT,
  to_status_type    TEXT,
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
CREATE INDEX IF NOT EXISTS idx_trans_to   ON status_transitions(to_status);

CREATE TABLE IF NOT EXISTS task_assignments (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id       TEXT NOT NULL,
  user_id       TEXT,
  assigned_at   TEXT NOT NULL DEFAULT (datetime('now')),
  assigned_by   TEXT,
  unassigned_at TEXT,
  is_current    INTEGER DEFAULT 1,
  source        TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_assign_task    ON task_assignments(task_id);
CREATE INDEX IF NOT EXISTS idx_assign_user    ON task_assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_assign_current ON task_assignments(is_current);

CREATE TABLE IF NOT EXISTS task_comments (
  id               TEXT PRIMARY KEY,
  task_id          TEXT NOT NULL,
  user_id          TEXT,
  user_name        TEXT,
  content          TEXT,
  comment_count    INTEGER DEFAULT 0,
  mention_count    INTEGER DEFAULT 0,
  attachment_count INTEGER DEFAULT 0,
  created_at       TEXT,
  updated_at       TEXT,
  fetched_at       TEXT DEFAULT (datetime('now')),
  source           TEXT DEFAULT 'webhook',
  file_paths       TEXT,
  licensor_hint    TEXT
);

CREATE INDEX IF NOT EXISTS idx_comment_task ON task_comments(task_id);
CREATE INDEX IF NOT EXISTS idx_comment_user ON task_comments(user_id);
CREATE INDEX IF NOT EXISTS idx_comment_time ON task_comments(created_at);

CREATE TABLE IF NOT EXISTS task_attachments (
  id            TEXT PRIMARY KEY,
  task_id       TEXT NOT NULL,
  user_id       TEXT,
  filename      TEXT,
  filetype      TEXT,
  filesize      INTEGER,
  url           TEXT,
  thumbnail_url TEXT,
  uploaded_at   TEXT,
  fetched_at    TEXT DEFAULT (datetime('now')),
  source        TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_attach_task ON task_attachments(task_id);
CREATE INDEX IF NOT EXISTS idx_attach_time ON task_attachments(uploaded_at);

CREATE TABLE IF NOT EXISTS task_checklists (
  id         TEXT PRIMARY KEY,
  task_id    TEXT NOT NULL,
  name       TEXT,
  position   INTEGER,
  created_at TEXT,
  fetched_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checklist_items (
  id           TEXT PRIMARY KEY,
  checklist_id TEXT NOT NULL,
  name         TEXT,
  resolved     INTEGER DEFAULT 0,
  resolved_by  TEXT,
  resolved_at  TEXT,
  position     INTEGER,
  fetched_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_checklist_task ON task_checklists(task_id);
CREATE INDEX IF NOT EXISTS idx_item_checklist ON checklist_items(checklist_id);

CREATE TABLE IF NOT EXISTS task_links (
  id             TEXT PRIMARY KEY,
  task_id        TEXT NOT NULL,
  linked_task_id TEXT NOT NULL,
  link_direction TEXT NOT NULL,
  link_type      TEXT NOT NULL,
  created_by     TEXT,
  created_at     TEXT,
  source         TEXT DEFAULT 'webhook'
);

CREATE INDEX IF NOT EXISTS idx_link_task   ON task_links(task_id);
CREATE INDEX IF NOT EXISTS idx_link_linked ON task_links(linked_task_id);
CREATE INDEX IF NOT EXISTS idx_link_type   ON task_links(link_type);

CREATE TABLE IF NOT EXISTS task_tags (
  task_id    TEXT NOT NULL,
  tag_id     TEXT NOT NULL,
  tag_name   TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (task_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_tag_task ON task_tags(task_id);
CREATE INDEX IF NOT EXISTS idx_tag_name ON task_tags(tag_name);

-- ============================================
-- PHASE 3: Custom Fields
-- ============================================

CREATE TABLE IF NOT EXISTS task_custom_fields (
  task_id       TEXT NOT NULL,
  field_id      TEXT NOT NULL,
  field_name    TEXT NOT NULL,
  field_type    TEXT,
  value_text    TEXT,
  value_number  REAL,
  value_date    TEXT,
  value_boolean INTEGER,
  updated_at    TEXT,
  PRIMARY KEY (task_id, field_id)
);

CREATE INDEX IF NOT EXISTS idx_cf_task  ON task_custom_fields(task_id);
CREATE INDEX IF NOT EXISTS idx_cf_field ON task_custom_fields(field_name);

-- Custom field schema definitions (list-level metadata)
CREATE TABLE IF NOT EXISTS custom_field_definitions (
  field_id    TEXT NOT NULL,
  list_id     TEXT NOT NULL,
  name        TEXT,
  type        TEXT,
  options     TEXT,   -- JSON array of {id, name, color, orderindex}
  fetched_at  TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (field_id, list_id)
);

CREATE INDEX IF NOT EXISTS idx_cfd_list ON custom_field_definitions(list_id);

-- Time tracking entries (last 90 days, fetched by snapshot script)
CREATE TABLE IF NOT EXISTS time_entries (
  id            TEXT PRIMARY KEY,
  task_id       TEXT,
  user_id       TEXT,
  user_name     TEXT,
  start_time    TEXT,
  end_time      TEXT,
  duration_ms   INTEGER,
  duration_hrs  REAL,
  billable      INTEGER DEFAULT 0,
  description   TEXT,
  tags          TEXT,    -- JSON array of tag names
  source        TEXT DEFAULT 'snapshot',
  fetched_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_te_task  ON time_entries(task_id);
CREATE INDEX IF NOT EXISTS idx_te_user  ON time_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_te_start ON time_entries(start_time);

-- ============================================
-- PHASE 4: Raw Event Log
-- ============================================

CREATE TABLE IF NOT EXISTS raw_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type    TEXT NOT NULL,
  task_id       TEXT,
  list_id       TEXT,
  workspace_id  TEXT,
  user_id       TEXT,
  user_name     TEXT,
  field_changed TEXT,
  from_value    TEXT,
  to_value      TEXT,
  space_id      TEXT,
  raw_payload   TEXT NOT NULL,
  received_at   TEXT NOT NULL DEFAULT (datetime('now')),
  processed     INTEGER DEFAULT 0,
  processed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_type ON raw_events(event_type);
CREATE INDEX IF NOT EXISTS idx_raw_task ON raw_events(task_id);
CREATE INDEX IF NOT EXISTS idx_raw_time ON raw_events(received_at);

-- ============================================
-- PHASE 4b: Structured Business Entities
-- Retailers and licensors as first-class rows,
-- seeded from products data and maintained over time.
-- ============================================

CREATE TABLE IF NOT EXISTS retailers (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  notes       TEXT,
  created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS licensors (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  notes       TEXT,
  created_at  TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- PHASE 5: Business Context Reference
-- ============================================

-- Workflow stage definitions — maps raw ClickUp status strings to ordered,
-- human-readable pipeline stages so AI and analytics can reason about sequence.
CREATE TABLE IF NOT EXISTS workflow_stages (
  status_raw      TEXT PRIMARY KEY,
  stage_order     INTEGER NOT NULL,
  stage_name      TEXT NOT NULL,
  stage_category  TEXT NOT NULL,   -- Ideation|Concept|Design|Pre-Production|Production|Fulfillment|Complete|Admin
  description     TEXT
);

-- Process checkpoint taxonomy — maps checklist item keywords to ordered steps.
-- Used by build_products_table.py to classify checklist items.
CREATE TABLE IF NOT EXISTS checkpoint_map (
  step_id        TEXT PRIMARY KEY,
  step_name      TEXT NOT NULL,
  step_order     INTEGER NOT NULL,
  step_category  TEXT NOT NULL,
  description    TEXT
);

-- ============================================
-- PHASE 6: Materialized Product Entity
-- ============================================

-- One row per parent task (product). Rebuilt nightly by build_products_table.py.
-- Primary query surface for AI: fully denormalized, indexed, no joins needed.
CREATE TABLE IF NOT EXISTS products (
  id                        TEXT PRIMARY KEY,
  name                      TEXT,
  licensor                  TEXT,
  retailer                  TEXT,
  product_category          TEXT,
  put_up                    TEXT,
  factory                   TEXT,
  buyer                     TEXT,
  task_type                 TEXT,
  customer_program          TEXT,
  sample_req_count          REAL,
  status                    TEXT,
  status_type               TEXT,
  stage_order               INTEGER,
  stage_name                TEXT,
  stage_category            TEXT,
  list_id                   TEXT,
  list_name                 TEXT,
  space_id                  TEXT,
  space_name                TEXT,
  created_at                TEXT,
  updated_at                TEXT,
  closed_at                 TEXT,
  due_date                  TEXT,
  start_date                TEXT,
  days_since_last_update    REAL,    -- days since updated_at (renamed from days_in_current_status)
  days_in_pipeline          REAL,    -- days since created_at
  creator_id                TEXT,
  priority                  TEXT,    -- "urgent" | "high" | "normal" | "low" | NULL
  assignee_count            INTEGER DEFAULT 0,
  assignee_ids              TEXT,    -- JSON array of user ID strings
  subtask_count             INTEGER DEFAULT 0,
  subtask_closed_count      INTEGER DEFAULT 0,
  checklist_item_count      INTEGER DEFAULT 0,
  checklist_resolved_count  INTEGER DEFAULT 0,
  checklist_completion_pct  REAL,
  milestone_concept_approved   INTEGER DEFAULT 0,
  milestone_sample_approved    INTEGER DEFAULT 0,
  milestone_art_complete       INTEGER DEFAULT 0,
  milestone_pi_approved        INTEGER DEFAULT 0,
  milestone_tech_pack_checked  INTEGER DEFAULT 0,
  concept_revisions        INTEGER DEFAULT 0,  -- # of "concept revision submitted" checklist rows
  packaging_revisions      INTEGER DEFAULT 0,  -- # of "packaging concept revision submitted" rows
  sample_rounds            INTEGER DEFAULT 0,  -- # of "sample submitted" checklist rows
  is_overdue               INTEGER DEFAULT 0,  -- 1 if due_date past and product not closed
  days_overdue             REAL,               -- days past due (NULL if not overdue)
  last_subtask_activity    TEXT,    -- updated_at of most recently touched subtask
  last_activity_at         TEXT,    -- max(updated_at, last_subtask_activity)
  is_active                INTEGER DEFAULT 0,  -- 1 if last_activity_at within 180 days
  is_internal              INTEGER DEFAULT 0,  -- 1 for non-product spaces (e.g. designflow)
  comment_approvals        INTEGER DEFAULT 0,  -- comments with approval-language keywords
  comment_revisions        INTEGER DEFAULT 0,  -- comments with revision-request keywords
  comment_rejections       INTEGER DEFAULT 0,  -- comments with rejection keywords
  refreshed_at             TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_products_licensor  ON products(licensor);
CREATE INDEX IF NOT EXISTS idx_products_retailer  ON products(retailer);
CREATE INDEX IF NOT EXISTS idx_products_stage     ON products(stage_order);
CREATE INDEX IF NOT EXISTS idx_products_status    ON products(status_type);
CREATE INDEX IF NOT EXISTS idx_products_space     ON products(space_id);
CREATE INDEX IF NOT EXISTS idx_products_active    ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_internal  ON products(is_internal);
CREATE INDEX IF NOT EXISTS idx_products_overdue   ON products(is_overdue);

-- Checklist items linked back to their parent product with step classification.
-- Rebuilt nightly by build_products_table.py alongside the products table.
CREATE TABLE IF NOT EXISTS product_checkpoints (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id   TEXT NOT NULL,
  checklist_id TEXT NOT NULL,
  item_id      TEXT NOT NULL,
  step_id      TEXT,
  raw_name     TEXT,
  resolved     INTEGER DEFAULT 0,
  resolved_at  TEXT,
  resolved_by  TEXT,
  refreshed_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pchk_product ON product_checkpoints(product_id);
CREATE INDEX IF NOT EXISTS idx_pchk_step    ON product_checkpoints(step_id);

-- ============================================
-- PHASE 7: Analysis Views
-- ============================================

-- Task completion times (requires status_transitions with multiple rows per task)
CREATE VIEW IF NOT EXISTS task_completion_times AS
SELECT
  t.id,
  t.name,
  t.space_id,
  s.to_status,
  s.to_status_type,
  s.transitioned_at,
  LAG(s.transitioned_at) OVER (PARTITION BY t.id ORDER BY s.transitioned_at) AS prev_transition,
  JULIANDAY(s.transitioned_at) - JULIANDAY(
    LAG(s.transitioned_at) OVER (PARTITION BY t.id ORDER BY s.transitioned_at)
  ) AS days_in_prev_status
FROM tasks t
JOIN status_transitions s ON t.id = s.task_id;

-- Workflow efficiency — average time per status transition
CREATE VIEW IF NOT EXISTS workflow_efficiency AS
SELECT
  space_id,
  from_status,
  to_status,
  COUNT(*)  AS transition_count,
  AVG(JULIANDAY(transitioned_at) - JULIANDAY(prev_transition)) AS avg_days,
  AVG(JULIANDAY(transitioned_at) - JULIANDAY(prev_transition)) * 24 AS avg_hours
FROM task_completion_times
WHERE prev_transition IS NOT NULL
GROUP BY space_id, from_status, to_status
ORDER BY avg_days DESC;

-- User activity summary
CREATE VIEW IF NOT EXISTS user_activity AS
SELECT
  u.id,
  u.username,
  COUNT(DISTINCT s.task_id)  AS tasks_transitioned,
  COUNT(s.id)                AS total_transitions,
  COUNT(c.id)                AS comments_made,
  COUNT(a.id)                AS assignments_made
FROM users u
LEFT JOIN status_transitions s ON u.id = s.user_id
LEFT JOIN task_comments c ON u.id = c.user_id
LEFT JOIN task_assignments a ON u.id = a.user_id
GROUP BY u.id;

-- Denormalized task view — one row per task with key dimensions joined.
-- Use task_details for ad-hoc queries; prefer products table for product analysis.
CREATE VIEW IF NOT EXISTS task_details AS
SELECT
  t.id,
  t.name,
  t.list_id,
  l.name                                                           AS list_name,
  t.space_id,
  sp.name                                                          AS space_name,
  t.status,
  ws.stage_order,
  ws.stage_name,
  ws.stage_category,
  t.status_type,
  t.licensor,
  t.parent_task_id,
  CASE WHEN t.parent_task_id IS NOT NULL THEN 1 ELSE 0 END        AS is_subtask,
  t.created_at,
  t.updated_at,
  t.closed_at,
  t.due_date,
  t.start_date,
  t.priority,
  t.creator_id,
  t.workspace_id,
  ROUND((julianday('now') - julianday(t.updated_at)), 1)          AS days_in_current_status,
  MAX(CASE WHEN cf.field_name IN ('🧑‍✈ Customer / Retailer','customer') THEN cf.value_text END) AS retailer,
  MAX(CASE WHEN cf.field_name = '📚 Category'    THEN cf.value_text END) AS product_category,
  MAX(CASE WHEN cf.field_name = 'put-up'         THEN cf.value_text END) AS put_up,
  MAX(CASE WHEN cf.field_name = '🏭 Factory'     THEN cf.value_text END) AS factory,
  MAX(CASE WHEN cf.field_name = '👤 Buyer'       THEN cf.value_text END) AS buyer,
  MAX(CASE WHEN cf.field_name = 'Idea/Task Type' THEN cf.value_text END) AS task_type,
  MAX(CASE WHEN cf.field_name = 'cust program'   THEN cf.value_text END) AS customer_program,
  MAX(CASE WHEN cf.field_name = 'SMPL Req'       THEN cf.value_number END) AS sample_req_count
FROM tasks t
LEFT JOIN workflow_stages ws ON ws.status_raw = t.status
LEFT JOIN lists l             ON l.id = t.list_id
LEFT JOIN spaces sp           ON sp.id = t.space_id
LEFT JOIN task_custom_fields cf ON cf.task_id = t.id
GROUP BY t.id;

-- Pipeline health snapshot — active tasks per stage with age signals.
CREATE VIEW IF NOT EXISTS pipeline_health AS
SELECT
  ws.stage_category,
  ws.stage_order,
  ws.stage_name,
  COUNT(t.id)                                                   AS task_count,
  COUNT(CASE WHEN t.parent_task_id IS NULL THEN 1 END)         AS parent_task_count,
  COUNT(CASE WHEN t.parent_task_id IS NOT NULL THEN 1 END)     AS subtask_count,
  ROUND(AVG(julianday('now') - julianday(t.updated_at)), 1)    AS avg_days_in_stage,
  ROUND(MAX(julianday('now') - julianday(t.updated_at)), 0)    AS max_days_in_stage,
  COUNT(DISTINCT t.licensor)                                    AS distinct_licensors
FROM tasks t
LEFT JOIN workflow_stages ws ON ws.status_raw = t.status
WHERE t.status_type NOT IN ('closed')
GROUP BY ws.stage_category, ws.stage_order, ws.stage_name
ORDER BY ws.stage_order;

-- Licensor activity — per-licensor pipeline summary
CREATE VIEW IF NOT EXISTS licensor_activity AS
SELECT
  t.licensor,
  COUNT(DISTINCT CASE WHEN t.parent_task_id IS NULL THEN t.id END) AS product_count,
  COUNT(DISTINCT CASE WHEN t.parent_task_id IS NULL
        AND t.status_type != 'closed' THEN t.id END)               AS active_product_count,
  COUNT(DISTINCT CASE WHEN t.parent_task_id IS NULL
        AND t.status_type = 'closed' THEN t.id END)                AS closed_product_count,
  COUNT(DISTINCT t.space_id)                                        AS space_count,
  ROUND(AVG(CASE WHEN t.parent_task_id IS NULL AND t.status_type != 'closed'
        THEN julianday('now') - julianday(t.created_at) END), 0)   AS avg_days_in_pipeline,
  COUNT(DISTINCT tc.user_id)                                        AS team_members_involved
FROM tasks t
LEFT JOIN task_comments tc ON tc.task_id = t.id
GROUP BY t.licensor;

-- Stage durations — how long products spend in each stage (from status_transitions)
CREATE VIEW IF NOT EXISTS stage_durations AS
SELECT
  st.space_id,
  ws.stage_name,
  ws.stage_category,
  ws.stage_order,
  COUNT(DISTINCT st.task_id)                                       AS task_count,
  ROUND(AVG(julianday(st.transitioned_at)
    - julianday(LAG(st.transitioned_at) OVER
        (PARTITION BY st.task_id ORDER BY st.transitioned_at))), 1) AS avg_days_in_stage
FROM status_transitions st
LEFT JOIN workflow_stages ws ON ws.status_raw = st.to_status
WHERE st.source = 'api_history'
GROUP BY st.space_id, ws.stage_name, ws.stage_category, ws.stage_order
ORDER BY ws.stage_order;

-- Task effort summary — hours logged per task/product from time_entries
CREATE VIEW IF NOT EXISTS task_effort AS
SELECT
  te.task_id,
  p.name                                      AS product_name,
  p.licensor,
  p.retailer,
  p.stage_name,
  COUNT(te.id)                                AS entry_count,
  COUNT(DISTINCT te.user_id)                  AS contributor_count,
  ROUND(SUM(te.duration_hrs), 2)              AS total_hours,
  ROUND(AVG(te.duration_hrs), 2)              AS avg_hours_per_entry,
  MIN(te.start_time)                          AS first_logged,
  MAX(te.start_time)                          AS last_logged
FROM time_entries te
LEFT JOIN products p ON p.id = te.task_id
GROUP BY te.task_id;

-- Active products overdue summary — quick dashboard query
CREATE VIEW IF NOT EXISTS overdue_products AS
SELECT
  p.id,
  p.name,
  p.licensor,
  p.retailer,
  p.stage_name,
  p.stage_category,
  p.due_date,
  p.days_overdue,
  p.priority,
  p.assignee_ids,
  p.space_name
FROM products p
WHERE p.is_overdue = 1
  AND p.is_internal = 0
  AND p.status_type != 'closed'
ORDER BY p.days_overdue DESC;

-- Comment signal summary — which products have the most implicit process events in comments
CREATE VIEW IF NOT EXISTS comment_signals AS
SELECT
  p.id,
  p.name,
  p.licensor,
  p.stage_name,
  p.comment_approvals,
  p.comment_revisions,
  p.comment_rejections,
  p.comment_approvals + p.comment_revisions + p.comment_rejections AS total_signals
FROM products p
WHERE p.is_internal = 0
  AND (p.comment_approvals > 0 OR p.comment_revisions > 0 OR p.comment_rejections > 0)
ORDER BY total_signals DESC;

-- ============================================
-- VERIFICATION
-- ============================================

SELECT 'Tables:' AS status;
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;

SELECT 'Views:' AS status;
SELECT name FROM sqlite_master WHERE type='view'  ORDER BY name;
