"""
ClickUp full workspace snapshot — optimized version.
Features: parallel API calls, resume capability, compression, D1 writes.
"""
import os
import json
import time
import sys
import gzip
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests

# ---------------------------------------------------------------------------
# Core config
# ---------------------------------------------------------------------------
TOKEN          = os.environ["CLICKUP_TOKEN"]
WORKSPACE      = os.environ["CLICKUP_WORKSPACE_ID"]
INCLUDE_CLOSED = os.environ.get("INCLUDE_CLOSED", "true").lower() == "true"
BASE           = "https://api.clickup.com/api/v2"
HEADERS        = {"Authorization": TOKEN}
OUT            = Path("snapshot_output")
OUT.mkdir(exist_ok=True)
RUN_TS         = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
MANIFEST_FILE  = OUT / "_manifest.json"
MAX_WORKERS    = 10
RETRY_DELAY    = 2

# ---------------------------------------------------------------------------
# Cloudflare D1 config (opt-in — all three vars must be set)
# ---------------------------------------------------------------------------
D1_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
D1_DB      = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "")
D1_TOKEN   = os.environ.get("CLOUDFLARE_API_TOKEN", "")
D1_ENABLED = bool(D1_ACCOUNT and D1_DB and D1_TOKEN)

D1_BASE    = f"https://api.cloudflare.com/client/v4/accounts/{D1_ACCOUNT}/d1/database/{D1_DB}"
D1_HEADERS = {"Authorization": f"Bearer {D1_TOKEN}", "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# Licensor lookup
# ---------------------------------------------------------------------------
KNOWN_LICENSORS = [
    "Disney", "Marvel", "Warner Bros", "WB", "Paramount", "SEGA",
    "Universal", "Nickelodeon", "DreamWorks", "Hasbro", "Mattel",
]

# ---------------------------------------------------------------------------
# Manifest (resume capability)
# ---------------------------------------------------------------------------
manifest_lock = Lock()

def load_manifest():
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text())
    return {}

def save_manifest(manifest):
    with manifest_lock:
        MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))

# ---------------------------------------------------------------------------
# ClickUp API helpers
# ---------------------------------------------------------------------------
def get(path, params=None, retries=5):
    url = BASE + path
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", RETRY_DELAY * (attempt + 1)))
                print(f"  Rate-limited on {path}, sleeping {wait}s …")
                time.sleep(wait)
                continue
            if r.status_code == 200:
                return r.json()
            print(f"  GET {path} → {r.status_code}: {r.text[:120]}", file=sys.stderr)
            return None
        except requests.RequestException as exc:
            print(f"  Request error {path}: {exc}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
    return None

# ---------------------------------------------------------------------------
# D1 write helper
# ---------------------------------------------------------------------------
def d1_batch(statements):
    """Execute a list of {"sql": ..., "params": [...]} dicts against D1. Batches of 25."""
    if not D1_ENABLED:
        return
    for i in range(0, len(statements), 25):
        chunk = statements[i:i + 25]
        for attempt in range(3):
            r = requests.post(
                f"{D1_BASE}/batch",
                headers=D1_HEADERS,
                json={"requests": chunk},
                timeout=30,
            )
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 15)))
                continue
            if r.status_code != 200:
                print(f"  D1 batch error {r.status_code}: {r.text[:200]}", file=sys.stderr)
            break

# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------
def ms_to_iso(ts):
    """Convert a ClickUp Unix-millisecond timestamp string to ISO-8601."""
    if not ts:
        return None
    try:
        return datetime.utcfromtimestamp(int(ts) / 1000).isoformat()
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Licensor extraction
# ---------------------------------------------------------------------------
def extract_licensor(task_name, custom_fields):
    """Return a licensor string from custom fields or task name, or None."""
    for cf in custom_fields:
        fname = (cf.get("name") or "").lower()
        if "customer" in fname or "retailer" in fname or "licensor" in fname:
            val = cf.get("value")
            if val:
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, dict):
                    return val.get("name") or val.get("label") or str(val)
    name_lower = task_name.lower()
    for lic in KNOWN_LICENSORS:
        if lic.lower() in name_lower:
            return lic
    return None

# ---------------------------------------------------------------------------
# Artifact save (gzip compressed JSON)
# ---------------------------------------------------------------------------
def save_compressed(data, filename):
    path = OUT / filename
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    return path

# ---------------------------------------------------------------------------
# Task fetching (all pages)
# ---------------------------------------------------------------------------
def fetch_all_tasks(list_id):
    tasks = []
    page = 0
    while True:
        params = {
            "page": page,
            "include_closed": str(INCLUDE_CLOSED).lower(),
            "subtasks": "true",
        }
        data = get(f"/list/{list_id}/task", params=params)
        if not data:
            break
        batch = data.get("tasks", [])
        tasks.extend(batch)
        if not batch or not data.get("last_page", False):
            # some ClickUp responses omit last_page; stop when we get an empty page
            if not batch:
                break
            if data.get("last_page") is True or data.get("last_page") == "true":
                break
            if len(batch) < 100:  # default page size
                break
        page += 1
        time.sleep(0.1)
    return tasks

# ---------------------------------------------------------------------------
# Comment fetching — ALL comments for ALL tasks (no sample limit)
# ---------------------------------------------------------------------------
def fetch_all_comments_for_list(tasks):
    """Fetch all comments for every task in a list."""
    all_comments = []
    for task in tasks:
        task_id = task["id"]
        comments = []
        start = None
        start_id = None
        while True:
            params = {}
            if start:
                params["start"] = start
            if start_id:
                params["start_id"] = start_id
            data = get(f"/task/{task_id}/comment", params=params)
            if not data:
                break
            batch = data.get("comments", [])
            comments.extend(batch)
            if len(batch) < 25:  # ClickUp default page size
                break
            # Cursor: use last comment's date and id
            last = batch[-1]
            start = last.get("date")
            start_id = last.get("id")
            time.sleep(0.2)
        if comments:
            all_comments.append({
                "task_id": task_id,
                "task_name": task.get("name", ""),
                "comments": comments,
            })
    return all_comments

# ---------------------------------------------------------------------------
# D1 — write tasks for a list
# ---------------------------------------------------------------------------
def d1_write_tasks(tasks, list_id, space_id):
    if not D1_ENABLED or not tasks:
        return
    stmts = []
    cf_stmts = []
    for task in tasks:
        cfs = task.get("custom_fields") or []
        licensor = extract_licensor(task.get("name", ""), cfs)
        status_obj = task.get("status") or {}
        priority_obj = task.get("priority") or {}
        creator_obj = task.get("creator") or {}

        stmts.append({
            "sql": (
                "INSERT OR REPLACE INTO tasks "
                "(id, list_id, parent_task_id, name, description, status, status_type, priority, "
                "due_date, start_date, url, creator_id, created_at, updated_at, closed_at, "
                "fetched_at, space_id, workspace_id, licensor) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?)"
            ),
            "params": [
                task.get("id"),
                list_id,
                task.get("parent"),
                task.get("name"),
                task.get("description"),
                status_obj.get("status"),
                status_obj.get("type"),
                priority_obj.get("priority"),
                ms_to_iso(task.get("due_date")),
                ms_to_iso(task.get("start_date")),
                task.get("url"),
                str(creator_obj.get("id", "")) or None,
                ms_to_iso(task.get("date_created")),
                ms_to_iso(task.get("date_updated")),
                ms_to_iso(task.get("date_closed")),
                space_id,
                WORKSPACE,
                licensor,
            ],
        })

        # Custom fields per task
        for cf in cfs:
            cf_val = cf.get("value")
            if cf_val is None:
                continue
            cf_type = (cf.get("type") or "").lower()
            value_number = None
            value_date = None
            value_boolean = None
            value_text = None

            if cf_type == "number":
                try:
                    value_number = float(cf_val)
                except (TypeError, ValueError):
                    value_text = str(cf_val)
            elif cf_type == "date":
                value_date = ms_to_iso(cf_val) if str(cf_val).isdigit() else str(cf_val)
            elif cf_type == "checkbox":
                if isinstance(cf_val, bool):
                    value_boolean = cf_val
                else:
                    value_boolean = str(cf_val).lower() in ("true", "1", "yes")
            else:
                if isinstance(cf_val, (dict, list)):
                    value_text = json.dumps(cf_val)
                else:
                    value_text = str(cf_val) if cf_val is not None else None

            cf_stmts.append({
                "sql": (
                    "INSERT OR REPLACE INTO task_custom_fields "
                    "(task_id, field_id, field_name, value_text, value_number, value_date, value_boolean) "
                    "VALUES (?,?,?,?,?,?,?)"
                ),
                "params": [
                    task.get("id"),
                    cf.get("id"),
                    cf.get("name"),
                    value_text,
                    value_number,
                    value_date,
                    value_boolean,
                ],
            })

    d1_batch(stmts)
    if cf_stmts:
        d1_batch(cf_stmts)

# ---------------------------------------------------------------------------
# D1 — write comments for a list
# ---------------------------------------------------------------------------
def d1_write_comments(all_comments):
    if not D1_ENABLED or not all_comments:
        return
    stmts = []
    for entry in all_comments:
        task_id = entry["task_id"]
        for c in entry.get("comments", []):
            text = c.get("comment_text", "")
            if isinstance(text, list):
                # ClickUp sometimes returns rich-text blocks
                text = " ".join(
                    (block.get("text") or "") for block in text if isinstance(block, dict)
                )
            user_obj = c.get("user") or {}
            stmts.append({
                "sql": (
                    "INSERT OR REPLACE INTO task_comments "
                    "(id, task_id, comment_text, user_id, date) "
                    "VALUES (?,?,?,?,?)"
                ),
                "params": [
                    c.get("id"),
                    task_id,
                    text,
                    str(user_obj.get("id", "")) or None,
                    ms_to_iso(c.get("date")),
                ],
            })
    d1_batch(stmts)

# ---------------------------------------------------------------------------
# D1 — write custom field definitions for a list
# ---------------------------------------------------------------------------
def d1_write_field_defs(field_defs, list_id):
    if not D1_ENABLED or not field_defs:
        return
    stmts = []
    for f in field_defs:
        type_config = f.get("type_config")
        stmts.append({
            "sql": (
                "INSERT OR REPLACE INTO custom_field_definitions "
                "(field_id, list_id, name, type, type_config) "
                "VALUES (?,?,?,?,?)"
            ),
            "params": [
                f.get("id"),
                list_id,
                f.get("name"),
                f.get("type"),
                json.dumps(type_config) if type_config is not None else None,
            ],
        })
    d1_batch(stmts)

# ---------------------------------------------------------------------------
# Process a single list (called in thread pool)
# ---------------------------------------------------------------------------
def process_list_parallel(lid, list_name, space_id, manifest):
    """Fetch tasks, comments, and field defs for one list; save artifacts; write to D1."""
    list_key = f"list_{lid}"

    # Resume: skip if already completed in a previous run
    if manifest.get(list_key, {}).get("status") == "done":
        print(f"  Skipping list '{list_name}' (already captured)")
        return {"list_id": lid, "list_name": list_name, "skipped": True}

    print(f"  Processing list '{list_name}' ({lid}) …")

    # --- Tasks ---
    tasks = fetch_all_tasks(lid)
    print(f"    {len(tasks)} tasks fetched for '{list_name}'")

    tasks_file = f"tasks_{lid}_{RUN_TS}.json.gz"
    save_compressed({"list_id": lid, "list_name": list_name, "tasks": tasks}, tasks_file)

    if D1_ENABLED:
        d1_write_tasks(tasks, lid, space_id)
        print(f"  D1: wrote {len(tasks)} tasks for list {list_name}")

    # --- Comments (ALL tasks, no sample limit) ---
    all_comments = fetch_all_comments_for_list(tasks)
    total_comments = sum(len(e["comments"]) for e in all_comments)
    print(f"    {total_comments} comments fetched for '{list_name}'")

    comments_file = f"comments_{lid}_{RUN_TS}.json.gz"
    save_compressed({"list_id": lid, "list_name": list_name, "comment_data": all_comments}, comments_file)

    if D1_ENABLED:
        d1_write_comments(all_comments)
        print(f"  D1: wrote {total_comments} comments for list {list_name}")

    # --- Custom field definitions per list ---
    fields_data = get(f"/list/{lid}/field")
    field_defs = fields_data.get("fields", []) if fields_data else []
    print(f"    {len(field_defs)} custom field definitions for '{list_name}'")

    fields_file = f"fields_{lid}_{RUN_TS}.json.gz"
    save_compressed({"list_id": lid, "list_name": list_name, "field_definitions": field_defs}, fields_file)

    if D1_ENABLED:
        d1_write_field_defs(field_defs, lid)
        print(f"  D1: wrote {len(field_defs)} field definitions for list {list_name}")

    # Mark done in manifest
    result = {
        "list_id": lid,
        "list_name": list_name,
        "task_count": len(tasks),
        "comment_count": total_comments,
        "field_def_count": len(field_defs),
        "tasks_file": tasks_file,
        "comments_file": comments_file,
        "fields_file": fields_file,
        "status": "done",
    }
    manifest[list_key] = result
    save_manifest(manifest)
    return result

# ---------------------------------------------------------------------------
# Workspace traversal helpers
# ---------------------------------------------------------------------------
def fetch_spaces():
    data = get(f"/team/{WORKSPACE}/space", params={"archived": "false"})
    return data.get("spaces", []) if data else []

def fetch_folders(space_id):
    data = get(f"/space/{space_id}/folder", params={"archived": "false"})
    return data.get("folders", []) if data else []

def fetch_folderless_lists(space_id):
    data = get(f"/space/{space_id}/list", params={"archived": "false"})
    return data.get("lists", []) if data else []

def fetch_folder_lists(folder_id):
    data = get(f"/folder/{folder_id}/list", params={"archived": "false"})
    return data.get("lists", []) if data else []

def collect_all_lists():
    """Return a flat list of (list_id, list_name, space_id) tuples."""
    all_lists = []
    spaces = fetch_spaces()
    print(f"Found {len(spaces)} spaces")
    for space in spaces:
        sid = space["id"]
        sname = space.get("name", sid)

        # Folderless lists
        for lst in fetch_folderless_lists(sid):
            all_lists.append((lst["id"], lst.get("name", lst["id"]), sid))

        # Folder → lists
        for folder in fetch_folders(sid):
            for lst in fetch_folder_lists(folder["id"]):
                all_lists.append((lst["id"], lst.get("name", lst["id"]), sid))

        print(f"  Space '{sname}': collected list IDs so far = {len(all_lists)}")

    return all_lists

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"=== ClickUp snapshot started {RUN_TS} ===")
    if D1_ENABLED:
        print("D1 integration ENABLED — data will be written to Cloudflare D1")
    else:
        print("D1 integration DISABLED — set CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_D1_DATABASE_ID, "
              "CLOUDFLARE_API_TOKEN to enable")

    manifest = load_manifest()

    # Collect all lists across the workspace
    all_lists = collect_all_lists()
    print(f"\nTotal lists to process: {len(all_lists)}")

    # Write workspace-level summary to D1
    if D1_ENABLED:
        d1_batch([{
            "sql": (
                "INSERT OR REPLACE INTO workspace_snapshots "
                "(workspace_id, run_ts, list_count, status) "
                "VALUES (?,?,?,'running')"
            ),
            "params": [WORKSPACE, RUN_TS, len(all_lists)],
        }])

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_list_parallel, lid, lname, sid, manifest): (lid, lname)
            for lid, lname, sid in all_lists
        }
        for future in as_completed(futures):
            lid, lname = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                print(f"  ERROR processing list '{lname}' ({lid}): {exc}", file=sys.stderr)
                results.append({"list_id": lid, "list_name": lname, "status": "error", "error": str(exc)})

    # Save top-level summary artifact
    summary = {
        "run_ts": RUN_TS,
        "workspace_id": WORKSPACE,
        "total_lists": len(all_lists),
        "results": results,
    }
    save_compressed(summary, f"summary_{RUN_TS}.json.gz")

    # Mark snapshot complete in D1
    if D1_ENABLED:
        d1_batch([{
            "sql": (
                "INSERT OR REPLACE INTO workspace_snapshots "
                "(workspace_id, run_ts, list_count, status) "
                "VALUES (?,?,?,'complete')"
            ),
            "params": [WORKSPACE, RUN_TS, len(all_lists)],
        }])

    done = sum(1 for r in results if r.get("status") == "done")
    skipped = sum(1 for r in results if r.get("skipped"))
    errors = sum(1 for r in results if r.get("status") == "error")
    print(f"\n=== Snapshot complete: {done} done, {skipped} skipped, {errors} errors ===")


if __name__ == "__main__":
    main()
