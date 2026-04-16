#!/usr/bin/env python3
"""
build_products_table.py

Rebuilds the `products` materialized table and `product_checkpoints` fact table
in D1 from current task data.

`products`          — One row per parent task (product), fully denormalized:
                      licensor, retailer, category, stage, pipeline age,
                      subtask counts, checklist completion, milestone flags,
                      assignees, overdue state, revision counts, comment signals.

`product_checkpoints` — One row per checklist item on a parent task, with
                      step_id assigned via keyword matching against checkpoint_map.

Run after every snapshot load:
    python build_products_table.py

Env vars:
    CLOUDFLARE_ACCOUNT_ID       (required)
    CLOUDFLARE_D1_DATABASE_ID   (required)
    CLOUDFLARE_API_TOKEN        (required)
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID  = os.environ.get("CLOUDFLARE_ACCOUNT_ID",  "8303d11002766bf1cc36bf2f07ba6f20")
DATABASE_ID = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "c37aeb36-e16e-416b-b699-c910f6f8dc10")
CF_TOKEN    = os.environ.get("CLOUDFLARE_API_TOKEN", "")

D1_BASE      = (f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
                f"/d1/database/{DATABASE_ID}")
D1_MAX_PARAMS = 90
PAGE_SIZE     = 500   # rows per D1 SELECT page

ACTIVE_DAYS      = 180   # products touched within this window are considered active
INTERNAL_SPACES  = {"designflow"}   # spaces excluded from product pipeline analysis

# ---------------------------------------------------------------------------
# Checklist step classification rules.
# Each tuple: (step_id, list_of_lowercase_keywords_any_match)
# Evaluated in order — first match wins.
# ---------------------------------------------------------------------------

STEP_RULES = [
    # --- Concept ---
    ("group_concept_approved",     ["group concept approved"]),
    ("concept_approved",           ["concept approved", "concept approve"]),
    ("concept_revision_submitted", ["concept revision submitted"]),
    ("pkg_concept_revision",       ["packaging concept revision submitted"]),
    ("packaging_concept_approved", ["packaging concept approved", "packaging concept approve"]),
    ("concept_submitted",          ["concept submitted pending", "concept submitted"]),
    # --- Art / Design ---
    ("designs_complete",           ["designs complete", "designs"]),
    ("art_complete",               ["art complete"]),
    # --- Tech pack ---
    ("tech_packs_complete",        ["tech packs"]),
    ("tech_pack_check",            ["checked with the tech pack", "tech pack check"]),
    # --- Sampling ---
    ("sampling_request",           ["sampling request"]),
    ("sample_requested",           ["sample requested", "sampled requested", "sample request"]),
    ("sample_submitted",           ["sample submitted pending", "sample submitted"]),
    ("sample_approved",            ["sample approved to production", "sample approved"]),
    ("pps_approval",               ["pps approval", "pre-production sample"]),
    # --- QC / Production ---
    ("factory_qc_china",           ["checked in-person in china", "check in-person in china",
                                    "checked in person in china"]),
    ("pi_approved",                ["product integrity approved"]),
    # --- Approvals ---
    ("licensor_approval",          ["licensor approval"]),
    ("sarbani_approval",           ["sarbani"]),
    ("buyer_picks",                ["buyer picks"]),
    ("buyer_presentation",         ["presentation for buyer"]),
]

# Comment keyword signals — simple phrase matching against lowercased comment text
COMMENT_APPROVAL_KW  = ["approved", "looks good", "lgtm", "go ahead", "confirmed",
                         "great job", "perfect", "love it", "moving forward"]
COMMENT_REJECTION_KW = ["rejected", "not approved", "denied", "declined",
                         "do not proceed", "hold off", "on hold"]
COMMENT_REVISION_KW  = ["revision", "revise", "redo", "please change",
                         "needs to be fixed", "please fix", "go back"]


def classify_step(raw_name: str) -> Optional[str]:
    lower = raw_name.lower()
    for step_id, keywords in STEP_RULES:
        if any(kw in lower for kw in keywords):
            return step_id
    return None


# ---------------------------------------------------------------------------
# D1 client
# ---------------------------------------------------------------------------

def _d1_request(payload: dict, retry: int = 5) -> dict:
    url  = f"{D1_BASE}/query"
    body = json.dumps(payload).encode()
    hdrs = {"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}
    for attempt in range(retry):
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                if not data.get("success"):
                    raise RuntimeError(f"D1 error: {data.get('errors', '?')}")
                return data
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 2 ** attempt
                print(f"  [D1 rate-limit] sleeping {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"D1 HTTP {exc.code}: {exc.read().decode()[:200]}") from exc
        except RuntimeError:
            raise
        except Exception:
            if attempt < retry - 1:
                time.sleep(2 ** attempt)
            else:
                raise
    raise RuntimeError("D1 retries exhausted")


def d1_exec(sql: str, params: list) -> None:
    clean = [str(p) if isinstance(p, int) and not isinstance(p, bool) else p for p in params]
    _d1_request({"sql": sql, "params": clean})


def d1_query(sql: str, params: list = None) -> list:
    clean = [str(p) if isinstance(p, int) and not isinstance(p, bool) else p
             for p in (params or [])]
    data = _d1_request({"sql": sql, "params": clean})
    return data["result"][0]["results"] if data.get("result") else []


def d1_bulk_insert(sql_template: str, rows: list) -> None:
    if not rows:
        return
    n_cols     = sql_template.count("?")
    chunk_size = max(1, D1_MAX_PARAMS // n_cols)
    prefix     = sql_template[:sql_template.rfind("VALUES")].rstrip()
    one_row    = "(" + ",".join(["?"] * n_cols) + ")"
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        if len(chunk) == 1:
            d1_exec(sql_template, chunk[0])
        else:
            expanded = f"{prefix} VALUES " + ",".join([one_row] * len(chunk))
            flat     = [v for row in chunk for v in row]
            d1_exec(expanded, flat)


def d1_page(sql_base: str, params: list = None, page_size: int = PAGE_SIZE):
    """Generator — yields rows from a large table in pages using LIMIT/OFFSET."""
    offset = 0
    while True:
        rows = d1_query(f"{sql_base} LIMIT {page_size} OFFSET {offset}", params)
        if not rows:
            break
        yield from rows
        if len(rows) < page_size:
            break
        offset += page_size


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_tasks_by_id() -> dict:
    print("  Loading tasks…")
    tasks = {}
    for row in d1_page(
        "SELECT id, name, parent_task_id, list_id, space_id, workspace_id, "
        "status, status_type, licensor, priority, due_date, start_date, "
        "created_at, updated_at, closed_at, creator_id FROM tasks"
    ):
        tasks[row["id"]] = row
    print(f"    {len(tasks):,} tasks loaded")
    return tasks


def load_custom_fields() -> dict:
    """Returns {task_id: {field_name: value}}"""
    print("  Loading custom fields…")
    cf: dict = {}
    for row in d1_page(
        "SELECT task_id, field_name, value_text, value_number FROM task_custom_fields"
    ):
        tid = row["task_id"]
        if tid not in cf:
            cf[tid] = {}
        val = row["value_text"] if row["value_text"] is not None else row["value_number"]
        cf[tid][row["field_name"]] = val
    print(f"    {sum(len(v) for v in cf.values()):,} custom field values loaded")
    return cf


def load_lists() -> dict:
    rows = d1_query("SELECT id, name FROM lists")
    return {r["id"]: r["name"] for r in rows}


def load_spaces() -> dict:
    rows = d1_query("SELECT id, name FROM spaces")
    return {r["id"]: r["name"] for r in rows}


def load_workflow_stages() -> dict:
    rows = d1_query("SELECT status_raw, stage_order, stage_name, stage_category FROM workflow_stages")
    return {r["status_raw"]: r for r in rows}


def load_checklist_items() -> dict:
    """Returns {task_id: [row, ...]}"""
    print("  Loading checklist items…")
    items: dict = {}
    for row in d1_page(
        "SELECT tc.task_id, ci.checklist_id, ci.id as item_id, ci.name, "
        "ci.resolved, ci.resolved_at, ci.resolved_by "
        "FROM checklist_items ci "
        "JOIN task_checklists tc ON tc.id = ci.checklist_id"
    ):
        tid = row["task_id"]
        if tid not in items:
            items[tid] = []
        items[tid].append(row)
    total = sum(len(v) for v in items.values())
    print(f"    {total:,} checklist items loaded for {len(items):,} tasks")
    return items


def load_assignments() -> dict:
    """
    Returns {task_id: [user_id, ...]} for current assignments.
    Gracefully returns {} if table is empty (populated by snapshot going forward).
    """
    print("  Loading assignments…")
    result: dict = {}
    try:
        for row in d1_page(
            "SELECT task_id, user_id FROM task_assignments "
            "WHERE is_current = 1 AND user_id IS NOT NULL"
        ):
            tid = row["task_id"]
            if tid not in result:
                result[tid] = []
            result[tid].append(row["user_id"])
        total = sum(len(v) for v in result.values())
        print(f"    {total:,} assignee links for {len(result):,} tasks")
    except Exception as exc:
        print(f"    WARNING: assignments load failed: {exc}")
    return result


def load_comment_signals() -> dict:
    """
    Returns {task_id: {approvals, rejections, revisions}} from keyword scan
    of task_comments.content. Gracefully returns {} if table is empty.
    """
    print("  Loading comment signals…")
    signals: dict = {}
    try:
        count = 0
        for row in d1_page(
            "SELECT task_id, content FROM task_comments "
            "WHERE content IS NOT NULL AND content != ''"
        ):
            text = (row.get("content") or "").lower()
            if not text:
                continue
            tid = row["task_id"]
            if tid not in signals:
                signals[tid] = {"approvals": 0, "rejections": 0, "revisions": 0}
            if any(kw in text for kw in COMMENT_APPROVAL_KW):
                signals[tid]["approvals"] += 1
            if any(kw in text for kw in COMMENT_REJECTION_KW):
                signals[tid]["rejections"] += 1
            if any(kw in text for kw in COMMENT_REVISION_KW):
                signals[tid]["revisions"] += 1
            count += 1
        print(f"    {count:,} comments scanned, {len(signals):,} tasks with signals")
    except Exception as exc:
        print(f"    WARNING: comment signals load failed: {exc}")
    return signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def days_since(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 1)
    except Exception:
        return None


def get_cf(cf_map: dict, task_id: str, *field_names) -> Optional[str]:
    fields = cf_map.get(task_id, {})
    for name in field_names:
        v = fields.get(name)
        if v is not None:
            return str(v) if not isinstance(v, str) else v
    return None


# ---------------------------------------------------------------------------
# INSERT templates  (54 columns / 54 ?)
# ---------------------------------------------------------------------------

INSERT_PRODUCT = (
    "INSERT OR REPLACE INTO products "
    "(id, name, licensor, retailer, product_category, put_up, factory, buyer, "
    "task_type, customer_program, sample_req_count, "
    "status, status_type, stage_order, stage_name, stage_category, "
    "list_id, list_name, space_id, space_name, "
    "created_at, updated_at, closed_at, due_date, start_date, "
    "days_since_last_update, days_in_pipeline, creator_id, "
    "priority, assignee_count, assignee_ids, "
    "subtask_count, subtask_closed_count, "
    "checklist_item_count, checklist_resolved_count, checklist_completion_pct, "
    "milestone_concept_approved, milestone_sample_approved, milestone_art_complete, "
    "milestone_pi_approved, milestone_tech_pack_checked, "
    "concept_revisions, packaging_revisions, sample_rounds, "
    "is_overdue, days_overdue, "
    "last_subtask_activity, last_activity_at, is_active, is_internal, "
    "comment_approvals, comment_revisions, comment_rejections, "
    "refreshed_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
    "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)

INSERT_PCHK = (
    "INSERT OR REPLACE INTO product_checkpoints "
    "(product_id, checklist_id, item_id, step_id, raw_name, "
    "resolved, resolved_at, resolved_by, refreshed_at) "
    "VALUES (?,?,?,?,?,?,?,?,?)"
)


# ---------------------------------------------------------------------------
# Core build
# ---------------------------------------------------------------------------

def build_products(
    tasks: dict,
    cf_map: dict,
    lists: dict,
    spaces: dict,
    stages: dict,
    checklist_items: dict,
    assignments: dict,
    comment_signals: dict,
) -> tuple:
    """Returns (product_rows, checkpoint_rows) ready for bulk insert."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build subtask index: counts + most-recent activity per parent
    subtask_counts: dict   = {}
    subtask_closed: dict   = {}
    subtask_last_act: dict = {}
    for task in tasks.values():
        pid = task.get("parent_task_id")
        if not pid:
            continue
        subtask_counts[pid] = subtask_counts.get(pid, 0) + 1
        if task.get("status_type") == "closed":
            subtask_closed[pid] = subtask_closed.get(pid, 0) + 1
        sub_ua = task.get("updated_at")
        if sub_ua:
            prev = subtask_last_act.get(pid)
            if prev is None or sub_ua > prev:
                subtask_last_act[pid] = sub_ua

    product_rows    = []
    checkpoint_rows = []

    for tid, task in tasks.items():
        if task.get("parent_task_id") is not None:
            continue   # subtask

        stage       = stages.get(task.get("status") or "", {})
        clist_items = checklist_items.get(tid, [])

        # Checklist aggregation
        n_items    = len(clist_items)
        n_resolved = sum(1 for ci in clist_items if ci.get("resolved"))

        # Single-pass: milestone flags + revision counts + checkpoint rows
        mil_concept = mil_sample = mil_art = mil_pi = mil_tech_pack = 0
        concept_revisions = packaging_revisions = sample_rounds = 0

        for ci in clist_items:
            step     = classify_step(ci.get("name") or "")
            resolved = bool(ci.get("resolved"))

            # Revision counts — all occurrences
            if step == "concept_revision_submitted":
                concept_revisions += 1
            elif step == "pkg_concept_revision":
                packaging_revisions += 1
            elif step == "sample_submitted":
                sample_rounds += 1

            # Checkpoint row — every item (resolved or not)
            checkpoint_rows.append([
                tid,
                ci["checklist_id"],
                ci["item_id"],
                step,
                ci.get("name"),
                1 if resolved else 0,
                ci.get("resolved_at") if resolved else None,
                ci.get("resolved_by") if resolved else None,
                now_iso,
            ])

            # Milestone flags — resolved only
            if not resolved:
                continue
            if step in ("concept_approved", "group_concept_approved",
                        "packaging_concept_approved"):
                mil_concept = 1
            if step == "sample_approved":
                mil_sample = 1
            if step == "art_complete":
                mil_art = 1
            if step == "pi_approved":
                mil_pi = 1
            if step == "tech_pack_check":
                mil_tech_pack = 1

        # Custom fields
        retailer = get_cf(cf_map, tid, "🧑‍✈ Customer / Retailer", "customer")
        cat      = get_cf(cf_map, tid, "📚 Category")
        put_up   = get_cf(cf_map, tid, "put-up")
        factory  = get_cf(cf_map, tid, "🏭 Factory")
        buyer    = get_cf(cf_map, tid, "👤 Buyer")
        ttype    = get_cf(cf_map, tid, "Idea/Task Type")
        cprog    = get_cf(cf_map, tid, "cust program")
        smpl_req = get_cf(cf_map, tid, "SMPL Req")

        # Assignees
        assignee_list  = assignments.get(tid, [])
        assignee_count = len(assignee_list)
        assignee_ids   = json.dumps(assignee_list) if assignee_list else None

        # Subtask aggregation
        sub_cnt    = subtask_counts.get(tid, 0)
        sub_closed = subtask_closed.get(tid, 0)
        pct        = round(n_resolved / n_items * 100, 1) if n_items else None

        # Activity window
        parent_ua   = task.get("updated_at")
        sub_last_ua = subtask_last_act.get(tid)
        last_act    = max(filter(None, [parent_ua, sub_last_ua]), default=None)
        is_active   = 1 if (days_since(last_act) is not None
                            and days_since(last_act) < ACTIVE_DAYS) else 0

        # Internal flag
        space_name_val = spaces.get(task.get("space_id") or "")
        is_internal    = 1 if (space_name_val or "").lower() in INTERNAL_SPACES else 0

        # Overdue (only meaningful for open products with a due date)
        due        = task.get("due_date")
        is_overdue = 0
        days_overdue = None
        if due and task.get("status_type") != "closed":
            d = days_since(due)
            if d is not None and d > 0:
                is_overdue   = 1
                days_overdue = round(d, 1)

        # Comment signals
        csig               = comment_signals.get(tid, {})
        comment_approvals  = csig.get("approvals", 0)
        comment_rejections = csig.get("rejections", 0)
        comment_revs       = csig.get("revisions", 0)

        # Priority — stored as text ("urgent"/"high"/"normal"/"low"/None)
        priority = task.get("priority")

        product_rows.append([
            tid,                                              # id
            task.get("name"),                                 # name
            task.get("licensor"),                             # licensor
            retailer,                                         # retailer
            cat,                                              # product_category
            put_up,                                           # put_up
            factory,                                          # factory
            buyer,                                            # buyer
            ttype,                                            # task_type
            cprog,                                            # customer_program
            float(smpl_req) if smpl_req is not None else None, # sample_req_count
            task.get("status"),                               # status
            task.get("status_type"),                          # status_type
            stage.get("stage_order"),                         # stage_order
            stage.get("stage_name"),                          # stage_name
            stage.get("stage_category"),                      # stage_category
            task.get("list_id"),                              # list_id
            lists.get(task.get("list_id") or ""),             # list_name
            task.get("space_id"),                             # space_id
            space_name_val,                                   # space_name
            task.get("created_at"),                           # created_at
            task.get("updated_at"),                           # updated_at
            task.get("closed_at"),                            # closed_at
            task.get("due_date"),                             # due_date
            task.get("start_date"),                           # start_date
            days_since(task.get("updated_at")),               # days_since_last_update
            days_since(task.get("created_at")),               # days_in_pipeline
            task.get("creator_id"),                           # creator_id
            priority,                                         # priority
            assignee_count,                                   # assignee_count
            assignee_ids,                                     # assignee_ids
            sub_cnt,                                          # subtask_count
            sub_closed,                                       # subtask_closed_count
            n_items,                                          # checklist_item_count
            n_resolved,                                       # checklist_resolved_count
            pct,                                              # checklist_completion_pct
            mil_concept,                                      # milestone_concept_approved
            mil_sample,                                       # milestone_sample_approved
            mil_art,                                          # milestone_art_complete
            mil_pi,                                           # milestone_pi_approved
            mil_tech_pack,                                    # milestone_tech_pack_checked
            concept_revisions,                                # concept_revisions
            packaging_revisions,                              # packaging_revisions
            sample_rounds,                                    # sample_rounds
            is_overdue,                                       # is_overdue
            days_overdue,                                     # days_overdue
            sub_last_ua,                                      # last_subtask_activity
            last_act,                                         # last_activity_at
            is_active,                                        # is_active
            is_internal,                                      # is_internal
            comment_approvals,                                # comment_approvals
            comment_revs,                                     # comment_revisions
            comment_rejections,                               # comment_rejections
            now_iso,                                          # refreshed_at
        ])

    return product_rows, checkpoint_rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not CF_TOKEN:
        print("ERROR: CLOUDFLARE_API_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    t0 = datetime.now(timezone.utc)
    print(f"=== build_products_table.py starting at {t0.isoformat()} ===\n")

    print("Loading source data…")
    tasks       = load_tasks_by_id()
    cf_map      = load_custom_fields()
    lists       = load_lists()
    spaces      = load_spaces()
    stages      = load_workflow_stages()
    chks        = load_checklist_items()
    assignments = load_assignments()
    com_signals = load_comment_signals()

    print("\nBuilding product rows…")
    product_rows, checkpoint_rows = build_products(
        tasks, cf_map, lists, spaces, stages, chks, assignments, com_signals
    )
    print(f"  {len(product_rows):,} products assembled")
    print(f"  {len(checkpoint_rows):,} checkpoint rows assembled")

    print("\nClearing old data…")
    d1_exec("DELETE FROM products", [])
    d1_exec("DELETE FROM product_checkpoints", [])

    print("Writing products…")
    d1_bulk_insert(INSERT_PRODUCT, product_rows)
    print(f"  {len(product_rows):,} products written")

    print("Writing product_checkpoints…")
    PROGRESS = 5000
    for i in range(0, len(checkpoint_rows), PROGRESS):
        d1_bulk_insert(INSERT_PCHK, checkpoint_rows[i : i + PROGRESS])
        print(f"  …{min(i + PROGRESS, len(checkpoint_rows)):,} / {len(checkpoint_rows):,}")
    print(f"  {len(checkpoint_rows):,} checkpoint rows written")

    print("\n=== Summary (active, non-internal, open) ===")
    summary = d1_query(
        "SELECT stage_category, "
        "COUNT(*) as total, "
        "SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active, "
        "SUM(CASE WHEN is_overdue=1 THEN 1 ELSE 0 END) as overdue, "
        "ROUND(AVG(CASE WHEN is_active=1 THEN days_in_pipeline END),0) as avg_days "
        "FROM products WHERE status_type != 'closed' AND is_internal = 0 "
        "GROUP BY stage_category ORDER BY MIN(stage_order)"
    )
    print(f"  {'Stage':<22} {'Total':>6} {'Active':>7} {'Overdue':>8} {'Avg days':>9}")
    print(f"  {'-'*22} {'-'*6} {'-'*7} {'-'*8} {'-'*9}")
    for r in summary:
        print(f"  {(r['stage_category'] or 'Unknown'):<22} "
              f"{r['total']:>6} "
              f"{r['active']:>7} "
              f"{r['overdue']:>8} "
              f"{(r['avg_days'] or '?'):>9}")

    cov = d1_query(
        "SELECT ROUND(100.0*SUM(CASE WHEN assignee_count>0 THEN 1 END)/COUNT(*),1) as pct "
        "FROM products WHERE is_active=1 AND is_internal=0"
    )
    print(f"\n  Assignee coverage on active products: {(cov[0]['pct'] if cov else 0) or 0}%")

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    print(f"\n=== Done in {elapsed:.0f}s ===")


if __name__ == "__main__":
    main()
