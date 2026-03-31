# CLAUDE.md — plane repo guide

This file is auto-loaded by Claude Code at the start of every session.
Read it fully before touching anything. Keep it up to date as the project evolves.

---

## What this project is

We are building a **custom, self-hosted project management platform** for a home decor product company (POP Creations / Spruce Line). The foundation is the open-source [Plane](https://github.com/makeplane/plane) PM tool, customized to fit how this business actually works — not how a generic PM tool thinks it should work.

The project has two phases:
1. **Learning phase** (current) — Passively observe the team's real behavior in ClickUp over ~14 days. Capture everything. Build a precise picture of workflows, bottlenecks, user patterns, and data models before writing a single line of Plane customization.
2. **Build phase** (after analysis) — Deploy Plane on Coolify, customize it based on observed behavior, and migrate the team off ClickUp.

**GitHub is the source of truth for all code.** Nothing runs from a developer's local machine or from the server directly. Every change goes through this repo.

---

## The business

### Two product divisions

| Division | Type | ClickUp Space | Workflow |
|----------|------|--------------|---------|
| **Spruce Line** | Non-licensed home decor | `Spruce Line` (space id: 2571984) | Design team → buyer approval |
| **POP Creations** | Licensed home decor | `POP Creations` (space id: 4294720) | Design team → **licensor approval** → buyer approval |

**Licensed** means products carry IP from Disney, Warner Bros, Paramount, and similar studios. Every concept, revision, and pre-production sample must go through the licensor's approval process before it can go into production. This is time-consuming, multi-stage, and the dominant source of complexity in how this company works.

**Non-licensed** (Spruce) has no licensor in the loop — the internal design team and the buyer are the only approvers. Much simpler.

### The third space
`designflow` (space id: 90114122073) is the internal dev team's project space. Two developers managing the PLM software project. Entirely separate from the product business.

### The core workflow (POP Creations — Licensing Management list)
This is the main pipeline, with ~11,561 tasks as of the initial snapshot:

```
idea new prod form
  → buyers insight
    → licensor insight
      → concp subm          (concept submitted to licensor)
        → concp apprv        (licensor approved concept)
          → concp apprv comments
            → revisions
              → prepro apprvd    (pre-production approved)
                → prod apprv     (production approved)
                  → sku created
                    → smpl req        (sample requested)
                      → smpl sent lic  (sample sent to licensor)
                        → smpl recvd
                          → smpl revision
                            → design brief
                              → design in prog
                                → design done
                                  → design complete
                                    → ready to submit
                                      → prod creation
                                        → complete
```

This pipeline — especially the licensor approval stages — is what makes this business hard to manage in a generic PM tool. Plane must model this explicitly.

### Key data facts (from March 30, 2026 snapshot)
- **17,746 total tasks** across all spaces
- **11,561 tasks** in Licensing Management alone (the main POP Creations list)
- **64 unique users** actively working in the system
- **96% of tasks have no priority set** — ClickUp's UI buries the priority field. The Plane build must surface it prominently. This is a UI/UX problem, not a data model problem.
- **37% of Licensing Management tasks are subtasks** — deep hierarchies are normal here
- **Time tracking is not used** — don't build around it
- **Custom fields in active use**: SMPL Req (sample request tracking), Revision received, Customer/Retailer, Category, Factory, Buyer, Due Date Licensor

---

## Infrastructure

### Where things run

```
GitHub (u2giants/plane)        ← source of truth, CI/CD
    │
    ├── Cloudflare Worker       ← plane-integrations.u2giants.workers.dev
    │     └── D1 SQLite DB      ← clickup-events (learning phase event log)
    │
    └── Coolify server          ← 178.156.180.212:8000
          ├── Twenty (CRM)      ← already running
          ├── OpenClaw          ← already running
          └── Plane             ← coming in build phase
```

### Cloudflare
- **Account ID**: `8303d11002766bf1cc36bf2f07ba6f20`
- **Worker name**: `plane-integrations`
- **Worker URL**: `https://plane-integrations.u2giants.workers.dev`
- **D1 database**: `clickup-events` (ID: `c37aeb36-e16e-416b-b699-c910f6f8dc10`)
- **workers.dev subdomain**: `u2giants`

### Coolify server
- **URL**: `http://178.156.180.212:8000`
- **Server UUID**: `onwp0kd7w1w74w9yeotnoihp`
- **Worksp directory pattern** (must follow this for every app):
  ```
  /worksp/{appname}/           ← real directory (royal blue)
    {service-name}             ← symlink → /data/coolify/applications/{UUID}/
  ```
  Existing examples:
  - `/worksp/openclaw/ocgate` → `/data/coolify/applications/yxz0hmaien0bgn0sv64g8q3p/`
  - `/worksp/openclaw/ocmc` → `/data/coolify/applications/jihoc2f68xmgi2gfomhhr9g3/`
  - `/worksp/twenty/twenty-server` → `/data/coolify/applications/rd261bt0wy7ifjrkoe1tkl92/`
  - `/worksp/twenty/twenty-worker` → `/data/coolify/applications/pkhhmt4r7n0xt25jmmlkkfi8/`
  - `/worksp/plane/` → exists (empty, symlinks added when apps are created)

### Plane production stack (future — build phase)
Plane requires these services running together:
- PostgreSQL 15 (bundled)
- Valkey/Redis (bundled)
- RabbitMQ (bundled)
- **Cloudflare R2** — replaces bundled MinIO for file storage (no egress fees, S3-compatible)
- Django API (Gunicorn + Uvicorn workers, set `GUNICORN_WORKERS=2` to share server with Twenty/OpenClaw)
- Celery bgworker + beatworker
- Hocuspocus live server (WebSocket)
- React Router frontend
- Admin panel
- Caddy proxy (handled by Coolify)

**Minimum server**: 2 vCPU / 4GB RAM. Current Coolify server is 8 vCPU / 16GB / 240GB — comfortable for all three apps.

---

## Secrets and credentials

**Never commit credentials.** All secrets live in GitHub Actions secrets and Cloudflare Worker secrets. Here's the inventory:

| Secret name | Where stored | What it is |
|-------------|-------------|-----------|
| `CLOUDFLARE_API_TOKEN` | GitHub Actions | CF API token with Workers edit permission |
| `CLICKUP_TOKEN` | GitHub Actions | ClickUp API token (`pk_4384255_...`) |
| `CLICKUP_WORKSPACE_ID` | GitHub Actions | ClickUp workspace/team ID (`2298436`) |
| `CLICKUP_WEBHOOK_SECRET` | GitHub Actions + CF Worker secret | HMAC secret for validating ClickUp webhooks |

---

## Repository structure

```
u2giants/plane/
│
├── CLAUDE.md                          ← you are here — read first, always
│
├── .github/
│   └── workflows/
│       ├── deploy-worker.yml          ← auto-deploys Worker on push to main
│       │                                 (only when integrations/worker/** changes)
│       └── clickup-snapshot.yml       ← manual dispatch — full ClickUp API pull
│                                         run via: gh workflow run clickup-snapshot.yml
│
├── integrations/
│   └── worker/
│       ├── src/
│       │   └── index.js               ← Cloudflare Worker source
│       │                                 receives ClickUp webhooks, validates HMAC,
│       │                                 extracts enriched fields, writes to D1
│       └── wrangler.toml              ← CF config: account, D1 binding, worker name
│
└── scripts/
    ├── clickup_snapshot.py            ← full workspace snapshot script
    │                                     run via GitHub Actions, not locally
    └── analysis/
        └── checkin_YYYY-MM-DD.md     ← periodic analysis reports (generated by scheduled task)
```

---

## The learning phase in detail

### What it captures
A Cloudflare Worker receives every ClickUp webhook event and writes it to D1.

**Webhook events subscribed (22 total):**
taskCreated, taskUpdated, taskDeleted, taskMoved, taskCommentPosted, taskCommentUpdated, taskAssigneeUpdated, taskStatusUpdated, taskTimeEstimateUpdated, taskTimeTrackedUpdated, taskPriorityUpdated, taskDueDateUpdated, taskTagUpdated, listCreated, listUpdated, listDeleted, folderCreated, folderUpdated, folderDeleted, spaceCreated, spaceUpdated, spaceDeleted

**ClickUp webhook registration:**
- Webhook ID: `b114d599-aa9a-4069-b08f-a4bf0ac4fe20`
- HMAC validated on every request (Worker rejects anything with invalid/missing signature)

### D1 schema
```sql
CREATE TABLE events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type   TEXT NOT NULL,           -- e.g. 'taskStatusUpdated'
  task_id      TEXT,                    -- ClickUp task ID
  list_id      TEXT,                    -- list the task lives in
  workspace_id TEXT,                    -- ClickUp workspace ID
  payload      TEXT NOT NULL,           -- full raw JSON from ClickUp (never truncate)
  received_at  TEXT NOT NULL DEFAULT (datetime('now')),
  processed    INTEGER DEFAULT 0,
  -- enriched columns (extracted from history_items[0] by Worker)
  user_id      TEXT,                    -- who made the change
  user_name    TEXT,                    -- display name
  field_changed TEXT,                   -- e.g. 'status', 'priority', 'assignee'
  from_value   TEXT,                    -- previous value
  to_value     TEXT,                    -- new value
  space_id     TEXT                     -- which space (Spruce/POP/designflow)
);
```

Always store the full raw `payload` — never truncate it. Schemas evolve; raw data never lies.

### Snapshot script
Pulls the full structural state of ClickUp at a point in time. Run it:
- On demand via GitHub Actions manual dispatch: `gh workflow run clickup-snapshot.yml`
- Artifacts download from the Actions run page (retained 30 days)

Captures: workspaces, members (via `/seat`), spaces, folders, lists, all tasks (with checklists + dependency graph), custom fields, goals, views, tags, time tracking (last 90 days), comments (sample of 200 most-recently-updated tasks), docs/pages (if available).

### Analysis schedule
Periodic check-ins run as local scheduled tasks:
- **Apr 1, 4pm ET** — first check-in (2 days of data)
- **~Apr 7** — mid-point analysis (7 days)
- **~Apr 14** — final analysis + Plane customization roadmap

Reports saved to `scripts/analysis/checkin_YYYY-MM-DD.md`.

---

## Design decisions and why

### Why Cloudflare D1, not Supabase?
Supabase would work but adds a paid dependency. D1 is free for this volume, Cloudflare MCP lets Claude query it directly in-session, and D1 lives in the same ecosystem as the Worker. No cross-service auth complexity.

### Why not Plane running during learning phase?
Learning phase produces zero Plane code. Deploying Plane before analysis would mean building against assumptions, not evidence.

### Why store full raw JSON payload?
ClickUp's webhook payload structure is undocumented in places and changes. The enriched columns (user_name, from_value, etc.) are conveniences for fast queries, but the raw payload is the ground truth. If enrichment has a bug, we can re-process from raw. Never throw away source data.

### Why R2 instead of bundled MinIO?
Plane's bundled MinIO runs in a container and writes to the Coolify server's disk (240GB, shared). R2 is S3-compatible, has zero egress fees, and removes one container from the stack. The switch is 3 env vars in Plane's config.

### Why GUNICORN_WORKERS=2?
Default is 4+. On a shared server running Twenty + OpenClaw + Plane, leaving all workers at default would OOM. 2 workers handles the expected team size (under 100 users) and leaves headroom for the other services.

### Priority is missing from 96% of tasks
Not a data problem — a ClickUp UI problem. The priority selector is buried in the task detail panel. The Plane build must surface priority in the task list view itself. This is confirmed by the team lead as a known pain point.

---

## Advice for a new developer on this project

1. **Read this file first. Always.** Then query D1 for current event data before forming any opinions about how the team works.

2. **The POP Creations licensor pipeline is the hard part.** Everything else is secondary. Plane's default "status" model can represent it, but the UI needs to make the licensor approval stages visually distinct from internal approval stages.

3. **GitHub → Cloudflare deploy is fully automated.** Push to `main` and the Worker deploys within 30 seconds. Don't manually edit Worker code in the Cloudflare dashboard — it will be overwritten on next push.

4. **The snapshot script is for structural data; webhooks are for behavioral data.** Run the snapshot when you need "what does the workspace look like right now." Query D1 when you need "what did the team actually do."

5. **Don't delete the test event** (event id: 1, event_type: 'test') — it's the pipeline verification record. Filter it with `WHERE event_type != 'test'` in analysis queries.

6. **The Coolify worksp directory pattern is non-negotiable.** Every app must follow `/worksp/{appname}/{service-name}` → symlink to `/data/coolify/applications/{UUID}/`. Check how Twenty and OpenClaw are set up before creating anything new.

7. **When Plane is deployed, disable MinIO.** Remove the `plane-minio` service from the docker-compose and set the three R2 env vars instead. The rest of Plane picks up S3-compatible storage automatically via `django-storages`.

8. **Plane is AGPL-3.0.** Any modifications we distribute (even internally as SaaS to other companies) must be open-sourced. Since this is an internal deployment for one company, that constraint likely doesn't apply — but get confirmation before customizing for external clients.

9. **D1 is eventually consistent at the edge.** Queries via the Cloudflare MCP tool (REST API to D1) always hit the primary, so they're accurate. Don't worry about read replicas for analysis.

10. **The team has 64 users.** When you look at activity, expect a power-law distribution — a handful of people do most of the task updates. That's normal for this type of business.

---

## How to query D1 from a Claude session

The Cloudflare MCP is connected. Use it directly:

```
Tool: mcp__9a4e64b3-8b0d-4708-9ca2-19515b76966e__d1_database_query
database_id: c37aeb36-e16e-416b-b699-c910f6f8dc10
sql: SELECT ...
```

Or via curl if MCP isn't available:
```bash
curl -s -X POST \
  "https://api.cloudflare.com/client/v4/accounts/8303d11002766bf1cc36bf2f07ba6f20/d1/database/c37aeb36-e16e-416b-b699-c910f6f8dc10/query" \
  -H "Authorization: Bearer cfut_qlhKZXlVmVaBTz5RpAPJhj7jRJyRo6v7LeCDDELG62a50c0a" \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT COUNT(*) FROM events"}'
```

---

## Current state (as of 2026-03-31)

- [x] Learning phase infrastructure fully deployed
- [x] Worker live, webhooks flowing, D1 capturing enriched events
- [x] 22 webhook event types subscribed
- [x] Initial snapshot complete (17,746 tasks)
- [x] Enriched snapshot complete (adds members, time tracking, tags, checklists, deps, comments)
- [x] Wednesday Apr 1 4pm check-in scheduled (auto-runs analysis, saves to scripts/analysis/)
- [ ] `/worksp/plane/` created on Coolify ← **DONE** (confirmed March 31)
- [ ] Build phase: clone makeplane/plane, configure R2, deploy on Coolify
- [ ] Plane customization based on analysis findings
