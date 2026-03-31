# plane — POP Creations / Spruce Line PM Platform

Custom self-hosted project management platform built on [Plane](https://github.com/makeplane/plane) (open-source, AGPL-3.0), customized to fit the real workflows of a licensed home decor product company.

**Phase 1 (current): Learning** — passively observing the team's ClickUp behavior for ~14 days before writing any Plane customization.
**Phase 2 (upcoming): Build** — deploy Plane on Coolify, customize based on observed behavior, migrate team off ClickUp.

---

## Table of Contents

1. [The Business](#the-business)
2. [The Core Workflow](#the-core-workflow)
3. [Infrastructure](#infrastructure)
4. [Repository Structure](#repository-structure)
5. [The Learning Phase](#the-learning-phase)
6. [D1 Database Schema](#d1-database-schema)
7. [How to Query Live Event Data](#how-to-query-live-event-data)
8. [Plane Production Stack (Build Phase)](#plane-production-stack-build-phase)
9. [Key Design Decisions](#key-design-decisions)
10. [Developer Guide](#developer-guide)
11. [Secrets and Credentials](#secrets-and-credentials)
12. [Current Status](#current-status)

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

Any PM tool that doesn't model licensor approval stages explicitly will fail for POP Creations.

### designflow
Internal dev team space. Two developers managing the PLM software project. Separate from the product business — different workflow, different users, different cadence.

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
            └─ concp subm            ← concept submitted to licensor
                 └─ concp apprv      ← licensor approved concept
                      ├─ concp apprv comments
                      └─ revisions
                           └─ prepro apprvd     ← pre-production approved
                                └─ prod apprv   ← production approved
                                     └─ sku created
                                          └─ smpl req         ← sample requested
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
    │  source of truth — all code lives here, CI/CD from here
    │
    ├── Cloudflare
    │     ├── Worker: plane-integrations
    │     │     URL: https://plane-integrations.u2giants.workers.dev
    │     │     Receives ClickUp webhooks → validates HMAC → writes to D1
    │     │
    │     ├── D1: clickup-events
    │     │     ID: c37aeb36-e16e-416b-b699-c910f6f8dc10
    │     │     SQLite — stores every ClickUp event during learning phase
    │     │
    │     └── R2: plane-uploads (future)
    │           Replaces Plane's bundled MinIO for file storage
    │
    └── Coolify server: 178.156.180.212:8000
          8 vCPU / 16 GB RAM / 240 GB disk
          ├── Twenty (CRM) — running
          ├── OpenClaw — running
          └── Plane — coming in build phase
```

### Coolify worksp directory convention
Every application on this Coolify server follows the same pattern:
```
/worksp/{appname}/              ← real directory
  {service-name}                ← symlink → /data/coolify/applications/{UUID}/
```

Existing examples:
```
/worksp/openclaw/
  ocgate    → /data/coolify/applications/yxz0hmaien0bgn0sv64g8q3p/
  ocmc      → /data/coolify/applications/jihoc2f68xmgi2gfomhhr9g3/

/worksp/twenty/
  twenty-server → /data/coolify/applications/rd261bt0wy7ifjrkoe1tkl92/
  twenty-worker → /data/coolify/applications/pkhhmt4r7n0xt25jmmlkkfi8/

/worksp/plane/                  ← exists, empty — symlinks added when apps are created
```

**This pattern is mandatory.** Always create the real directory first, then add symlinks as Coolify apps are created. Never put code directly on the server.

---

## Repository Structure

```
u2giants/plane/
│
├── README.md                          ← you are here — universal project guide
├── CLAUDE.md                          ← Claude Code specific additions (MCP tool names, etc.)
├── .gitignore
│
├── .github/
│   └── workflows/
│       ├── deploy-worker.yml          ← auto-deploys Worker on every push to main
│       │                                 (path-filtered: only fires on integrations/worker/**)
│       └── clickup-snapshot.yml       ← manual dispatch — full ClickUp API snapshot
│                                         trigger: gh workflow run clickup-snapshot.yml
│
├── integrations/
│   └── worker/
│       ├── src/
│       │   └── index.js               ← Cloudflare Worker
│       │                                 - POST /clickup/webhook: receives events, validates
│       │                                   HMAC-SHA256, extracts enriched fields, writes to D1
│       │                                 - GET /health: returns {"status":"ok","ts":"..."}
│       └── wrangler.toml              ← Cloudflare config: account ID, D1 binding, worker name
│
└── scripts/
    ├── clickup_snapshot.py            ← full workspace snapshot (run via GH Actions)
    └── analysis/
        └── checkin_YYYY-MM-DD.md     ← periodic behavioral analysis reports
```

---

## The Learning Phase

Before customizing Plane, we need to know exactly how the team works — not how we assume they work. The learning phase captures two types of data:

### 1. Structural snapshot (point-in-time)
Run `gh workflow run clickup-snapshot.yml` to pull the full state of the ClickUp workspace. Captures:
- All workspaces, spaces, folders, lists
- All tasks including subtasks, custom fields, checklists, dependency graph
- Members and roles (via `/team/{id}/seat`)
- Views, tags, goals
- Time tracking history (last 90 days)
- Comments (sample of 200 most-recently-updated tasks)
- Docs/pages (if available on plan tier)

Artifacts download from the GitHub Actions run page and are retained for 30 days.

### 2. Behavioral stream (continuous)
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

**ClickUp webhook registration ID:** `b114d599-aa9a-4069-b08f-a4bf0ac4fe20`
All events are HMAC-SHA256 validated. The Worker rejects any request with a missing or invalid `X-Signature` header.

### Analysis schedule
| Date | What |
|------|------|
| Apr 1, 2026 4pm ET | First check-in — 2 days of data |
| ~Apr 7 | Mid-point — 7 days of data |
| ~Apr 14 | Final analysis + Plane customization roadmap |

Reports are saved to `scripts/analysis/checkin_YYYY-MM-DD.md`.

---

## D1 Database Schema

```sql
CREATE TABLE events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type    TEXT NOT NULL,     -- e.g. 'taskStatusUpdated'
  task_id       TEXT,              -- ClickUp task ID
  list_id       TEXT,              -- ClickUp list ID
  workspace_id  TEXT,              -- ClickUp workspace/team ID
  payload       TEXT NOT NULL,     -- full raw JSON from ClickUp — never truncate this
  received_at   TEXT NOT NULL DEFAULT (datetime('now')),
  processed     INTEGER DEFAULT 0,

  -- enriched columns extracted from history_items[0] by the Worker
  user_id       TEXT,              -- who made the change
  user_name     TEXT,              -- display name
  field_changed TEXT,              -- e.g. 'status', 'priority', 'assignee', 'due_date'
  from_value    TEXT,              -- previous value (JSON-stringified for complex types)
  to_value      TEXT,              -- new value
  space_id      TEXT               -- which space (Spruce Line / POP Creations / designflow)
);

CREATE INDEX idx_event_type  ON events(event_type);
CREATE INDEX idx_task_id     ON events(task_id);
CREATE INDEX idx_received_at ON events(received_at);
```

**Always store the full raw `payload`.** The enriched columns are query conveniences. Raw data is ground truth and allows re-processing if the enrichment logic has bugs.

---

## How to Query Live Event Data

### Via Cloudflare REST API (works from any tool)
```bash
curl -s -X POST \
  "https://api.cloudflare.com/client/v4/accounts/8303d11002766bf1cc36bf2f07ba6f20/d1/database/c37aeb36-e16e-416b-b699-c910f6f8dc10/query" \
  -H "Authorization: Bearer cfut_qlhKZXlVmVaBTz5RpAPJhj7jRJyRo6v7LeCDDELG62a50c0a" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT event_type, COUNT(*) as count FROM events WHERE event_type != '"'"'test'"'"' GROUP BY event_type ORDER BY count DESC"}'
```
Response shape: `{"result": [{"results": [...], "success": true}]}`

### Useful analysis queries

**Events by type:**
```sql
SELECT event_type, COUNT(*) as count
FROM events WHERE event_type != 'test'
GROUP BY event_type ORDER BY count DESC
```

**Status transitions (core workflow):**
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
FROM events WHERE user_name IS NOT NULL AND event_type != 'test'
GROUP BY user_name ORDER BY actions DESC
```

**Activity by hour (received_at is UTC, Eastern = UTC-4 or UTC-5):**
```sql
SELECT CAST(strftime('%H', received_at) AS INTEGER) as hour_utc,
       COUNT(*) as events
FROM events WHERE event_type != 'test'
GROUP BY hour_utc ORDER BY hour_utc
```

**Note:** Filter out the pipeline test event with `WHERE event_type != 'test'` (event id: 1). It exists as a verification record and should not be deleted.

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

**R2 configuration** (3 env vars replace MinIO entirely):
```
AWS_S3_ENDPOINT_URL=https://8303d11002766bf1cc36bf2f07ba6f20.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID={r2_access_key}
AWS_SECRET_ACCESS_KEY={r2_secret_key}
AWS_S3_BUCKET_NAME=plane-uploads
```

Remove the `plane-minio` service from the docker-compose before deploying. Plane uses `django-storages` with boto3 — it picks up S3-compatible config automatically.

---

## Key Design Decisions

### Why Cloudflare (Worker + D1) for learning phase?
- D1 is free at this event volume
- Worker is serverless — zero infra to maintain, globally available instantly
- Both become permanent infrastructure: Worker evolves into the integration hub for Plane ↔ external tools, D1 becomes the audit/integration event log
- Nothing learned in this phase is throwaway

### Why not Supabase?
Plane already bundles PostgreSQL, real-time (Hocuspocus), and auth. Adding Supabase would duplicate all of that at extra cost with no benefit. Cloudflare D1 is sufficient for the event log use case.

### Why store raw webhook payload AND enriched columns?
ClickUp's webhook structure is partially undocumented and changes. The enriched columns (user_name, from_value, to_value, space_id) enable fast SQL analysis. The raw payload is the source of truth. If enrichment has a bug, raw data allows re-processing without losing history.

### Why is priority 96% empty?
ClickUp's UI buries the priority selector inside the task detail panel — it's not visible in list view. The team doesn't use it because they can't easily see or set it. This is a UI problem, not a team culture problem. The Plane build must surface priority directly in task list rows. Confirmed by team lead as a known pain point.

### AGPL-3.0 licensing
Plane is AGPL-3.0. For internal deployments (one company using their own instance), this has no practical impact. If the platform is ever offered as a service to other companies, those customizations must be open-sourced. Get legal confirmation before building any multi-tenant or white-label features on top of Plane.

---

## Developer Guide

### Day one checklist
1. Read this README fully
2. Check current event flow: query D1 for recent events
3. Review the latest analysis report in `scripts/analysis/`
4. Look at `integrations/worker/src/index.js` to understand what's being extracted
5. Check `gh run list --repo u2giants/plane` to see recent CI/CD activity

### Workflow rules
- **All code goes through GitHub.** No direct edits on the Coolify server. No code floating on a developer's laptop that isn't committed.
- **Push to `main` deploys the Worker automatically** — the `deploy-worker.yml` workflow fires whenever `integrations/worker/**` changes.
- **Run the snapshot via GitHub Actions**, not locally: `gh workflow run clickup-snapshot.yml`. This ensures consistent credentials and artifacts are properly stored.
- **Follow the Coolify worksp pattern** (see [Infrastructure](#infrastructure)) for every new application. Check `/worksp/openclaw/` and `/worksp/twenty/` as reference before creating anything new.

### When touching the Worker
- Test your HMAC locally before pushing: compute `HMAC-SHA256(payload, CLICKUP_WEBHOOK_SECRET)` and verify it matches the `X-Signature` header
- The Worker must return `200 ok` quickly — ClickUp will retry failed webhooks and mark the endpoint unhealthy after repeated failures
- Health check: `curl https://plane-integrations.u2giants.workers.dev/health`

### When touching the snapshot script
- The script is designed to run for 7–15 minutes on a large workspace — don't add unbounded loops
- Rate limiting: ClickUp allows 100 req/s on paid plans but the script deliberately sleeps to be polite
- Comments are sampled (top 200 most-recently-updated tasks) — full comment history for 11K+ tasks would require hours and thousands of API calls

### ClickUp API reference
- Base URL: `https://api.clickup.com/api/v2`
- Auth header: `Authorization: pk_4384255_...` (token directly, no "Bearer" prefix)
- Workspace/team ID: `2298436`
- Rate limit: 100 req/s (paid plan). The script respects this with `time.sleep(0.2–0.3)` between calls.

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

The `CLICKUP_WEBHOOK_SECRET` also needs to be set as a Cloudflare Worker secret (done automatically by the deploy workflow via `wrangler secret put`).

---

## Current Status

| Item | Status |
|------|--------|
| GitHub repo (`u2giants/plane`) | Live |
| Cloudflare Worker deployed | Live — `plane-integrations.u2giants.workers.dev` |
| D1 database schema | Live — enriched 9-column schema |
| ClickUp webhooks registered | Live — 22 event types, HMAC validated |
| Initial snapshot (Mar 30) | Complete — 17,746 tasks |
| Enriched snapshot (Mar 31) | Complete — adds members, time tracking, tags, checklists, deps, comments |
| `/worksp/plane/` on Coolify | Created |
| Apr 1 4pm check-in | Scheduled |
| Build phase (Plane on Coolify) | Not started — begins after learning phase analysis |
