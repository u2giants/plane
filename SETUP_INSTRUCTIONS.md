# Setup Instructions for ClickUp Data Capture

## 1. Add Missing Webhook Subscriptions in ClickUp

Go to ClickUp Dashboard and add these webhook events:

1. Go to https://app.clickup.com
2. Click your avatar → **Integrations**
3. Find **Webhooks** → **Manage**
4. Edit the existing webhook (or create new one)
5. Add these event types:
   - `taskAttachmentUpdated`
   - `taskChecklistItemCompleted`
   - `taskChecklistItemDeleted`
   - `taskLinkedTasksUpdated`
   - `taskDependencyUpdated`

**Webhook URL:** `https://plane-integrations.u2giants.workers.dev/clickup/webhook`

---

## 2. Create Cloudflare API Token with D1 Permissions

1. Go to https://dash.cloudflare.com/
2. Click **My Profile** → **API Tokens**
3. Click **Create Token** → **Create Custom Token**
4. Name: `Plane D1 Access`
5. Account permissions:
   - **Account** → **D1** → **Edit**
6. Click **Create Token**
7. Copy the new token

Then update `scripts/query_d1.py` with the new token:
```python
API_TOKEN = "your_new_token_here"
```

---

## 3. Execute list_space_map.sql Against D1

Once you have a D1-enabled API token:

```bash
# Option A: Use wrangler CLI
wrangler d1 execute clickup-events --command="$(cat list_space_map.sql)"

# Option B: Use the API directly
# Update query_d1.py and run:
python scripts/query_d1.py
```

Or execute via Cloudflare Dashboard:
1. Go to D1 → clickup-events → Query
2. Paste the contents of `list_space_map.sql`
3. Execute

---

## 4. Run New Snapshot

The snapshot was triggered via GitHub Actions. Check status:
```bash
gh run list --repo u2giants/plane --limit 3
```

Download results when complete:
```bash
gh run download latest --repo u2giants/plane --name "clickup-snapshot-*"
```

---

## 5. Update Worker for New Webhook Events

Once webhook subscriptions are added in ClickUp, the Worker will automatically capture:
- `taskAttachmentUpdated` - File events
- `taskChecklistItemCompleted` - Checklist progress
- `taskChecklistItemDeleted` - Checklist changes
- `taskLinkedTasksUpdated` - Linked task changes

No code changes needed - the Worker already captures any webhook event.
