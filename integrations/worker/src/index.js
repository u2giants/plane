/**
 * plane-integrations Worker
 * Receives ClickUp webhooks, validates HMAC, writes to D1.
 * Will grow into the permanent integration hub for Plane ↔ external tools.
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

  const eventType   = payload.event                                     ?? 'unknown';
  const taskId      = payload.task_id                                   ?? null;
  const listId      = payload.history_items?.[0]?.data?.list_id        ?? null;
  const workspaceId = String(payload.webhook_id ?? '');

  try {
    await env.DB.prepare(
      `INSERT INTO events (event_type, task_id, list_id, workspace_id, payload)
       VALUES (?, ?, ?, ?, ?)`
    ).bind(eventType, taskId, listId, workspaceId, body).run();
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
