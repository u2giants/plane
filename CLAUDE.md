# CLAUDE.md — Claude Code specific additions

**Read README.md first.** This file only covers things specific to Claude Code sessions.

---

## MCP tools available in this project

### Cloudflare MCP
Query D1, manage Workers, R2, D1 databases directly:
```
mcp__9a4e64b3-8b0d-4708-9ca2-19515b76966e__d1_database_query
  database_id: c37aeb36-e16e-416b-b699-c910f6f8dc10
  sql: SELECT ...

mcp__9a4e64b3-8b0d-4708-9ca2-19515b76966e__workers_list
mcp__9a4e64b3-8b0d-4708-9ca2-19515b76966e__r2_buckets_list
```

### Coolify API (via Bash/curl)
No MCP — use the REST API directly:
```bash
curl -s "http://178.156.180.212:8000/api/v1/applications" \
  -H "Authorization: Bearer 1|mlVx9mbwsN1Sga6eLtJEvmPioy6Sra9AnepnCe3K7d0a2927"
```
Server UUID: `onwp0kd7w1w74w9yeotnoihp`

### GitHub CLI
Already authenticated as `u2giants`. Common commands:
```bash
gh workflow run deploy-worker.yml --repo u2giants/plane
gh workflow run clickup-snapshot.yml --repo u2giants/plane -f include_closed=true
gh run list --repo u2giants/plane --limit 5
gh secret set SECRET_NAME --repo u2giants/plane --body "value"
```

### Browser automation
Chrome MCP (`mcp__Claude_in_Chrome__*`) and Playwright (`mcp__playwright__*`) are both available.
Chrome MCP is more reliable for authenticated sessions (carries the user's browser cookies).
Playwright is better for headless/programmatic flows.

---

## Scheduled tasks

The Wednesday Apr 1 4pm check-in is configured as a local scheduled task:
- Task ID: `clickup-learning-checkin-apr1`
- Fires once at 2026-04-01T16:00:00-04:00, then auto-disables
- Queries D1, runs 9 analysis queries, saves report to `scripts/analysis/checkin_2026-04-01.md`
- Manage at: Claude Code sidebar → Scheduled section

To create future check-ins, use `mcp__scheduled-tasks__create_scheduled_task`.

---

## Memory files

Project memory is stored at:
`C:\Users\ahazan2\.claude\projects\D--Plane\memory\`

Write new memories there as the project evolves (user preferences, key decisions, lessons learned).
