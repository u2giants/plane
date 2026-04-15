#!/usr/bin/env python3
"""
build_products_table.py

Rebuilds the `products` materialized table and `product_checkpoints` fact table
in D1 from current task data.

`products`          — One row per parent task (product), fully denormalized:
                      licensor, retailer, category, stage, pipeline age,
                      subtask counts, checklist completion, milestone flags.

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
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Optional
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
# Data loaders — pull tables into memory dicts
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
    """Returns {task_id: {field_name: value_text or value_number}}"""
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
    """Returns {list_id: list_name}"""
    rows = d1_query("SELECT id, name FROM lists")
    return {r["id"]: r["name"] for r in rows}


def load_spaces() -> dict:
    """Returns {space_id: space_name}"""
    rows = d1_query("SELECT id, name FROM spaces")
    return {r["id"]: r["name"] for r in rows}


def load_workflow_stages() -> dict:
    """Returns {status_raw: {stage_order, stage_name, stage_category}}"""
    rows = d1_query("SELECT status_raw, stage_order, stage_name, stage_category FROM workflow_stages")
    return {r["status_raw"]: r for r in rows}


def load_checklist_items() -> dict:
    """Returns {task_id: [(checklist_id, item_id, name, resolved, resolved_at, resolved_by)]}"""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def days_since(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return round((now - dt).total_seconds() / 86400, 1)
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
# Core build
# ---------------------------------------------------------------------------

INSERT_PRODUCT = (
    "INSERT OR REPLACE INTO products "
    "(id, name, licensor, retailer, product_category, put_up, factory, buyer, "
    "task_type, customer_program, sample_req_count, "
    "status, status_type, stage_order, stage_name, stage_category, "
    "list_id, list_name, space_id, space_name, "
    "created_at, updated_at, closed_at, due_date, start_date, "
    "days_in_current_status, days_in_pipeline, creator_id, "
    "subtask_count, subtask_closed_count, "
    "checklist_item_count, checklist_resolved_count, checklist_completion_pct, "
    "milestone_concept_approved, milestone_sample_approved, milestone_art_complete, "
    "milestone_pi_approved, milestone_tech_pack_checked, "
    "refreshed_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)

INSERT_PCHK = (
    "INSERT OR REPLACE INTO product_checkpoints "
    "(product_id, checklist_id, item_id, step_id, raw_name, resolved, resolved_at, resolved_by, refreshed_at) "
    "VALUES (?,?,?,?,?,?,?,?,?)"
)


def build_products(
    tasks: dict,
    cf_map: dict,
    lists: dict,
    spaces: dict,
    stages: dict,
    checklist_items: dict,
) -> tuple:
    """
    Returns (product_rows, checkpoint_rows) ready for bulk insert.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build subtask counts per parent
    subtask_counts: dict  = {}
    subtask_closed: dict  = {}
    for task in tasks.values():
        pid = task.get("parent_task_id")
        if pid:
            subtask_counts[pid] = subtask_counts.get(pid, 0) + 1
            if task.get("status_type") == "closed":
                subtask_closed[pid] = subtask_closed.get(pid, 0) + 1

    product_rows    = []
    checkpoint_rows = []

    parent_count = 0
    for tid, task in tasks.items():
        if task.get("parent_task_id") is not None:
            continue   # subtask — skip

        parent_count += 1
        stage = stages.get(task.get("status") or "", {})
        clist_items = checklist_items.get(tid, [])

        # --- Checklist aggregation ---
        n_items    = len(clist_items)
        n_resolved = sum(1 for ci in clist_items if ci.get("resolved"))

        # --- Milestone flags from resolved checklist items ---
        mil_concept   = 0
        mil_sample    = 0
        mil_art       = 0
        mil_pi        = 0
        mil_tech_pack = 0

        for ci in clist_items:
            if not ci.get("resolved"):
                continue
            step = classify_step(ci.get("name") or "")
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

            checkpoint_rows.append([
                tid,
                ci["checklist_id"],
                ci["item_id"],
                step,
                ci.get("name"),
                1 if ci.get("resolved") else 0,
                ci.get("resolved_at"),
                ci.get("resolved_by"),
                now_iso,
            ])

        # Add unresolved checklist items too
        for ci in clist_items:
            if ci.get("resolved"):
                continue
            step = classify_step(ci.get("name") or "")
            checkpoint_rows.append([
                tid,
                ci["checklist_id"],
                ci["item_id"],
                step,
                ci.get("name"),
                0,
                None,
                None,
                now_iso,
            ])

        # --- Custom fields ---
        retailer = get_cf(cf_map, tid, "🧑‍✈ Customer / Retailer", "customer")
        cat      = get_cf(cf_map, tid, "📚 Category")
        put_up   = get_cf(cf_map, tid, "put-up")
        factory  = get_cf(cf_map, tid, "🏭 Factory")
        buyer    = get_cf(cf_map, tid, "👤 Buyer")
        ttype    = get_cf(cf_map, tid, "Idea/Task Type")
        cprog    = get_cf(cf_map, tid, "cust program")
        smpl_req = get_cf(cf_map, tid, "SMPL Req")

        sub_cnt    = subtask_counts.get(tid, 0)
        sub_closed = subtask_closed.get(tid, 0)
        pct        = round(n_resolved / n_items * 100, 1) if n_items else None

        product_rows.append([
            tid,
            task.get("name"),
            task.get("licensor"),
            retailer,
            cat,
            put_up,
            factory,
            buyer,
            ttype,
            cprog,
            float(smpl_req) if smpl_req is not None else None,
            task.get("status"),
            task.get("status_type"),
            stage.get("stage_order"),
            stage.get("stage_name"),
            stage.get("stage_category"),
            task.get("list_id"),
            lists.get(task.get("list_id") or ""),
            task.get("space_id"),
            spaces.get(task.get("space_id") or ""),
            task.get("created_at"),
            task.get("updated_at"),
            task.get("closed_at"),
            task.get("due_date"),
            task.get("start_date"),
            days_since(task.get("updated_at")),
            days_since(task.get("created_at")),
            task.get("creator_id"),
            sub_cnt,
            sub_closed,
            n_items,
            n_resolved,
            pct,
            mil_concept,
            mil_sample,
            mil_art,
            mil_pi,
            mil_tech_pack,
            now_iso,
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

    # Load all source data
    tasks  = load_tasks_by_id()
    cf_map = load_custom_fields()
    lists  = load_lists()
    spaces = load_spaces()
    stages = load_workflow_stages()
    chks   = load_checklist_items()

    print("\nBuilding product rows…")
    product_rows, checkpoint_rows = build_products(tasks, cf_map, lists, spaces, stages, chks)
    print(f"  {len(product_rows):,} products assembled")
    print(f"  {len(checkpoint_rows):,} checkpoint rows assembled")

    # Clear and repopulate
    print("\nClearing old data…")
    d1_exec("DELETE FROM products", [])
    d1_exec("DELETE FROM product_checkpoints", [])

    print("Writing products…")
    d1_bulk_insert(INSERT_PRODUCT, product_rows)
    print(f"  {len(product_rows):,} products written")

    print("Writing product_checkpoints…")
    # Checkpoint rows can be large — batch in groups of 1000 to show progress
    PROGRESS = 5000
    for i in range(0, len(checkpoint_rows), PROGRESS):
        d1_bulk_insert(INSERT_PCHK, checkpoint_rows[i : i + PROGRESS])
        print(f"  …{min(i + PROGRESS, len(checkpoint_rows)):,} / {len(checkpoint_rows):,}")
    print(f"  {len(checkpoint_rows):,} checkpoint rows written")

    # Quick sanity summary
    print("\n=== Summary ===")
    summary = d1_query(
        "SELECT stage_category, COUNT(*) as cnt, "
        "ROUND(AVG(days_in_pipeline),0) as avg_days_in_pipeline "
        "FROM products WHERE status_type != 'closed' "
        "GROUP BY stage_category ORDER BY MIN(stage_order)"
    )
    for r in summary:
        print(f"  {(r['stage_category'] or 'Unknown'):20s}  "
              f"{r['cnt']:>5} products   "
              f"avg {r['avg_days_in_pipeline'] or '?':>6} days in pipeline")

    milestone_stats = d1_query(
        "SELECT "
        "  SUM(milestone_concept_approved) as concept_approved, "
        "  SUM(milestone_sample_approved)  as sample_approved, "
        "  SUM(milestone_art_complete)     as art_complete, "
        "  SUM(milestone_pi_approved)      as pi_approved, "
        "  COUNT(*) as total "
        "FROM products WHERE status_type != 'closed'"
    )
    if milestone_stats:
        r = milestone_stats[0]
        tot = r["total"] or 1
        print(f"\n  Active products with milestone reached (of {tot:,} active):")
        print(f"    Concept approved : {r['concept_approved']:>5,}")
        print(f"    Sample approved  : {r['sample_approved']:>5,}")
        print(f"    Art complete     : {r['art_complete']:>5,}")
        print(f"    PI approved      : {r['pi_approved']:>5,}")

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    print(f"\n=== Done in {elapsed:.0f}s ===")


if __name__ == "__main__":
    main()
