/**
 * plane-integrations Worker
 * Receives ClickUp webhooks, validates HMAC, writes enriched rows to D1.
 * Also serves as the permanent integration hub for Plane ↔ external tools.
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/health' && request.method === 'GET') {
      return new Response(JSON.stringify({ status: 'ok', ts: new Date().toISOString() }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (url.pathname === '/clickup/webhook' && request.method === 'POST') {
      return handleClickUpWebhook(request, env);
    }

    return new Response('Not Found', { status: 404 });
  },
};

async function handleClickUpWebhook(request, env) {
  const body = await request.text();

  // Validate HMAC-SHA256 signature sent by ClickUp
  if (env.CLICKUP_WEBHOOK_SECRET) {
    const signature = request.headers.get('X-Signature');
    if (!signature) {
      console.warn('Missing X-Signature header');
      return new Response('Unauthorized', { status: 401 });
    }
    const valid = await verifyHmac(body, signature, env.CLICKUP_WEBHOOK_SECRET);
    if (!valid) {
      console.warn('Invalid HMAC signature');
      return new Response('Unauthorized', { status: 401 });
    }
  }

  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    return new Response('Bad Request: invalid JSON', { status: 400 });
  }

  // ── Core fields ────────────────────────────────────────────────────────────
  const eventType = payload.event ?? 'unknown';
  const taskId    = payload.task_id ?? null;

  // ── Extract from history_items[0] ─────────────────────────────────────────
  const item      = Array.isArray(payload.history_items) ? payload.history_items[0] : null;
  const user      = item?.user ?? null;
  const userId    = user?.id   ? String(user.id) : null;
  const userName  = user?.username ?? user?.email ?? null;
  const fieldChanged = item?.field ?? null;

  // from/to values depend on the field that changed
  let fromValue = null;
  let toValue   = null;

  if (item) {
    const data = item.data ?? {};
    switch (fieldChanged) {
      case 'status':
        fromValue = item.before?.status ?? data.from?.status ?? null;
        toValue   = item.after?.status  ?? data.to?.status   ?? null;
        break;
      case 'assignee':
        fromValue = item.before ? JSON.stringify(item.before) : null;
        toValue   = item.after  ? JSON.stringify(item.after)  : null;
        break;
      case 'priority':
        fromValue = item.before?.priority?.priority ?? item.before?.priority ?? null;
        toValue   = item.after?.priority?.priority  ?? item.after?.priority  ?? null;
        break;
      case 'due_date':
        fromValue = item.before?.due_date ?? null;
        toValue   = item.after?.due_date  ?? null;
        break;
      case 'tag':
        fromValue = item.before ? JSON.stringify(item.before) : null;
        toValue   = item.after  ? JSON.stringify(item.after)  : null;
        break;
      default:
        // Generic: try before/after, then data.from/to
        fromValue = item.before != null ? JSON.stringify(item.before) : (data.from != null ? JSON.stringify(data.from) : null);
        toValue   = item.after  != null ? JSON.stringify(item.after)  : (data.to   != null ? JSON.stringify(data.to)   : null);
    }
  }

  // list_id: ClickUp puts this in history_items[0].parent_id (not item.data.list_id which doesn't exist)
  const listId    = item?.parent_id ?? item?.data?.subcategory_id ?? payload.list_id ?? null;
  
  // space_id: ClickUp webhooks don't include this directly - must derive from list_id via list_space_map
  // Try common locations, but primary fix is via JOIN on list_space_map
  const spaceId   = item?.data?.space_id ?? payload.space_id ?? null;
  
  // workspace_id: should be team_id, not webhook_id (which is the registration UUID)
  const workspaceId = payload.team_id ? String(payload.team_id) : null;

  try {
    await env.DB.prepare(
      `INSERT INTO events
         (event_type, task_id, list_id, workspace_id, payload,
          user_id, user_name, field_changed, from_value, to_value, space_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      eventType, taskId, listId, workspaceId, body,
      userId, userName, fieldChanged, fromValue, toValue, spaceId
    ).run();
  } catch (err) {
    console.error('D1 write error:', err.message);
    return new Response('Internal Server Error', { status: 500 });
  }

  return new Response('ok', { status: 200 });
}

async function verifyHmac(body, signature, secret) {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const mac = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(body));
  const expected = Array.from(new Uint8Array(mac))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
  return signature === expected;
}
