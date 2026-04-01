# ClickUp Data Gaps and Fixes (Apr 1, 2026)

## Bugs Fixed

### Worker Bugs (Apr 1, 2026)

1. **list_id extraction** - Fixed in `integrations/worker/src/index.js`
   - Was: `item?.data?.list_id` (path doesn't exist)
   - Now: `item?.parent_id ?? item?.data?.subcategory_id ?? payload.list_id`
   - ClickUp stores list_id in `history_items[0].parent_id`

2. **workspace_id extraction** - Fixed in `integrations/worker/src/index.js`
   - Was: `String(payload.webhook_id ?? '')` (stores registration UUID)
   - Now: `payload.team_id ? String(payload.team_id) : null` (correct: 2298436)

3. **space_id** - Remains NULL as ClickUp doesn't send it directly
   - Must be derived via JOIN on `list_space_map` table
   - See "Populating list_space_map" below

### Snapshot Script Bugs

4. **Dependencies extraction** - Fixed in `scripts/clickup_snapshot.py`
   - Was: Extracting from `task.dependencies` (always empty)
   - Now: Extracts from `task.linked_tasks` (ClickUp's actual relationship field)
   - Found 495 linked task relationships in snapshot data

## Data Gaps Identified

### Missing from Snapshot

| Gap | Impact | Fix Needed |
|-----|--------|------------|
| Custom field DEFINITIONS at list level | Only 2/13 fields captured at workspace level | Fetch `/list/{id}/field` per list |
| Linked tasks (495 found) | Not captured in ALL_dependencies | ✅ Fixed - now in ALL_linked_tasks |
| Members API null | Can't map user activity | Try `/team/{id}/member` endpoint |
| Time tracking 0 entries | Despite being enabled | Check ClickUp plan tier |

### Missing Webhook Subscriptions

Add these in ClickUp dashboard to capture more behavioral data:

- `taskAttachmentUpdated` - Attachment events
- `taskChecklistItemCompleted` - Checklist progress tracking
- `taskChecklistItemDeleted` - Checklist changes
- `taskDependencyUpdated` - Dependency changes (if used)
- `taskLinkedTasksUpdated` - Linked task relationship changes

## Custom Fields in Tasks (13 total)

Found in task payloads (not in workspace-level `/team/{id}/field`):

| Field Name | Type | Frequency |
|------------|------|-----------|
| DATE FCTRY SELECTED | date | 100% |
| DATE TLR | date | 100% |
| Idea/Task Type | labels | 100% |
| Next Review Date | date | 100% |
| SAS-PO | date | 100% |
| SMPL Req | number | 100% |
| 🏭 Factory | drop_down | 100% |
| 📚 Category | drop_down | 100% |
| 🧑‍✈ Customer / Retailer | drop_down | 100% |
| Due Date Licensor | date | 100% |
| 👤 Buyer | labels | 100% |
| Revision received | date | 40% |
| Old Statuses | drop_down | 29% |

## Populating list_space_map

Run the SQL in `list_space_map.sql` against D1 to enable division-level analysis:

```bash
# The SQL has been generated and saved to list_space_map.sql
# Execute it via Cloudflare dashboard or API once you have D1 permissions
```

This enables queries like:
```sql
SELECT m.space_name, e.event_type, COUNT(*) as cnt
FROM events e
LEFT JOIN list_space_map m ON e.list_id = m.list_id
GROUP BY m.space_name, e.event_type
```

## ClickUp API Endpoints Not Being Pulled

Consider adding to snapshot script:

1. `/list/{list_id}/field` - List-specific custom field definitions
2. `/task/{id}/linked_tasks` - Full linked task data (now captured in tasks)
3. `/task/{id}/attachments` - Direct task attachments
4. `/team/{id}/guest` - External collaborators/guests

## Verification Steps

After fixes are deployed:
1. Wait for new webhook events to arrive in D1
2. Verify `list_id` is populated: `SELECT COUNT(*) as populated FROM events WHERE list_id IS NOT NULL`
3. Verify `workspace_id` = 2298436: `SELECT DISTINCT workspace_id FROM events`
4. Run division analysis with populated `list_space_map`
