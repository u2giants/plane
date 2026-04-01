# ClickUp Webhook Setup Guide

## Add Missing Webhook Subscriptions

ClickUp does NOT have a webhook management API. You must do this in the ClickUp Dashboard.

### Step-by-Step Instructions

1. **Open ClickUp Dashboard**
   - Go to: https://app.clickup.com

2. **Navigate to Integrations**
   - Click your **avatar/profile picture** (top right)
   - Select **Integrations** from the dropdown

3. **Find Webhooks**
   - Under "Integrations", find and click **Webhooks**
   - Click **Manage**

4. **Edit Existing Webhook**
   - Find the webhook pointing to: `https://plane-integrations.u2giants.workers.dev/clickup/webhook`
   - Click **Edit** (the pencil icon)

5. **Add These Event Types**
   
   Check ALL of these events:
   ```
   ✅ taskCreated
   ✅ taskUpdated
   ✅ taskDeleted
   ✅ taskMoved
   ✅ taskCommentPosted
   ✅ taskCommentUpdated
   ✅ taskAssigneeUpdated
   ✅ taskStatusUpdated
   ✅ taskTimeEstimateUpdated
   ✅ taskTimeTrackedUpdated
   ✅ taskPriorityUpdated
   ✅ taskDueDateUpdated
   ✅ taskTagUpdated
   ✅ taskAttachmentUpdated      ← ADD THIS
   ✅ taskChecklistItemCompleted ← ADD THIS
   ✅ taskChecklistItemDeleted   ← ADD THIS
   ✅ taskLinkedTasksUpdated      ← ADD THIS
   ✅ listCreated
   ✅ listUpdated
   ✅ listDeleted
   ✅ folderCreated
   ✅ folderUpdated
   ✅ folderDeleted
   ✅ spaceCreated
   ✅ spaceUpdated
   ✅ spaceDeleted
   ```

6. **Save**
   - Click **Save** or **Update**

## Why These 4 Events?

These events are currently NOT subscribed but are critical:

| Event | Why It Matters |
|-------|----------------|
| `taskAttachmentUpdated` | Track file uploads/downloads |
| `taskChecklistItemCompleted` | Progress tracking |
| `taskChecklistItemDeleted` | Checklist changes |
| `taskLinkedTasksUpdated` | Dependencies/relationships |

## Verify Webhook is Active

After adding events:
1. Create a test task
2. Check D1 for a new event: `SELECT * FROM events ORDER BY received_at DESC LIMIT 5`

## If No Webhook Exists

If you don't see an existing webhook:
1. Click **Create Webhook**
2. Enter: `https://plane-integrations.u2giants.workers.dev/clickup/webhook`
3. Add all the events listed above
4. Copy the webhook secret and update it in GitHub secrets

## Troubleshooting

**"Webhook URL is invalid"**
- Ensure you're using: `https://plane-integrations.u2giants.workers.dev/clickup/webhook`

**"Signature mismatch"**
- The webhook secret must match `CLICKUP_WEBHOOK_SECRET` in GitHub secrets
- Check Cloudflare Worker logs if signature issues persist

**"No events received"**
- Check Worker health: `curl https://plane-integrations.u2giants.workers.dev/health`
- Check D1 events: Use query_d1.py or Cloudflare Dashboard
