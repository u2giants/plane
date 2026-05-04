// integrations/worker/src/index.js
// Cloudflare Worker — ClickUp webhook receiver + AI query interface
//
// Routes:
//   GET  /health                → liveness check
//   POST /clickup/webhook       → ClickUp webhook receiver → D1
//   POST /query                 → natural language → SQL → plain English answer
//
// Required Worker secrets (set via wrangler secret put <NAME>):
//   CLICKUP_WEBHOOK_SECRET      — HMAC secret for webhook validation (optional but recommended)
//   ANTHROPIC_API_KEY           — for /query endpoint
//   QUERY_SECRET                — bearer token protecting /query (optional; open if unset)
//
// D1 binding: DB → clickup-events

// ---------------------------------------------------------------------------
// Schema context — embedded for AI SQL generation
// The products table is the primary query surface; always filter is_internal=0.
// ---------------------------------------------------------------------------

const SCHEMA_CONTEXT = `
You are a SQL expert for a product licensing company that develops consumer goods
(plush toys, apparel, accessories) for major IP licensors (Disney, Marvel, etc.)
sold through mass-market retailers (Target, Walmart, etc.).

DATABASE: Cloudflare D1 (SQLite syntax). Read-only SELECT queries only.

═══ PRIMARY TABLE: products ═══
One row per product. Always add WHERE is_internal = 0 unless the user asks about internal/designflow.

Columns:
  id, name                          — product ID and name
  licensor                          — IP rights holder (Disney, Marvel, Warner Bros, etc.)
  retailer                          — selling store (Target, Walmart, etc.)
  product_category                  — type of product (plush, apparel, etc.)
  space_name                        — business unit: "POP Creations" or "Spruce Line"
  stage_name, stage_category        — current pipeline stage
  stage_order                       — 1=Ideation … 7=Complete (use for ordering)
  status, status_type               — status_type: "open" | "closed" | "done"
  priority                          — "urgent" | "high" | "normal" | "low" | NULL
  days_since_last_update            — days since anything changed on this product
  days_in_pipeline                  — days since product was created
  days_overdue                      — days past due date (NULL if not overdue)
  is_active                         — 1 if touched within last 180 days, else 0
  is_overdue                        — 1 if past due date and not closed
  is_internal                       — 1 for non-product spaces; always filter = 0
  assignee_count                    — number of people assigned
  assignee_ids                      — JSON array of user ID strings
  subtask_count, subtask_closed_count
  checklist_item_count, checklist_resolved_count, checklist_completion_pct
  milestone_concept_approved        — 1 if concept was formally approved
  milestone_sample_approved         — 1 if sample was approved
  milestone_art_complete            — 1 if art/design is complete
  milestone_pi_approved             — 1 if product integrity approved
  milestone_tech_pack_checked       — 1 if tech pack reviewed
  concept_revisions                 — number of concept revision cycles
  packaging_revisions               — number of packaging revision cycles
  sample_rounds                     — number of sample submission rounds
  comment_approvals                 — comments containing approval language
  comment_revisions                 — comments containing revision-request language
  comment_rejections                — comments containing rejection language
  due_date, created_at, updated_at, last_activity_at, closed_at

═══ OTHER TABLES ═══
product_checkpoints(product_id, step_id, raw_name, resolved INTEGER, resolved_at TEXT, resolved_by TEXT)
  — every checklist item on every product, classified by step_id

checkpoint_map(step_id TEXT PK, step_name, step_order INTEGER, step_category)
  — 27 process steps defining the workflow

workflow_stages(status_raw TEXT PK, stage_order, stage_name, stage_category)
  — maps ClickUp status strings to pipeline stages

users(id TEXT PK, username, email, role_name)
  — workspace members; join on assignee_ids JSON or status_transitions.user_id

task_tags(task_id, tag_name)
  — tags applied to tasks in ClickUp; use to find categorized/flagged products

task_links(task_id, linked_task_id, link_direction, link_type)
  — linked tasks and dependencies between tasks (link_type: 'linked' or 'dependency')

task_comments(id, task_id, content, user_id, user_name, comment_driver, created_at)
  — all comments; comment_driver: 'licensor' | 'factory' | 'retailer' | NULL

status_transitions(task_id, from_status, to_status, user_id, user_name, transitioned_at)
  — status change history (sparse; only captured via webhook going forward)

time_entries(task_id, user_id, user_name, duration_hrs, start_time)
  — time logged against tasks (last 90 days)

═══ VIEWS (prefer these for common queries) ═══
overdue_products       — open products past due date (id, name, licensor, retailer, stage_name, days_overdue, priority)
stalled_products       — active products with no movement in 30+ days (days_since_last_update > 30)
comment_signals        — products with comment-based process signals
comment_drivers        — per-product breakdown of comments by driver (licensor_comments, factory_comments, retailer_comments)
tag_usage              — tag_name, product_count, pct_of_products — what tags are in use
task_dependency_map    — tasks with blocking dependencies (task_name, depends_on_name, depends_on_status)
licensor_activity      — per-licensor: product_count, active_product_count, avg_days_in_pipeline
product_journey        — resolved checkpoints per product in chronological order with dates
checkpoint_velocity    — avg days from product creation to each checkpoint completion

═══ RULES ═══
1. Always WHERE is_internal = 0 (filters out internal tool space)
2. "Active" means is_active = 1; "open" means status_type != 'closed'
3. Return ONLY the SQL statement — no explanation, no markdown, no code fences
4. Use SQLite syntax (no ILIKE, use LIKE; no arrays, use json_each for assignee_ids)
5. Keep queries efficient; products has ~9,000 rows, ~300 active
6. For licensor/retailer questions, check both the products table AND the licensors/retailers tables
7. When counting revision cycles, use concept_revisions, packaging_revisions, sample_rounds columns
`.trim();

const FORMAT_CONTEXT = `You are a sharp business analyst for a consumer goods licensing company.
Given a question and a SQL result, write a concise 1-3 sentence plain English answer.
Be specific: include exact numbers, names, and percentages from the data.
If the result is empty, say clearly that no matching products were found.
Do not mention SQL or databases. Speak as if you know the business.`.trim();

const OPENROUTER_MODEL = 'deepseek/deepseek-v3.2';
const OPENROUTER_URL   = 'https://openrouter.ai/api/v1/chat/completions';

// ---------------------------------------------------------------------------
// Known licensors for path extraction
// ---------------------------------------------------------------------------

const KNOWN_LICENSORS = [
  'Disney', 'Marvel', 'Warner Bros', 'WB', 'Paramount', 'SEGA',
  'Universal', 'Nickelodeon', 'DreamWorks', 'Hasbro', 'Mattel',
];

// ---------------------------------------------------------------------------
// Comment driver classification — who is driving a comment?
// ---------------------------------------------------------------------------

const LICENSOR_KW = [
  'per licensor', 'licensor says', 'licensor wants', 'licensor feedback',
  'licensor requires', 'licensor approved', 'licensor rejected', 'licensor comment',
  'licensor notes', 'per the licensor', 'ip approved', 'ip rejected', 'ip notes',
  'brand approved', 'brand rejected', 'brand feedback', 'brand says', 'brand notes',
  'per disney', 'disney approved', 'disney rejected', 'disney wants', 'disney feedback',
  'per marvel', 'marvel approved', 'marvel rejected',
  'per wb', 'per warner', 'warner approved', 'warner rejected',
  'per peanuts', 'per sega', 'per nickelodeon', 'per wwe',
  'per strawberry', 'per care bears', 'per sanrio',
];
const FACTORY_KW = [
  'factory says', 'factory confirmed', 'factory feedback', 'factory notes',
  'factory issue', 'from the factory', 'from factory', 'factory approved',
  'factory rejected', 'vendor says', 'supplier says', 'vendor feedback',
  'production issue', 'qc issue', 'quality issue', 'sample quality',
];
const RETAILER_KW = [
  'buyer says', 'buyer wants', 'buyer feedback', 'buyer notes',
  'per the buyer', 'per buyer', 'buyer approved', 'buyer confirmed',
  'customer feedback', 'customer wants', 'retailer feedback',
  'per burlington', 'per ross', 'per walmart', 'per target',
  'per tjx', 'per tj maxx', 'per five below',
];

function classifyCommentDriver(text) {
  if (!text) return null;
  const lower = text.toLowerCase();
  if (LICENSOR_KW.some(kw => lower.includes(kw))) return 'licensor';
  if (FACTORY_KW.some(kw  => lower.includes(kw))) return 'factory';
  if (RETAILER_KW.some(kw => lower.includes(kw))) return 'retailer';
  return null;
}

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
      return json({ status: 'ok', ts: new Date().toISOString() });
    }

    if (url.pathname === '/clickup/webhook' && request.method === 'POST') {
      return handleClickUpWebhook(request, env);
    }

    if (url.pathname === '/query' && request.method === 'POST') {
      return handleAIQuery(request, env);
    }

    if (url.pathname === '/interview' && request.method === 'GET') {
      return handleInterviewPage(request, env);
    }

    if (url.pathname === '/interview/answer' && request.method === 'POST') {
      return handleInterviewAnswer(request, env);
    }

    return new Response('not found', { status: 404 });
  },
};

// ---------------------------------------------------------------------------
// AI Query handler
// ---------------------------------------------------------------------------

async function handleAIQuery(request, env) {
  // Optional bearer token auth
  const querySecret = env.QUERY_SECRET || '';
  if (querySecret) {
    const auth = request.headers.get('Authorization') || '';
    if (auth !== `Bearer ${querySecret}`) {
      return json({ error: 'unauthorized' }, 401);
    }
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'request body must be JSON' }, 400);
  }

  const question = (body.question || '').trim();
  if (!question) {
    return json({ error: 'question field is required' }, 400);
  }

  const apiKey = env.OPENROUTER_API_KEY || '';
  if (!apiKey) {
    return json({ error: 'OPENROUTER_API_KEY not configured on this Worker' }, 500);
  }

  // Step 1 — generate SQL
  let sql;
  try {
    const raw = await callLLM(apiKey, SCHEMA_CONTEXT, question, 512);
    sql = cleanSQL(raw);
  } catch (err) {
    return json({ error: 'Claude API error (SQL generation)', message: err.message }, 502);
  }

  if (!sql || !sql.trim().toUpperCase().startsWith('SELECT')) {
    return json({ error: 'model did not return a SELECT statement', raw: sql }, 500);
  }

  // Step 2 — execute SQL against D1
  let rows = [];
  let sqlError = null;
  try {
    const result = await env.DB.prepare(sql).all();
    rows = result.results || [];
  } catch (err) {
    sqlError = err.message;
  }

  // Step 3 — format answer in plain English
  let answer;
  if (sqlError) {
    answer = `The query could not be executed: ${sqlError}`;
  } else {
    try {
      const rowSummary = rows.length === 0
        ? 'The query returned no rows.'
        : JSON.stringify(rows.slice(0, 30));
      const formatPrompt = `Question: "${question}"\n\nSQL used:\n${sql}\n\nResult (${rows.length} total rows):\n${rowSummary}`;
      answer = await callLLM(apiKey, FORMAT_CONTEXT, formatPrompt, 512);
    } catch (err) {
      answer = `Query returned ${rows.length} row(s) but formatting failed: ${err.message}`;
    }
  }

  return json({
    question,
    answer,
    sql,
    row_count: rows.length,
    rows: rows.slice(0, 50),   // cap at 50 rows in response
    sql_error: sqlError || undefined,
  });
}

// ---------------------------------------------------------------------------
// LLM helper — OpenRouter (OpenAI-compatible)
// ---------------------------------------------------------------------------

async function callLLM(apiKey, systemPrompt, userMessage, maxTokens = 512) {
  const resp = await fetch(OPENROUTER_URL, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': 'https://plane-integrations.u2giants.workers.dev',
    },
    body: JSON.stringify({
      model: OPENROUTER_MODEL,
      max_tokens: maxTokens,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user',   content: userMessage  },
      ],
    }),
  });

  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`OpenRouter ${resp.status}: ${errText.slice(0, 200)}`);
  }

  const data = await resp.json();
  return data.choices?.[0]?.message?.content?.trim() || '';
}

function cleanSQL(text) {
  // Strip markdown code fences if Claude includes them
  return text
    .replace(/```sql\s*/gi, '')
    .replace(/```\s*/gi, '')
    .trim();
}

// ---------------------------------------------------------------------------
// Webhook handler
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

  const eventType    = payload.event || '';
  const historyItems = Array.isArray(payload.history_items) ? payload.history_items : [];
  const item         = historyItems[0] || {};

  const workspaceId = payload.team_id ? String(payload.team_id) : null;
  const taskId      = payload.task_id ? String(payload.task_id) : null;
  const listId      = item.parent_id  ? String(item.parent_id)  : null;
  const spaceId     = null;

  const userId   = item.user
    ? String(item.user.id || '')
    : (payload.user_id ? String(payload.user_id) : null);
  const userName = item.user
    ? (item.user.username || item.user.email || null)
    : null;

  const fieldChanged = item.field || null;
  const fromValue    = item.before != null
    ? (typeof item.before === 'object'
        ? (item.before.status || JSON.stringify(item.before))
        : String(item.before))
    : null;
  const toValue = item.after != null
    ? (typeof item.after === 'object'
        ? (item.after.status || JSON.stringify(item.after))
        : String(item.after))
    : null;

  // Primary write: raw_events table
  try {
    await env.DB.prepare(`
      INSERT INTO raw_events
        (event_type, task_id, list_id, workspace_id, raw_payload, user_id, user_name,
         field_changed, from_value, to_value, space_id)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      eventType, taskId, listId, workspaceId, body,
      userId, userName, fieldChanged, fromValue, toValue, spaceId,
    ).run();
  } catch (err) {
    // Fallback: try legacy 'events' table name in case migration hasn't run
    try {
      await env.DB.prepare(`
        INSERT INTO events
          (event_type, task_id, list_id, workspace_id, payload, user_id, user_name,
           field_changed, from_value, to_value, space_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        eventType, taskId, listId, workspaceId, body,
        userId, userName, fieldChanged, fromValue, toValue, spaceId,
      ).run();
    } catch (err2) {
      console.error('events table write failed:', err2.message);
      return new Response('internal error', { status: 500 });
    }
  }

  // Secondary writes — best-effort
  const handlers = {
    taskStatusUpdated:       () => writeStatusTransition(env.DB, { taskId, fromValue, toValue, item, userId, userName, listId, spaceId, workspaceId }),
    taskAssigneeUpdated:     () => writeTaskAssignment(env.DB, { taskId, fieldChanged, item, userId }),
    taskCommentPosted:       () => writeTaskComment(env.DB, { taskId, item, payload, userId, userName }),
    taskCreated:             () => writeTaskStub(env.DB, { taskId, listId, workspaceId, spaceId, toValue, userId }),
    taskCustomFieldUpdated:  () => writeCustomFieldChange(env.DB, { taskId, item }),
    taskChecklistUpdated:    () => writeChecklistItemUpdate(env.DB, { taskId, item, userId, userName }),
  };

  if (handlers[eventType]) {
    try {
      await handlers[eventType]();
    } catch (err) {
      console.error(`${eventType} handler failed:`, err.message);
    }
  }

  return new Response('ok', { status: 200 });
}

// ---------------------------------------------------------------------------
// Specialized table writers
// ---------------------------------------------------------------------------

async function writeStatusTransition(db, { taskId, fromValue, toValue, item, userId, userName, listId, spaceId, workspaceId }) {
  const fromStatusType = item.before && typeof item.before === 'object' ? (item.before.type || null) : null;
  const toStatusType   = item.after  && typeof item.after  === 'object' ? (item.after.type  || null) : null;

  await db.prepare(`
    INSERT INTO status_transitions
      (task_id, from_status, to_status, from_status_type, to_status_type,
       user_id, user_name, list_id, space_id, workspace_id, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'webhook')
  `).bind(taskId, fromValue, toValue, fromStatusType, toStatusType,
          userId, userName, listId, spaceId, workspaceId).run();
}

async function writeTaskAssignment(db, { taskId, fieldChanged, item, userId }) {
  const isAdd      = fieldChanged === 'assignee_add';
  const assigneeObj = isAdd
    ? (item.after  && typeof item.after  === 'object' ? item.after  : null)
    : (item.before && typeof item.before === 'object' ? item.before : null);
  const assigneeId = assigneeObj
    ? String(assigneeObj.id || assigneeObj.user_id || '')
    : null;

  if (isAdd) {
    await db.prepare(`
      INSERT INTO task_assignments (task_id, user_id, assigned_by, is_current, source)
      VALUES (?, ?, ?, 1, 'webhook')
    `).bind(taskId, assigneeId, userId).run();
  } else {
    await db.prepare(`
      INSERT INTO task_assignments (task_id, user_id, assigned_by, is_current, unassigned_at, source)
      VALUES (?, ?, ?, 0, datetime('now'), 'webhook')
    `).bind(taskId, assigneeId, userId).run();
  }
}

async function writeTaskComment(db, { taskId, item, payload, userId, userName }) {
  const historyItems = Array.isArray(payload.history_items) ? payload.history_items : [];
  const commentObj   = historyItems[0]?.comment || null;
  if (!commentObj) return;

  const commentId   = commentObj.id ? String(commentObj.id) : null;
  if (!commentId) return;

  const textContent = commentObj.text_content || null;
  const dateMs      = commentObj.date ? Number(commentObj.date) : null;
  const createdAt   = dateMs && !isNaN(dateMs) ? new Date(dateMs).toISOString() : null;

  const commentParts    = Array.isArray(commentObj.comment) ? commentObj.comment : [];
  const mentionCount    = textContent ? (textContent.match(/@/g) || []).length : 0;
  const attachmentCount = commentParts.filter(p => p?.type === 'attachment').length;

  const filePaths      = extractFilePaths(textContent);
  const licensorHint   = extractLicensorFromPaths(filePaths);
  const commentDriver  = classifyCommentDriver(textContent);

  await db.prepare(`
    INSERT OR REPLACE INTO task_comments
      (id, task_id, user_id, user_name, content, mention_count, attachment_count,
       created_at, file_paths, licensor_hint, comment_driver, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'webhook')
  `).bind(commentId, taskId, userId, userName, textContent, mentionCount, attachmentCount,
          createdAt, filePaths.length ? JSON.stringify(filePaths) : null,
          licensorHint, commentDriver).run();
}

async function writeTaskStub(db, { taskId, listId, workspaceId, spaceId, toValue, userId }) {
  if (!taskId) return;
  await db.prepare(`
    INSERT OR IGNORE INTO tasks (id, list_id, workspace_id, space_id, status, creator_id)
    VALUES (?, ?, ?, ?, ?, ?)
  `).bind(taskId, listId, workspaceId, spaceId, toValue, userId).run();
}

async function writeCustomFieldChange(db, { taskId, item }) {
  if (!taskId) return;
  const fieldId   = item.field_id ? String(item.field_id) : null;
  const fieldName = item.field || fieldId;
  if (!fieldId || !fieldName) return;

  const after = item.after;
  let valueText = null, valueNumber = null, valueDate = null, valueBoolean = null;

  if (after === null || after === undefined) {
    // field cleared — write nulls
  } else if (typeof after === 'number') {
    valueNumber = after;
  } else if (typeof after === 'boolean') {
    valueBoolean = after ? 1 : 0;
  } else if (typeof after === 'object') {
    valueText = after.name || after.value || JSON.stringify(after);
  } else {
    const s = String(after);
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
  `).bind(taskId, fieldId, fieldName, valueText, valueNumber, valueDate, valueBoolean).run();
}

async function writeChecklistItemUpdate(db, { taskId, item, userId }) {
  // ClickUp fires taskChecklistUpdated for any checklist change.
  // item.field indicates the sub-type: "checklist_item_resolved", "checklist_item_created", etc.
  // item.after contains the current state of the affected item.
  const afterObj = item.after && typeof item.after === 'object' ? item.after : null;
  if (!afterObj) return;

  const itemId      = afterObj.id       ? String(afterObj.id)       : null;
  const checklistId = afterObj.checklist_id ? String(afterObj.checklist_id) : null;
  if (!itemId) return;

  const resolved   = (afterObj.resolved === true || afterObj.resolved === 1) ? 1 : 0;
  const resolvedAt = resolved ? new Date().toISOString() : null;
  const resolvedBy = resolved ? userId : null;
  const name       = afterObj.name || null;

  await db.prepare(`
    INSERT OR REPLACE INTO checklist_items
      (id, checklist_id, name, resolved, resolved_by, resolved_at, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
  `).bind(itemId, checklistId, name, resolved, resolvedBy, resolvedAt).run();
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
// Interview page
// ---------------------------------------------------------------------------

async function handleInterviewPage(request, env) {
  const pending = await env.DB.prepare(
    `SELECT id, question, context, topic FROM interview_questions WHERE status = 'pending' ORDER BY id ASC LIMIT 1`
  ).first();

  const { results: answered } = await env.DB.prepare(
    `SELECT id, question, answer, topic, answered_at FROM interview_questions WHERE status = 'answered' ORDER BY id ASC`
  ).all();

  return new Response(buildInterviewHTML(pending, answered || []), {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

async function handleInterviewAnswer(request, env) {
  let form;
  try { form = await request.formData(); } catch { return new Response('bad request', { status: 400 }); }

  const questionId = parseInt(form.get('question_id') || '0', 10);
  const answer = (form.get('answer') || '').trim();

  if (answer && questionId) {
    await env.DB.prepare(
      `UPDATE interview_questions SET answer = ?, answered_at = datetime('now'), status = 'answered' WHERE id = ? AND status = 'pending'`
    ).bind(answer, questionId).run();
  }

  const base = new URL(request.url);
  return Response.redirect(`${base.origin}/interview`, 302);
}

function esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function buildInterviewHTML(pending, answered) {
  const pendingHtml = pending ? `
    <div class="card">
      ${pending.topic ? `<div class="badge">${esc(pending.topic.replace(/_/g, ' '))}</div>` : ''}
      <div class="q-text">${esc(pending.question)}</div>
      ${pending.context ? `<div class="q-context">${esc(pending.context)}</div>` : ''}
      <form method="POST" action="/interview/answer">
        <input type="hidden" name="question_id" value="${pending.id}">
        <textarea name="answer" placeholder="Type your answer here…" required autofocus></textarea>
        <button type="submit">Submit Answer</button>
      </form>
    </div>` : `
    <div class="card done-card">
      <div class="done-icon">&#10003;</div>
      <div class="done-title">All caught up!</div>
      <div class="done-sub">No new questions right now — check back soon.</div>
    </div>`;

  const historyHtml = answered.length > 0 ? `
    <div class="history">
      <div class="history-label">${answered.length} answered</div>
      ${answered.map(q => `
      <div class="h-item">
        <div class="h-q">${esc(q.question)}</div>
        <div class="h-a">${esc(q.answer || '')}</div>
        ${q.answered_at ? `<div class="h-date">${q.answered_at.slice(0, 10)}</div>` : ''}
      </div>`).join('')}
    </div>` : '';

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Business Q&amp;A</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f5f7;color:#111;min-height:100vh;padding:36px 16px}
.wrap{max-width:640px;margin:0 auto}
.eyebrow{font-size:.8rem;font-weight:600;color:#999;text-transform:uppercase;letter-spacing:.1em;margin-bottom:24px}
.card{background:#fff;border-radius:16px;padding:30px;box-shadow:0 1px 4px rgba(0,0,0,.07),0 6px 20px rgba(0,0,0,.04);margin-bottom:24px}
.badge{display:inline-block;background:#eef2ff;color:#4263eb;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;padding:4px 10px;border-radius:20px;margin-bottom:14px}
.q-text{font-size:1.2rem;font-weight:700;line-height:1.55;margin-bottom:10px}
.q-context{font-size:.88rem;color:#888;line-height:1.55;margin-bottom:18px;padding:10px 14px;background:#f8f9fa;border-radius:8px}
textarea{width:100%;border:1.5px solid #dde1e7;border-radius:10px;padding:14px;font-size:.98rem;font-family:inherit;line-height:1.55;resize:vertical;min-height:140px;outline:none;transition:border-color .15s;color:#111}
textarea:focus{border-color:#4263eb}
button{background:#4263eb;color:#fff;border:none;border-radius:10px;padding:13px 32px;font-size:.98rem;font-weight:600;cursor:pointer;margin-top:14px;transition:background .15s}
button:hover{background:#3451d1}
.done-card{text-align:center;padding:52px 28px}
.done-icon{font-size:2.8rem;color:#40c057;margin-bottom:12px}
.done-title{font-size:1.35rem;font-weight:700;margin-bottom:6px}
.done-sub{color:#999}
.history{margin-top:12px}
.history-label{font-size:.8rem;font-weight:600;color:#bbb;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px}
.h-item{background:#fff;border-radius:12px;padding:20px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.h-q{font-size:.9rem;font-weight:600;color:#555;margin-bottom:8px}
.h-a{font-size:.95rem;line-height:1.65;white-space:pre-wrap;color:#1a1a1a}
.h-date{font-size:.75rem;color:#ccc;margin-top:8px}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">Business Q&amp;A</div>
  ${pendingHtml}
  ${historyHtml}
</div>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function verifyHmac(body, signature, secret) {
  try {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      'raw', encoder.encode(secret),
      { name: 'HMAC', hash: 'SHA-256' },
      false, ['sign'],
    );
    const sigBuf  = await crypto.subtle.sign('HMAC', key, encoder.encode(body));
    const computed = Array.from(new Uint8Array(sigBuf))
      .map(b => b.toString(16).padStart(2, '0')).join('');
    return computed === signature;
  } catch (err) {
    console.error('HMAC verification error:', err.message);
    return false;
  }
}
