// integrations/worker/src/index.js
// Cloudflare Worker — ClickUp webhook receiver
// Writes to D1: events (primary), plus specialized tables per event type.

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const KNOWN_LICENSORS = [
  'Disney', 'Marvel', 'Warner Bros', 'WB', 'Paramount', 'SEGA',
  'Universal', 'Nickelodeon', 'DreamWorks', 'Hasbro', 'Mattel',
];

// Goal / key-result event types that only write to `events`
const GOAL_EVENT_TYPES = new Set([
  'goalCreated', 'goalUpdated', 'goalDeleted',
  'keyResultCreated', 'keyResultUpdated', 'keyResultDeleted',
]);

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/health') {
      return new Response(JSON.stringify({ status: 'ok', ts: new Date().toISOString() }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname === '/clickup/webhook' && request.method === 'POST') {
      return handleClickUpWebhook(request, env);
    }

    return new Response('not found', { status: 404 });
  },
};

// ---------------------------------------------------------------------------
// Main webhook handler
// ---------------------------------------------------------------------------

async function handleClickUpWebhook(request, env) {
  let body;
  try {
    body = await request.text();
  } catch (err) {
    console.error('Failed to read request body:', err.message);
    return new Response('bad request', { status: 400 });
  }

  // HMAC validation
  const signature = request.headers.get('x-signature') || request.headers.get('X-Signature') || '';
  const secret = env.CLICKUP_WEBHOOK_SECRET || '';
  if (secret) {
    const valid = await verifyHmac(body, signature, secret);
    if (!valid) {
      console.error('HMAC validation failed');
      return new Response('unauthorized', { status: 401 });
    }
  }

  let payload;
  try {
    payload = JSON.parse(body);
  } catch (err) {
    console.error('Failed to parse JSON payload:', err.message);
    return new Response('bad request', { status: 400 });
  }

  // -------------------------------------------------------------------------
  // Extract common fields
  // -------------------------------------------------------------------------
  const eventType = payload.event || '';
  const historyItems = Array.isArray(payload.history_items) ? payload.history_items : [];
  const item = historyItems[0] || {};

  const workspaceId = payload.team_id ? String(payload.team_id) : null;
  const taskId = payload.task_id ? String(payload.task_id) : null;
  const listId = item.parent_id ? String(item.parent_id) : null;
  const spaceId = null; // not directly in webhook envelope; may be enriched later

  const userId = item.user
    ? String(item.user.id || '')
    : (payload.user_id ? String(payload.user_id) : null);
  const userName = item.user
    ? (item.user.username || item.user.email || null)
    : null;

  const fieldChanged = item.field || null;
  const fromValue = item.before != null
    ? (typeof item.before === 'object' ? (item.before.status || JSON.stringify(item.before)) : String(item.before))
    : null;
  const toValue = item.after != null
    ? (typeof item.after === 'object' ? (item.after.status || JSON.stringify(item.after)) : String(item.after))
    : null;

  // -------------------------------------------------------------------------
  // Primary write: events table (must succeed for 200 response)
  // -------------------------------------------------------------------------
  try {
    await env.DB.prepare(`
      INSERT INTO events
        (event_type, task_id, list_id, workspace_id, payload, user_id, user_name,
         field_changed, from_value, to_value, space_id)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      eventType,
      taskId,
      listId,
      workspaceId,
      body,
      userId,
      userName,
      fieldChanged,
      fromValue,
      toValue,
      spaceId,
    ).run();
  } catch (err) {
    console.error('events table write failed:', err.message);
    return new Response('internal error', { status: 500 });
  }

  // -------------------------------------------------------------------------
  // Secondary writes — best-effort, errors are logged but never propagated
  // -------------------------------------------------------------------------

  if (eventType === 'taskStatusUpdated') {
    try {
      await writeStatusTransition(env.DB, {
        taskId,
        fromValue,
        toValue,
        item,
        userId,
        userName,
        listId,
        spaceId,
        workspaceId,
      });
    } catch (err) {
      console.error('status_transitions write failed:', err.message);
    }
  }

  if (eventType === 'taskAssigneeUpdated') {
    try {
      await writeTaskAssignment(env.DB, {
        taskId,
        fieldChanged,
        item,
        userId,
      });
    } catch (err) {
      console.error('task_assignments write failed:', err.message);
    }
  }

  if (eventType === 'taskCommentPosted') {
    try {
      await writeTaskComment(env.DB, {
        taskId,
        item,
        payload,
        userId,
        userName,
      });
    } catch (err) {
      console.error('task_comments write failed:', err.message);
    }
  }

  if (eventType === 'taskCreated') {
    try {
      await writeTaskStub(env.DB, {
        taskId,
        listId,
        workspaceId,
        spaceId,
        toValue,  // status from after value
        userId,
      });
    } catch (err) {
      console.error('tasks stub write failed:', err.message);
    }
  }

  if (eventType === 'taskCustomFieldUpdated') {
    try {
      await writeCustomFieldChange(env.DB, {
        taskId,
        item,
      });
    } catch (err) {
      console.error('task_custom_fields write failed:', err.message);
    }
  }

  // Goal / key-result events: already written to events above; no further action needed.
  // GOAL_EVENT_TYPES is checked implicitly — these events skip all the blocks above.

  return new Response('ok', { status: 200 });
}

// ---------------------------------------------------------------------------
// Specialized table writers
// ---------------------------------------------------------------------------

// 1. status_transitions
async function writeStatusTransition(db, { taskId, fromValue, toValue, item, userId, userName, listId, spaceId, workspaceId }) {
  const fromStatusType = item.before && typeof item.before === 'object' ? (item.before.type || null) : null;
  const toStatusType   = item.after  && typeof item.after  === 'object' ? (item.after.type  || null) : null;

  await db.prepare(`
    INSERT INTO status_transitions
      (task_id, from_status, to_status, from_status_type, to_status_type,
       user_id, user_name, list_id, space_id, workspace_id, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'webhook')
  `).bind(
    taskId,
    fromValue,
    toValue,
    fromStatusType,
    toStatusType,
    userId,
    userName,
    listId,
    spaceId,
    workspaceId,
  ).run();
}

// 2. task_assignments
async function writeTaskAssignment(db, { taskId, fieldChanged, item, userId }) {
  const isAdd = fieldChanged === 'assignee_add';
  // The assigned user comes from item.after (add) or item.before (remove)
  const assigneeObj = isAdd
    ? (item.after  && typeof item.after  === 'object' ? item.after  : null)
    : (item.before && typeof item.before === 'object' ? item.before : null);

  const assigneeId = assigneeObj
    ? String(assigneeObj.id || assigneeObj.user_id || '')
    : null;

  if (isAdd) {
    await db.prepare(`
      INSERT INTO task_assignments
        (task_id, user_id, assigned_by, is_current, source)
      VALUES (?, ?, ?, 1, 'webhook')
    `).bind(taskId, assigneeId, userId).run();
  } else {
    await db.prepare(`
      INSERT INTO task_assignments
        (task_id, user_id, assigned_by, is_current, unassigned_at, source)
      VALUES (?, ?, ?, 0, datetime('now'), 'webhook')
    `).bind(taskId, assigneeId, userId).run();
  }
}

// 3. task_comments
async function writeTaskComment(db, { taskId, item, payload, userId, userName }) {
  const historyItems = Array.isArray(payload.history_items) ? payload.history_items : [];
  const commentObj = historyItems[0] && historyItems[0].comment ? historyItems[0].comment : null;

  if (!commentObj) {
    console.warn('taskCommentPosted: no comment object found in history_items[0]');
    return;
  }

  const commentId   = commentObj.id ? String(commentObj.id) : null;
  const textContent = commentObj.text_content || null;
  const dateMs      = commentObj.date ? Number(commentObj.date) : null;
  const createdAt   = dateMs && !isNaN(dateMs) ? new Date(dateMs).toISOString() : null;

  const commentParts = Array.isArray(commentObj.comment) ? commentObj.comment : [];
  const mentionCount    = textContent ? (textContent.match(/@/g) || []).length : 0;
  const attachmentCount = commentParts.filter(p => p && p.type === 'attachment').length;

  const filePaths    = extractFilePaths(textContent);
  const licensorHint = extractLicensorFromPaths(filePaths);

  if (!commentId) {
    console.warn('taskCommentPosted: comment has no id, skipping task_comments write');
    return;
  }

  await db.prepare(`
    INSERT OR REPLACE INTO task_comments
      (id, task_id, user_id, user_name, content, mention_count, attachment_count,
       created_at, file_paths, licensor_hint, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'webhook')
  `).bind(
    commentId,
    taskId,
    userId,
    userName,
    textContent,
    mentionCount,
    attachmentCount,
    createdAt,
    filePaths.length > 0 ? JSON.stringify(filePaths) : null,
    licensorHint,
  ).run();
}

// 4. tasks stub
async function writeTaskStub(db, { taskId, listId, workspaceId, spaceId, toValue, userId }) {
  if (!taskId) return;

  await db.prepare(`
    INSERT OR IGNORE INTO tasks
      (id, list_id, workspace_id, space_id, status, creator_id)
    VALUES (?, ?, ?, ?, ?, ?)
  `).bind(
    taskId,
    listId,
    workspaceId,
    spaceId,
    toValue,  // status string from the after field
    userId,
  ).run();
}

// 5. custom field update
async function writeCustomFieldChange(db, { taskId, item }) {
  if (!taskId) return;

  const fieldId   = item.field_id ? String(item.field_id) : null;
  const fieldName = item.field || fieldId;
  if (!fieldId || !fieldName) return;

  const after = item.after;
  let valueText    = null;
  let valueNumber  = null;
  let valueDate    = null;
  let valueBoolean = null;

  if (after === null || after === undefined) {
    // field cleared — write nulls
  } else if (typeof after === 'number') {
    valueNumber = after;
  } else if (typeof after === 'boolean') {
    valueBoolean = after ? 1 : 0;
  } else if (typeof after === 'object') {
    // dropdown option: {id, name, color, ...}
    valueText = after.name || after.value || JSON.stringify(after);
  } else {
    const s = String(after);
    // ISO date-like strings
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
      valueDate = s;
    } else if (!isNaN(Number(s)) && s.trim() !== '') {
      valueNumber = Number(s);
    } else {
      valueText = s;
    }
  }

  await db.prepare(`
    INSERT OR REPLACE INTO task_custom_fields
      (task_id, field_id, field_name, value_text, value_number, value_date, value_boolean, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
  `).bind(
    taskId,
    fieldId,
    fieldName,
    valueText,
    valueNumber,
    valueDate,
    valueBoolean,
  ).run();
}

// ---------------------------------------------------------------------------
// File path / licensor helpers
// ---------------------------------------------------------------------------

function extractFilePaths(text) {
  if (!text) return [];
  return (text.match(/[A-Z]:[\\\/][^\n,"]{5,}/g) || []).slice(0, 10);
}

function extractLicensorFromPaths(paths) {
  for (const p of paths) {
    const parts = p.replace(/\\/g, '/').split('/');
    if (parts.length > 1) {
      const first = parts[1];
      for (const lic of KNOWN_LICENSORS) {
        if (first.toLowerCase().includes(lic.toLowerCase())) return lic;
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// HMAC-SHA256 verification
// ---------------------------------------------------------------------------

async function verifyHmac(body, signature, secret) {
  try {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      'raw',
      encoder.encode(secret),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['sign'],
    );
    const signatureBuffer = await crypto.subtle.sign('HMAC', key, encoder.encode(body));
    const computed = Array.from(new Uint8Array(signatureBuffer))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('');
    return computed === signature;
  } catch (err) {
    console.error('HMAC verification error:', err.message);
    return false;
  }
}
