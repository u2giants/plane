# plane — POP Creations / Spruce Line PM Platform

Custom self-hosted project management platform built on [Plane](https://github.com/makeplane/plane) (open-source, AGPL-3.0), customized to fit the real workflows of a licensed home decor product company.

**Phase 1 (current): Learning** — passively observing the team's ClickUp behavior for ~14 business days before writing any Plane customization.
**Phase 2 (upcoming): Build** — deploy Plane on Coolify, customize based on observed behavior, migrate team off ClickUp.

---

## Table of Contents

1. [The Business](#the-business)
2. [The Core Workflow](#the-core-workflow)
3. [Infrastructure](#infrastructure)
4. [Repository Structure](#repository-structure)
5. [The Learning Phase](#the-learning-phase)
6. [D1 Database Schema](#d1-database-schema)
7. [Known Data Quality Issues](#known-data-quality-issues)
8. [How Learning Phase Data Becomes Plane Features](#how-learning-phase-data-becomes-plane-features)
9. [How to Query Live Event Data](#how-to-query-live-event-data)
10. [Plane Production Stack (Build Phase)](#plane-production-stack-build-phase)
11. [Key Design Decisions](#key-design-decisions)
12. [Developer Guide — Dos and Don'ts](#developer-guide--dos-and-donts)
13. [Troubleshooting](#troubleshooting)
14. [Secrets and Credentials](#secrets-and-credentials)
15. [Current Status](#current-status)

---

## The Business

This platform serves a home decor product company with two divisions and an internal dev team:

### Spruce Line
Non-licensed home decor products. No outside licensor involved.
**Workflow:** Internal design team → buyer (customer) approval → done.
Simple, fast, low overhead.

### POP Creations
Licensed home decor products carrying IP from studios including Disney, Warner Bros, and Paramount.
**Workflow:** Internal design team → **licensor approval** → buyer approval → done.

The licensor approval process is multi-stage, mandatory at multiple points in the product lifecycle (concept, pre-production, sampling), and the primary source of complexity in this business. Every concept, revision, and pre-production sample must be formally submitted and approved by the licensor before moving forward. This is where work stalls, where follow-ups are required, and where the most process overhead lives.

**Any PM tool that doesn't model licensor approval stages explicitly will fail for POP Creations.**

### designflow
Internal dev team space. Two developers managing the PLM software project. Separate from the product business — different workflow, different users, different cadence.

### Space / Division Reference

| Space | ID | Type | Key Statuses |
|-------|----|------|-------------|
| Spruce Line | `2571984` | Non-licensed products | to do → complete |
| POP Creations | `4294720` | Licensed products (Disney, WB, Paramount) | 20+ licensor pipeline stages |
| designflow | `90114122073` | Internal dev team (private) | backlog → scoping → in design → in development → in review → testing → ready for development → shipped → cancelled |

ClickUp Workspace / Team ID: `2298436`
Webhook registration ID: `b114d599-aa9a-4069-b08f-a4bf0ac4fe20`

### Key numbers (as of March 30, 2026 snapshot)
- 17,746 total tasks across all spaces
- 11,561 tasks in the Licensing Management list alone
- 64 unique users in the system
- 37% of tasks are subtasks (deep hierarchies are normal)
- 96% of tasks have no priority set (UI problem — ClickUp buries the field)
- Time tracking is not used by the team

---

## The Core Workflow

The POP Creations licensing pipeline is the heart of this system. Plane must model it explicitly.

```
idea new prod form
  └─ buyers insight
       └─ licensor insight
            └─ concp subm            <- concept submitted to licensor
                 └─ concp apprv      <- licensor approved concept
                      ├─ concp apprv comments
                      └─ revisions
                           └─ prepro apprvd     <- pre-production approved
                                └─ prod apprv   <- production approved
                                     └─ sku created
                                          └─ smpl req         <- sample requested
                                               └─ smpl sent lic
                                                    └─ smpl recvd
                                                         └─ smpl revision
                                                              └─ design brief
                                                                   └─ design in prog
                                                                        └─ design done
                                                                             └─ design complete
                                                                                  └─ ready to submit
                                                                                       └─ prod creation
                                                                                            └─ complete
```

Spruce Line has a much simpler pipeline: `to do → complete` with minimal intermediate states.

### Custom fields in active use
| Field | Type | Used for |
|-------|------|---------|
| SMPL Req | number | Sample request tracking (2,362 tasks) |
| Revision received | date | When revision came back from licensor |
| Customer / Retailer | dropdown | Which buyer this is for |
| Category | dropdown | Product category |
| Factory | dropdown | Manufacturing source |
| Buyer | text | Buyer name |
| Due Date Licensor | date | Licensor-facing deadline |

---

## Infrastructure

```
GitHub (u2giants/plane)
    |  source of truth -- all code lives here, CI/CD from here
    |
    +-- Cloudflare
    |     +-- Worker: plane-integrations
    |     |     URL: https://plane-integrations.u2giants.workers.dev
    |     |     Receives ClickUp webhooks -> validates HMAC -> writes to D1
    |     |
    |     +-- D1: clickup-events
    |     |     ID: c37aeb36-e16e-416b-b699-c910f6f8dc10
    |     |     SQLite -- stores every ClickUp event during learning phase
    |     |     Tables: events, list_space_map
    |     |
    |     +-- Cloudflare Account ID: 8303d11002766bf1cc36bf2f07ba6f20
    |     |
    |     +-- R2: plane-uploads (future)
    |           Replaces Plane's bundled MinIO for file storage
    |
    +-- Coolify server: 178.156.180.212:8000
          8 vCPU / 16 GB RAM / 240 GB disk
          +-- Twenty (CRM) -- running
          +-- OpenClaw -- running
          +-- Plane -- coming in build phase
```

### Coolify worksp directory convention
Every application on this Coolify server follows the same pattern:
```
/worksp/{appname}/              <- real directory
  {service-name}                <- symlink -> /data/coolify/applications/{UUID}/
```

Existing examples:
```
/worksp/openclaw/
  ocgate    -> /data/coolify/applications/yxz0hmaien0bgn0sv64g8q3p/
  ocmc      -> /data/coolify/applications/jihoc2f68xmgi2gfomhhr9g3/

/worksp/twenty/
  twenty-server -> /data/coolify/applications/rd261bt0wy7ifjrkoe1tkl92/
  twenty-worker -> /data/coolify/applications/pkhhmt4r7n0xt25jmmlkkfi8/

/worksp/plane/                  <- exists, empty -- symlinks added when apps are created
```

**This pattern is mandatory.** Always create the real directory first, then add symlinks as Coolify apps are created. Never put code directly on the server.

---

## Repository Structure

```
u2giants/plane/
|
+-- README.md                          <- you are here -- universal project guide
+-- CLAUDE.md                          <- Claude Code specific additions (MCP tool names, etc.)
+-- .gitignore
|
+-- .github/
|   +-- workflows/
|       +-- deploy-worker.yml          <- auto-deploys Worker on every push to main
|       |                                 (path-filtered: only fires on integrations/worker/**)
|       +-- clickup-snapshot.yml       <- manual dispatch -- full ClickUp API snapshot
|                                         trigger: gh workflow run clickup-snapshot.yml
|
+-- integrations/
|   +-- worker/
|       +-- src/
|       |   +-- index.js               <- Cloudflare Worker
|       |                                 - POST /clickup/webhook: receives events, validates
|       |                                   HMAC-SHA256, extracts enriched fields, writes to D1
|       |                                 - GET /health: returns {"status":"ok","ts":"..."}
|       +-- wrangler.toml              <- Cloudflare config: account ID, D1 binding, worker name
|
+-- scripts/
    +-- clickup_snapshot.py            <- full workspace snapshot (run via GH Actions)
    +-- populate_list_space_map.py     <- one-time: reads snapshot files, prints SQL to
    |                                     populate D1 list_space_map table
    +-- analysis/
        +-- checkin_YYYY-MM-DD.md     <- periodic behavioral analysis reports
```

---

## The Learning Phase

Before customizing Plane, we need to know exactly how the team works — not how we assume they work.

### Why ~14 business days?
The office is closed Apr 2, 3, 8, and 9 — so a calendar window of ~Apr 1–14 gives approximately 10 real business days of team activity. We need enough data to see patterns, not just one-off events.

### Two data sources

#### 1. Structural snapshot (point-in-time)
Run `gh workflow run clickup-snapshot.yml` to pull the full state of the ClickUp workspace. Captures:
- All workspaces, spaces, folders, lists
- All tasks including subtasks, custom fields, checklists, dependency graph
- Members and roles (via `/team/{id}/seat`)
- Views, tags, goals
- Time tracking history (last 90 days)
- Comments (sample of 200 most-recently-updated tasks)
- Docs/pages (if available on plan tier)

Artifacts are stored in GitHub Actions and retained for 30 days.

#### 2. Behavioral stream (continuous)
A Cloudflare Worker receives every ClickUp webhook event in real time. Events are written to D1 immediately. No polling, no batch jobs — everything is event-driven.

**22 webhook event types subscribed:**
```
taskCreated          taskUpdated          taskDeleted
taskMoved            taskCommentPosted    taskCommentUpdated
taskAssigneeUpdated  taskStatusUpdated    taskTimeEstimateUpdated
taskTimeTrackedUpdated  taskPriorityUpdated  taskDueDateUpdated
taskTagUpdated       listCreated          listUpdated
listDeleted          folderCreated        folderUpdated
folderDeleted        spaceCreated         spaceUpdated
spaceDeleted
```

All events are HMAC-SHA256 validated. The Worker rejects any request with a missing or invalid `X-Signature` header.

**Note on duplicate events:** ClickUp fires `taskUpdated` for every change AND the specific event type simultaneously. One status change = 2 rows in D1 (`taskStatusUpdated` + `taskUpdated`). This is expected behavior, not a bug. Use `WHERE event_type != 'taskUpdated'` for unique-action counts.

### Analysis schedule

| Date | What | Purpose |
|------|------|---------|
| Apr 1, 2026 4pm ET | First check-in | 2 days of data — verify capture is working, spot early patterns |
| ~Apr 7 | Mid-point | 7 days of data — status transition map, user activity breakdown, Spruce vs POP comparison |
| ~Apr 14 | Final analysis | Full 10-day picture + Plane customization roadmap — this drives all build decisions |

Reports are saved to `scripts/analysis/checkin_YYYY-MM-DD.md`.

---

## D1 Database Schema

### events table
```sql
CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type    TEXT NOT NULL,     -- e.g. 'taskStatusUpdated'
  task_id       TEXT,              -- ClickUp task ID
  list_id       TEXT,              -- ClickUp list ID (see Known Issues -- currently NULL)
  workspace_id  TEXT,              -- ClickUp team ID (see Known Issues -- currently wrong)
  payload       TEXT NOT NULL,     -- full raw JSON from ClickUp -- NEVER truncate this
  received_at   TEXT NOT NULL DEFAULT (datetime('now')),
  processed     INTEGER DEFAULT 0,

  -- enriched columns extracted from history_items[0] by the Worker
  user_id       TEXT,              -- who made the change
  user_name     TEXT,              -- display name
  field_changed TEXT,              -- e.g. 'status', 'priority', 'assignee', 'due_date'
  from_value    TEXT,              -- previous value (JSON-stringified for complex types)
  to_value      TEXT,              -- new value
  space_id      TEXT               -- which space (see Known Issues -- currently NULL)
);

CREATE INDEX idx_event_type  ON events(event_type);
CREATE INDEX idx_task_id     ON events(task_id);
CREATE INDEX idx_received_at ON events(received_at);
```

**Always store the full raw `payload`.** The enriched columns are query conveniences. Raw data is ground truth and allows re-processing if the enrichment logic has bugs.

### list_space_map table
```sql
CREATE TABLE list_space_map (
  list_id     TEXT PRIMARY KEY,
  list_name   TEXT,
  space_id    TEXT,   -- join to events.list_id to get division context
  space_name  TEXT,   -- 'Spruce Line', 'POP Creations', or 'designflow'
  folder_id   TEXT,
  folder_name TEXT
);
```

ClickUp webhook payloads never include `space_id` directly. To know which division an event came from, you must `JOIN events ON list_space_map`. This table is populated from the snapshot data using `scripts/populate_list_space_map.py`. **As of Apr 1 this table exists but is not yet populated** — see Known Issues.

Division-aware query pattern:
```sql
SELECT m.space_name, e.event_type, COUNT(*) as cnt
FROM events e
LEFT JOIN list_space_map m ON e.list_id = m.list_id
GROUP BY m.space_name, e.event_type
ORDER BY m.space_name, cnt DESC
```

---

## Known Data Quality Issues

Discovered during an Apr 1 audit of live event data. All three are Worker-level bugs pending fix.

| Field | Issue | Root Cause | Fix |
|-------|-------|-----------|-----|
| `events.list_id` | Always NULL | Worker looks for `item.data.list_id` — that path doesn't exist in real payloads. Actual value is at `history_items[0].parent_id` | Change extraction to `item?.parent_id ?? item?.data?.subcategory_id ?? payload.list_id` |
| `events.space_id` | Always NULL | ClickUp webhooks never include `space_id` in the payload. Must be derived from list_id via list_space_map | Populate list_space_map first; space_id will be accessible via JOIN |
| `events.workspace_id` | Stores webhook registration ID (`b114d599-...`), not the team ID | Worker uses `payload.webhook_id` instead of `payload.team_id` | Change to `payload.team_id ?? null` (correct value is `2298436`) |

**Impact:** Until the fix is deployed, all three of these columns are unusable for analysis. The `user_name`, `field_changed`, `from_value`, `to_value`, and `event_type` columns are working correctly. The full raw `payload` column always contains all data and can be used as a fallback.

**Pending fix sequence:**
1. Fix Worker (`integrations/worker/src/index.js`) — correct list_id and workspace_id extraction
2. Deploy via push to `main`
3. Populate `list_space_map` from snapshot data using `scripts/populate_list_space_map.py`
4. Backfill `list_id` on existing rows by re-parsing `json_extract(payload, '$.history_items[0].parent_id')`

### Duplicate events (expected, not a bug)
ClickUp fires `taskUpdated` for every change AND the specific event type. A single status change produces two rows:
- `taskStatusUpdated` with `field_changed='status'`
- `taskUpdated` with `field_changed='status'` (identical content)

**For unique-action analysis:** `WHERE event_type != 'taskUpdated'`
**For total volume/activity:** count all rows (both are valid signals of team activity)

---

## How Learning Phase Data Becomes Plane Features

Every piece of data we capture maps directly to a Plane configuration decision. This is not an academic exercise.

| Data captured | Question it answers | Plane decision it drives |
|--------------|--------------------|-----------------------------|
| Status transitions (from_value → to_value) | Which workflow stages actually get used vs. exist only in theory? | Which custom statuses to create per space in Plane |
| Skipped/unused statuses | What can we eliminate from the pipeline? | Simplified status set — fewer choices = fewer mistakes |
| Active hours (received_at patterns) | When is the team actually working? | Notification scheduling, SLA window definition |
| user_name activity counts | Who are power users vs. occasional users? | Default assignee logic, Plane onboarding priority |
| field_changed distribution | Which fields actually get updated? | Which fields to surface prominently in Plane UI |
| Priority = 96% empty | Is this a culture problem or a UI problem? | Confirmed UI problem — surface priority directly in list row, not buried in task detail panel |
| Spruce vs POP event distribution | Are workflows actually different day-to-day? | Whether to use separate Plane projects or a single project with label-based routing |
| taskCommentPosted frequency | How much communication happens inside tasks? | Whether to configure aggressive comment notifications or keep async |
| taskTimeTrackedUpdated count (expected: 0) | Does the team actually track time? | If 0: don't configure time tracking in Plane — it will be ignored |
| Licensor-stage status transitions | How many approval rounds actually happen in practice? | How many licensor stages to model in Plane (trim theoretical pipeline to actual usage) |
| taskMoved events | Do tasks cross lists/spaces frequently? | Whether to build cross-space task linking in Plane |
| Subtask creation patterns | How deep do hierarchies get? | Plane's subtask depth limit configuration |

---

## How to Query Live Event Data

### Via Cloudflare REST API (works from any tool without MCP)
```bash
curl -s -X POST \
  "https://api.cloudflare.com/client/v4/accounts/8303d11002766bf1cc36bf2f07ba6f20/d1/database/c37aeb36-e16e-416b-b699-c910f6f8dc10/query" \
  -H "Authorization: Bearer cfut_qlhKZXlVmVaBTz5RpAPJhj7jRJyRo6v7LeCDDELG62a50c0a" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT event_type, COUNT(*) as count FROM events WHERE event_type != '\''test'\'' GROUP BY event_type ORDER BY count DESC"}'
```
Response shape: `{"result": [{"results": [...], "success": true}]}`

### Useful analysis queries

**Events by type (unique actions only):**
```sql
SELECT event_type, COUNT(*) as cnt
FROM events
WHERE event_type NOT IN ('test', 'taskUpdated')
GROUP BY event_type ORDER BY cnt DESC
```

**Status transitions (core workflow map):**
```sql
SELECT from_value, to_value, COUNT(*) as transitions
FROM events
WHERE event_type = 'taskStatusUpdated'
  AND from_value IS NOT NULL AND to_value IS NOT NULL
GROUP BY from_value, to_value
ORDER BY transitions DESC LIMIT 30
```

**Most active users:**
```sql
SELECT user_name, COUNT(*) as actions
FROM events
WHERE user_name IS NOT NULL AND event_type NOT IN ('test', 'taskUpdated')
GROUP BY user_name ORDER BY actions DESC
```

**Activity by hour (UTC — Eastern = UTC-4 in summer, UTC-5 in winter):**
```sql
SELECT CAST(strftime('%H', received_at) AS INTEGER) as hour_utc,
       COUNT(*) as events
FROM events WHERE event_type != 'test'
GROUP BY hour_utc ORDER BY hour_utc
```

**Fields that actually get changed:**
```sql
SELECT field_changed, COUNT(*) as cnt
FROM events
WHERE field_changed IS NOT NULL AND event_type != 'test'
GROUP BY field_changed ORDER BY cnt DESC
```

**Division breakdown (requires list_space_map to be populated):**
```sql
SELECT m.space_name, COUNT(*) as events
FROM events e
LEFT JOIN list_space_map m ON e.list_id = m.list_id
WHERE e.event_type NOT IN ('test', 'taskUpdated')
GROUP BY m.space_name
```

**Note:** Filter out the pipeline test event with `WHERE event_type != 'test'` in all analysis queries (event id=1 is a pipeline verification record — do not delete it).

---

## Plane Production Stack (Build Phase)

When learning phase is complete and analysis is done, Plane will be deployed on Coolify. Key decisions already made:

| Component | Decision | Reason |
|-----------|----------|--------|
| File storage | Cloudflare R2 (not bundled MinIO) | No egress fees, removes one container, frees disk |
| PostgreSQL | Bundled (Plane default) | No reason to externalize |
| Redis/Valkey | Bundled (Plane default) | Same |
| RabbitMQ | Bundled (Plane default) | Same |
| Gunicorn workers | Set to 2 (`GUNICORN_WORKERS=2`) | Shared server — prevents OOM with Twenty + OpenClaw |
| Reverse proxy | Coolify-managed Caddy | Automatic SSL, consistent with other apps |

**R2 configuration** (replaces MinIO entirely with 3 env vars):
```
AWS_S3_ENDPOINT_URL=https://8303d11002766bf1cc36bf2f07ba6f20.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID={r2_access_key}
AWS_SECRET_ACCESS_KEY={r2_secret_key}
AWS_S3_BUCKET_NAME=plane-uploads
```

Remove the `plane-minio` service from the docker-compose before deploying. Plane uses `django-storages` with boto3 — it picks up S3-compatible config automatically.

---

## Key Design Decisions

### Why observe first, then build?
PM platforms fail when they're designed around what management thinks the team does, not what the team actually does. 14 days of behavioral data costs almost nothing and makes every Plane customization decision evidence-based rather than guesswork.

### Why Cloudflare (Worker + D1) for learning phase?
- D1 is free at this event volume
- Worker is serverless — zero infrastructure to maintain, globally available instantly
- Both become permanent infrastructure: Worker evolves into the integration hub for Plane and external tools, D1 becomes the audit/integration event log
- Nothing from this phase is throwaway

### Why not Supabase or an external database?
Plane already bundles PostgreSQL, real-time (Hocuspocus), and auth. Adding Supabase would duplicate all of that at extra cost with no benefit. Cloudflare D1 is sufficient for the event log use case.

### Why store raw webhook payload AND enriched columns?
ClickUp's webhook structure is partially undocumented and changes over time. The enriched columns (user_name, from_value, to_value) enable fast SQL analysis without JSON parsing. The raw payload is the source of truth. If enrichment has a bug (and it did — see Known Issues), raw data allows re-processing without losing any history.

### Why is priority 96% empty?
ClickUp's UI buries the priority selector inside the task detail panel — it's not visible in list view. The team doesn't use it because they can't easily see or set it. This is a UI problem, not a team culture problem. The Plane build must surface priority directly in task list rows. Confirmed by team lead as a known pain point.

### AGPL-3.0 licensing
Plane is AGPL-3.0. For internal deployments (one company using their own instance), this has no practical impact. If the platform is ever offered as a service to other companies, those customizations must be open-sourced. Get legal confirmation before building any multi-tenant or white-label features on top of Plane.

---

## Developer Guide — Dos and Don'ts

### Day one checklist
1. Read this README fully
2. Check current event flow: query D1 for recent events
3. Review the latest analysis report in `scripts/analysis/`
4. Look at `integrations/worker/src/index.js` to understand what's being extracted
5. Check `gh run list --repo u2giants/plane` to see recent CI/CD activity
6. Read the Known Issues section above before writing any queries

### DO

- **Always store the full raw `payload`** — enriched columns are conveniences, raw is ground truth
- **Filter `WHERE event_type != 'test'`** in analysis queries (row id=1 is a pipeline verification record)
- **Use LEFT JOIN with list_space_map** for any division-aware query: `JOIN list_space_map m ON e.list_id = m.list_id`
- **Run snapshots via GitHub Actions** (`gh workflow run clickup-snapshot.yml`) — ensures consistent credentials and artifacts are properly stored
- **Push to `main` to deploy the Worker** — the `deploy-worker.yml` workflow fires automatically; don't deploy via wrangler CLI locally
- **Verify Worker after every deploy:** `curl https://plane-integrations.u2giants.workers.dev/health`
- **Follow the Coolify worksp pattern** for every new application (check `/worksp/openclaw/` as reference)
- **Return `200 ok` quickly from the Worker** — ClickUp will retry failed webhooks and mark the endpoint unhealthy after repeated failures

### DON'T

- **Don't delete the test event (id=1)** — it exists as a pipeline verification record
- **Don't trust `list_id` or `space_id` columns** until the Worker fix is deployed — both are currently NULL for all rows
- **Don't trust `workspace_id`** — it currently stores the webhook registration ID (`b114d599-...`), not the team ID (`2298436`)
- **Don't count `taskUpdated` as unique actions** — it double-fires alongside every specific event type; use `WHERE event_type != 'taskUpdated'` for action counts
- **Don't edit code directly on the Coolify server** — GitHub is the source of truth, always
- **Don't run the snapshot locally against production** — use GitHub Actions; local runs don't store artifacts and use developer-local credentials
- **Don't add time tracking in Plane at launch** — the team doesn't use it (zero time tracking events in ClickUp data); it will be ignored
- **Don't add priority enforcement in Plane at launch** — fix the UI visibility first; enforcement without visibility creates frustration
- **Don't assume ClickUp webhook payloads are complete** — many fields aren't present; always verify against the raw `payload` column before concluding a field doesn't exist
- **Don't deploy Plane** until the three Worker bugs are fixed and list_space_map is populated — you won't be able to run meaningful division-level analysis otherwise

### When touching the Worker
- The `list_id` fix must use `history_items[0].parent_id` — not `item.data.list_id` (doesn't exist)
- Test HMAC locally before pushing: compute `HMAC-SHA256(payload, secret)` and verify it matches `X-Signature`
- The Worker must respond `200 ok` quickly — ClickUp marks endpoints unhealthy after repeated failures

### When touching the snapshot script
- The script is designed to run 7–15 minutes on a large workspace — don't add unbounded loops
- Rate limiting: ClickUp allows 100 req/s on paid plans; the script deliberately sleeps to be polite
- Comments are sampled (top 200 most-recently-updated tasks) — full comment history for 11K+ tasks would require hours and thousands of API calls

### ClickUp API reference
- Base URL: `https://api.clickup.com/api/v2`
- Auth header: `Authorization: pk_4384255_...` (token directly — no "Bearer" prefix)
- Workspace/Team ID: `2298436`
- Rate limit: 100 req/s (paid plan). The script respects this with `time.sleep(0.2–0.3)` between calls.

---

## Troubleshooting

**"Cloudflare dashboard shows 40+ requests but D1 has fewer events"**
Some requests are rejected before writing to D1 (HMAC validation failure, malformed JSON). The gap is normal. Rejected requests are logged via `console.warn` in the Worker — check Cloudflare Worker logs for details.

**"space_id is NULL for all events"**
Known issue. ClickUp webhooks don't include space_id in the payload. Needs: (1) Worker fix to correctly populate list_id, (2) list_space_map populated from snapshot. Then use JOIN instead of the space_id column directly.

**"list_id is NULL for all events"**
Known Worker bug. The extraction path `item.data.list_id` doesn't exist. Real value is `history_items[0].parent_id`. Pending fix.

**"workspace_id column has a UUID that looks like a webhook ID, not a team ID"**
Known Worker bug. Currently stores `payload.webhook_id` (the webhook registration ID) instead of `payload.team_id`. The correct team ID is `2298436`. Pending fix.

**"taskUpdated events dominate the event count"**
Expected behavior. ClickUp fires `taskUpdated` for every change type AND fires the specific event (e.g., `taskStatusUpdated`). Filter with `WHERE event_type != 'taskUpdated'` for unique-action analysis.

**"Workers onboarding URL returns 404"**
The `/workers/onboarding` URL is deprecated. Navigate to Workers & Pages in the Cloudflare dashboard sidebar. Correct Worker URL: `https://dash.cloudflare.com/8303d11002766bf1cc36bf2f07ba6f20/workers/services/view/plane-integrations/production`

**"Coolify terminal is inaccessible via automation"**
Coolify's UI uses Livewire which blocks standard JS automation. Use the Coolify REST API directly (`curl http://178.156.180.212:8000/api/v1/...`) for everything possible. For commands that truly require a terminal, ask the user to run them manually — they take seconds.

---

## Secrets and Credentials

**Nothing sensitive is committed to this repo.** All secrets live in GitHub Actions and Cloudflare.

| Secret | Stored in | Purpose |
|--------|-----------|---------|
| `CLOUDFLARE_API_TOKEN` | GitHub Actions secrets | Deploys Worker via Wrangler |
| `CLICKUP_TOKEN` | GitHub Actions secrets | ClickUp API access for snapshots |
| `CLICKUP_WORKSPACE_ID` | GitHub Actions secrets | ClickUp workspace ID (`2298436`) |
| `CLICKUP_WEBHOOK_SECRET` | GitHub Actions secrets + CF Worker secret | HMAC validation of incoming webhooks |

To add or rotate a secret:
```bash
gh secret set SECRET_NAME --repo u2giants/plane --body "value"
```

The `CLICKUP_WEBHOOK_SECRET` also needs to be set as a Cloudflare Worker secret. This is done automatically by the `deploy-worker.yml` workflow on every deploy via `wrangler secret put`.

---

## Current Status

| Item | Status |
|------|--------|
| GitHub repo (`u2giants/plane`) | ✅ Live |
| Cloudflare Worker | ✅ Live — `plane-integrations.u2giants.workers.dev` |
| Worker bugs | ✅ **FIXED** — list_id, workspace_id, HMAC security |
| D1 schema (legacy) | ✅ Live — events table |
| D1 schema (robust) | ✅ **CREATED** — 15 new tables + views |
| D1 migration | ✅ **COMPLETED** via GitHub Actions |
| ClickUp webhook | ✅ **CONFIGURED** — pointing to Worker with HMAC validation |
| list_space_map | ⚠️ **NEEDS POPULATION** — SQL ready in scripts/ |
| Initial snapshot (Mar 30) | ✅ Complete — 17,746 tasks |
| Enriched snapshot (Mar 31) | ✅ Complete — members, time, tags, checklists, deps, comments |
| `/worksp/plane/` on Coolify | ✅ Ready — empty, for build phase |
| Build phase (Plane on Coolify) | ⏳ Not started — begins after final analysis |
