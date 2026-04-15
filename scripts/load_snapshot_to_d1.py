#!/usr/bin/env python3
"""
load_snapshot_to_d1.py

Reads ClickUp workspace snapshot files from scripts/snapshot_output/ and loads
them into a Cloudflare D1 (SQLite) database via the D1 REST API.

Expected env vars:
    CLOUDFLARE_ACCOUNT_ID
    CLOUDFLARE_D1_DATABASE_ID
    CLOUDFLARE_API_TOKEN
    GH_TOKEN  (not used by this script directly, but available in the Actions env)
"""

import gzip
import json
import os
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKSPACE_ID = "2298436"
SOURCE = "snapshot"
BATCH_SIZE = 25          # max statements per D1 /batch request
PROGRESS_EVERY = 500     # print progress every N rows

ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "8303d11002766bf1cc36bf2f07ba6f20")
DATABASE_ID = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "c37aeb36-e16e-416b-b699-c910f6f8dc10")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")

BASE_URL = (
    f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
    f"/d1/database/{DATABASE_ID}"
)

SNAPSHOT_DIR = Path(__file__).parent / "snapshot_output"

KNOWN_LICENSORS = [
    "Disney", "Marvel", "Warner Bros", "WB", "Paramount", "SEGA",
    "Universal", "Nickelodeon", "DreamWorks", "Hasbro", "Mattel",
]

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def ms_to_iso(ts: Any) -> Optional[str]:
    """Convert a Unix-millisecond timestamp (string or int) to an ISO-8601 string."""
    if ts is None:
        return None
    try:
        ms = int(ts)
        if ms == 0:
            return None
        return datetime.utcfromtimestamp(ms / 1000).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Licensor extraction
# ---------------------------------------------------------------------------

def _resolve_dropdown_label(value: Any, type_config: Any) -> Optional[str]:
    """Resolve a dropdown value (int index or dict) to a human-readable label."""
    if type_config is None:
        return None
    options = type_config.get("options") if isinstance(type_config, dict) else None
    if not options:
        return None
    # value may be an integer index
    if isinstance(value, int):
        for opt in options:
            if opt.get("orderindex") == value or opt.get("order_index") == value:
                return opt.get("name") or opt.get("label")
        # fall back to positional index
        if 0 <= value < len(options):
            return options[value].get("name") or options[value].get("label")
    # value may be a dict with id/name
    if isinstance(value, dict):
        return value.get("name") or value.get("label")
    return None


def extract_licensor(task_name: str, custom_fields: list) -> Optional[str]:
    """Return licensor string if detectable from custom fields or task name."""
    for cf in custom_fields:
        fname = (cf.get("name") or "").lower()
        if "customer" in fname or "retailer" in fname or "licensor" in fname:
            val = cf.get("value")
            if val is None:
                continue
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, (dict, list)):
                label = _resolve_dropdown_label(val, cf.get("type_config"))
                if label:
                    return label.strip()
            if isinstance(val, int):
                label = _resolve_dropdown_label(val, cf.get("type_config"))
                if label:
                    return label.strip()
    # Fall back to task name keyword scan
    for lic in KNOWN_LICENSORS:
        if lic.lower() in task_name.lower():
            return lic
    return None


# Matches Windows absolute paths broadly — path components may contain spaces
# (e.g. "Warner Bros"), so we can't stop at the first whitespace.
# We use a broad initial match (stopping only at comma/newline/quote), then
# post-process to split on whitespace-before-new-drive-letter boundaries and
# strip trailing prose words.
_PATH_BROAD_RE = re.compile(r'[A-Z]:[\\\/][^,\n"]+')
# Lookahead split: whitespace before a new Windows drive-letter root
_DRIVE_SPLIT_RE = re.compile(r'\s+(?=[A-Z]:[\\\/])')
# Strip trailing prose connectors: sequences of spaces + all-alpha words (e.g. " and", " or")
_TRAIL_PROSE_RE = re.compile(r'(\s+[a-z]+)+\s*$', re.IGNORECASE)


def extract_file_paths(text: str) -> list:
    """Extract Windows-style file paths from a text string.

    Handles:
    - Spaces within path components (e.g. S:\\Warner Bros\\file.ai)
    - Multiple paths in one string separated by prose connectors (" and ", " or ")
    - Comma-delimited paths
    """
    if not text:
        return []
    raw_matches = _PATH_BROAD_RE.findall(text)
    results = []
    for raw in raw_matches:
        # Split on whitespace immediately before a new drive-letter path
        parts = _DRIVE_SPLIT_RE.split(raw)
        for p in parts:
            # Strip trailing prose words and punctuation
            p = _TRAIL_PROSE_RE.sub('', p)
            p = p.strip().rstrip(" \t.,;:)\"'")
            if p and re.match(r'[A-Z]:[\\\/]', p):
                results.append(p)
    return results


def licensor_from_path(path: str) -> Optional[str]:
    """If path starts with S:\\, return the first component after the drive."""
    if not path:
        return None
    # Normalise separators
    norm = path.replace("/", "\\")
    # Must start with S:\
    if not norm.upper().startswith("S:\\"):
        return None
    parts = norm.split("\\")
    if len(parts) >= 2 and parts[1]:
        candidate = parts[1].strip()
        for lic in KNOWN_LICENSORS:
            if lic.lower() == candidate.lower():
                return lic
        # Return raw first component anyway — it may be a licensor not in our list
        return candidate if candidate else None
    return None

# ---------------------------------------------------------------------------
# Custom-field value extraction
# ---------------------------------------------------------------------------

def extract_cf_value(cf: dict) -> dict:
    """
    Return a dict with keys: value_text, value_number, value_date, value_boolean.
    All keys are present; unused ones are None.
    """
    result = {"value_text": None, "value_number": None, "value_date": None, "value_boolean": None}
    ftype = (cf.get("type") or "").lower()
    val = cf.get("value")
    type_config = cf.get("type_config")

    if val is None:
        return result  # all None — caller should skip this row

    try:
        if ftype in ("number", "currency", "percentage"):
            result["value_number"] = float(val) if val != "" else None

        elif ftype == "date":
            if isinstance(val, (int, str)) and val != "":
                result["value_date"] = ms_to_iso(val)

        elif ftype == "checkbox":
            result["value_boolean"] = 1 if val else 0

        elif ftype in ("drop_down", "labels"):
            # Resolve to label string
            label = None
            if isinstance(val, int):
                label = _resolve_dropdown_label(val, type_config)
            elif isinstance(val, str):
                # Could be the label directly, or an ID — try to resolve
                label = _resolve_dropdown_label(val, type_config) or val
            elif isinstance(val, dict):
                label = val.get("name") or val.get("label") or _resolve_dropdown_label(val, type_config)
            elif isinstance(val, list):
                # labels: list of selected options
                labels = []
                for item in val:
                    if isinstance(item, dict):
                        labels.append(item.get("name") or item.get("label") or str(item))
                    else:
                        labels.append(str(item))
                label = ", ".join(l for l in labels if l)
            result["value_text"] = label

        elif ftype in ("text", "url", "email", "phone", "short_text", "textarea"):
            result["value_text"] = str(val) if val != "" else None

        else:
            # Unknown type — store as text if it's a string
            if isinstance(val, str) and val.strip():
                result["value_text"] = val.strip()
            elif isinstance(val, (int, float)):
                result["value_number"] = float(val)

    except Exception as exc:
        warnings.warn(f"CF value extraction failed for type={ftype} val={val!r}: {exc}")

    return result

# ---------------------------------------------------------------------------
# Comment parsing helpers
# ---------------------------------------------------------------------------

def parse_comment(comment: dict, task_id: str, fetched_at: str) -> Optional[dict]:
    """Parse a single ClickUp comment object into a row dict."""
    cid = comment.get("id")
    if not cid:
        return None

    text_content = comment.get("text_content") or ""
    user_obj = comment.get("user") or {}
    user_id = str(user_obj.get("id") or "")
    user_name = user_obj.get("username") or user_obj.get("email") or ""

    created_at = ms_to_iso(comment.get("date"))

    # Count @-mentions
    mention_count = text_content.count("@")

    # Count attachments in the comment parts array
    parts = comment.get("comment") or []
    attachment_count = sum(
        1 for p in parts if isinstance(p, dict) and p.get("type") == "attachment"
    )

    # Extract file paths
    file_paths = extract_file_paths(text_content)
    file_paths_str = "\n".join(file_paths) if file_paths else None

    # Licensor hint from S:\ paths
    licensor_hint = None
    for fp in file_paths:
        lh = licensor_from_path(fp)
        if lh:
            licensor_hint = lh
            break

    return {
        "id": cid,
        "task_id": task_id,
        "user_id": user_id or None,
        "user_name": user_name or None,
        "content": text_content or None,
        "comment_count": len(parts),
        "mention_count": mention_count,
        "attachment_count": attachment_count,
        "created_at": created_at,
        "updated_at": None,
        "fetched_at": fetched_at,
        "source": SOURCE,
        "file_paths": file_paths_str,
        "licensor_hint": licensor_hint,
    }

# ---------------------------------------------------------------------------
# D1 REST API client
# ---------------------------------------------------------------------------

def _cf_request(endpoint: str, payload: dict, retry: int = 5) -> dict:
    """
    POST a JSON payload to the Cloudflare D1 API endpoint (relative to BASE_URL).
    Handles HTTP 429 with exponential backoff.
    """
    url = f"{BASE_URL}/{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }

    for attempt in range(retry):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 2 ** attempt
                print(f"  [rate-limit] HTTP 429 — sleeping {wait}s (attempt {attempt+1}/{retry})")
                time.sleep(wait)
                continue
            # Read body for better error message
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = "(unreadable)"
            raise RuntimeError(
                f"D1 API error {exc.code} on {endpoint}: {err_body}"
            ) from exc
        except Exception as exc:
            if attempt < retry - 1:
                wait = 2 ** attempt
                print(f"  [error] {exc} — retrying in {wait}s")
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"Exhausted retries for D1 API call to {endpoint}")


def d1_query(sql: str, params: list) -> dict:
    return _cf_request("query", {"sql": sql, "params": [str(p) if isinstance(p, int) and not isinstance(p, bool) else p for p in params]})


def execute_batch(statements: list) -> None:
    """
    Execute a list of {"sql": ..., "params": [...]} dicts against D1.

    The D1 REST API only exposes /query (no /batch endpoint). To stay efficient
    we group consecutive statements that share the same SQL template into
    multi-row INSERTs, collapsing N individual calls into ~N/BATCH_SIZE calls.
    """
    if not statements:
        return

    # Group consecutive rows with the same SQL template
    groups: list = []
    for stmt in statements:
        sql = stmt["sql"]
        params = stmt["params"]
        if groups and groups[-1][0] == sql:
            groups[-1][1].append(params)
        else:
            groups.append([sql, [params]])

    for sql_template, rows_params in groups:
        # Split into chunks of BATCH_SIZE rows
        for i in range(0, len(rows_params), BATCH_SIZE):
            chunk = rows_params[i : i + BATCH_SIZE]
            try:
                _execute_multi_row(sql_template, chunk)
            except Exception as exc:
                warnings.warn(f"execute_batch error (rows {i}–{i+len(chunk)-1}): {exc}")


def _execute_multi_row(sql_template: str, rows: list) -> None:
    """
    Combine multiple rows with the same INSERT template into a single
    multi-row INSERT and send one /query request.

    sql_template looks like:
      INSERT OR REPLACE INTO t (a, b, c) VALUES (?, ?, ?)
    We expand it to:
      INSERT OR REPLACE INTO t (a, b, c) VALUES (?, ?, ?), (?, ?, ?), ...
    with a flat params list.
    """
    if not rows:
        return

    # Count placeholders in the template (one row's worth)
    n_cols = sql_template.count("?")

    if len(rows) == 1:
        # No expansion needed
        d1_query(sql_template, rows[0])
        return

    # Build the VALUES portion: repeat "(?, ?, ...)" for each row
    single_values = "(" + ", ".join(["?"] * n_cols) + ")"
    multi_values  = ", ".join([single_values] * len(rows))

    # Replace the last VALUES (...) in the template
    # Template ends with "VALUES (?, ?, ?)" — replace that suffix
    prefix = sql_template[:sql_template.rfind("VALUES")].rstrip()
    expanded_sql = f"{prefix} VALUES {multi_values}"

    # Flatten params
    flat_params: list = []
    for row in rows:
        flat_params.extend(row)

    d1_query(expanded_sql, flat_params)


# ---------------------------------------------------------------------------
# Snapshot file discovery
# ---------------------------------------------------------------------------

def latest_file(pattern_prefix: str) -> Optional[Path]:
    """Return the most-recently-named (by filename sort) .json.gz file matching prefix."""
    files = sorted(SNAPSHOT_DIR.glob(f"{pattern_prefix}*.json.gz"))
    return files[-1] if files else None


def load_gz_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)

# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_spaces(fetched_at: str) -> None:
    """Load spaces_{workspace_id}_*.json.gz into the spaces table."""
    path = latest_file(f"spaces_{WORKSPACE_ID}_")
    if path is None:
        print("[spaces] No snapshot file found — skipping.")
        return
    print(f"[spaces] Loading from {path.name}")

    try:
        data = load_gz_json(path)
    except Exception as exc:
        print(f"[spaces] Failed to load file: {exc}")
        return

    spaces = data if isinstance(data, list) else data.get("spaces", [])
    statements = []
    count = 0

    for sp in spaces:
        sid = sp.get("id")
        if not sid:
            continue
        try:
            statements.append({
                "sql": (
                    "INSERT OR REPLACE INTO spaces "
                    "(id, workspace_id, name, url, created_at, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)"
                ),
                "params": [
                    str(sid),
                    WORKSPACE_ID,
                    sp.get("name"),
                    sp.get("url") or sp.get("private"),  # url field varies
                    ms_to_iso(sp.get("date_joined") or sp.get("created")),
                    fetched_at,
                ],
            })
            count += 1
        except Exception as exc:
            warnings.warn(f"[spaces] Row error for id={sid}: {exc}")

    execute_batch(statements)
    print(f"[spaces] Upserted {count} rows.")


def load_members(fetched_at: str) -> None:
    """Load members_seats_{workspace_id}_*.json.gz into the users table."""
    path = latest_file(f"members_seats_{WORKSPACE_ID}_")
    if path is None:
        print("[members] No snapshot file found — skipping.")
        return
    print(f"[members] Loading from {path.name}")

    try:
        data = load_gz_json(path)
    except Exception as exc:
        print(f"[members] Failed to load file: {exc}")
        return

    # The members_seats API sometimes returns null (known ClickUp issue)
    if data is None:
        print("[members] File contains null data — API returned nothing, skipping.")
        return

    # Data may be a list of member objects or wrapped
    members = data if isinstance(data, list) else data.get("members", [])
    statements = []
    count = 0

    # Also upsert the workspace row while we have data
    ws_statements = [{
        "sql": (
            "INSERT OR REPLACE INTO workspaces (id, name, created_at, fetched_at) "
            "VALUES (?, ?, ?, ?)"
        ),
        "params": [WORKSPACE_ID, data.get("workspace_name") if isinstance(data, dict) else None, None, fetched_at],
    }]
    execute_batch(ws_statements)

    for m in members:
        user = m.get("user") or m  # member may wrap a user sub-object
        uid = user.get("id")
        if not uid:
            continue
        try:
            statements.append({
                "sql": (
                    "INSERT OR REPLACE INTO users "
                    "(id, workspace_id, username, email, color, profile_url, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)"
                ),
                "params": [
                    str(uid),
                    WORKSPACE_ID,
                    user.get("username"),
                    user.get("email"),
                    user.get("color"),
                    user.get("profile_picture") or user.get("profilePicture"),
                    fetched_at,
                ],
            })
            count += 1
            if count % PROGRESS_EVERY == 0:
                print(f"  [members] {count} rows queued…")
        except Exception as exc:
            warnings.warn(f"[members] Row error for id={uid}: {exc}")

    execute_batch(statements)
    print(f"[members] Upserted {count} rows.")


def load_tasks(fetched_at: str) -> None:
    """
    Load all tasks_list_{list_id}_*.json.gz files.
    Also populates: task_custom_fields, task_links, task_checklists,
                    checklist_items, task_tags, task_assignments.
    """
    task_files = sorted(SNAPSHOT_DIR.glob("tasks_list_*_*.json.gz"))
    if not task_files:
        # Try per-list latest only
        task_files = []
        for p in sorted(SNAPSHOT_DIR.glob("tasks_list_*.json.gz")):
            task_files.append(p)

    if not task_files:
        print("[tasks] No snapshot files found — skipping.")
        return

    # Deduplicate: for each list_id keep only the latest file
    by_list: dict = {}
    _list_re = re.compile(r"tasks_list_([^_]+)_")
    for p in task_files:
        m = _list_re.search(p.name)
        if m:
            lid = m.group(1)
            by_list[lid] = p  # sorted order means last wins (latest timestamp)

    print(f"[tasks] Found {len(by_list)} list file(s).")

    total_tasks = 0
    total_cfs = 0
    total_links = 0
    total_checklists = 0
    total_items = 0
    total_tags = 0
    total_assigns = 0

    for list_id, path in by_list.items():
        try:
            data = load_gz_json(path)
        except Exception as exc:
            warnings.warn(f"[tasks] Failed to load {path.name}: {exc}")
            continue

        list_name = data.get("list_name")
        space_id = data.get("space_id")
        tasks = data.get("tasks", [])

        # Ensure list row exists
        list_stmts = [{
            "sql": (
                "INSERT OR REPLACE INTO lists "
                "(id, space_id, folder_id, name, created_at, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            ),
            "params": [list_id, space_id, None, list_name, None, fetched_at],
        }]
        execute_batch(list_stmts)

        task_stmts = []
        cf_stmts = []
        link_stmts = []
        cl_stmts = []
        item_stmts = []
        tag_stmts = []
        assign_stmts = []

        for task in tasks:
            tid = task.get("id")
            if not tid:
                continue

            custom_fields = task.get("custom_fields") or []
            licensor = extract_licensor(task.get("name") or "", custom_fields)

            status_obj = task.get("status") or {}
            creator_obj = task.get("creator") or {}

            # ---- tasks row ----
            try:
                task_stmts.append({
                    "sql": (
                        "INSERT OR REPLACE INTO tasks "
                        "(id, list_id, parent_task_id, name, description, status, status_type, "
                        "priority, due_date, start_date, url, creator_id, created_at, updated_at, "
                        "closed_at, fetched_at, space_id, workspace_id, licensor) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    "params": [
                        tid,
                        list_id,
                        task.get("parent"),
                        task.get("name"),
                        task.get("description"),
                        status_obj.get("status"),
                        status_obj.get("type"),
                        task.get("priority"),
                        ms_to_iso(task.get("due_date")),
                        ms_to_iso(task.get("start_date")),
                        task.get("url"),
                        str(creator_obj.get("id")) if creator_obj.get("id") else None,
                        ms_to_iso(task.get("date_created")),
                        ms_to_iso(task.get("date_updated")),
                        ms_to_iso(task.get("date_closed")),
                        fetched_at,
                        space_id,
                        WORKSPACE_ID,
                        licensor,
                    ],
                })
                total_tasks += 1
                if total_tasks % PROGRESS_EVERY == 0:
                    print(f"  [tasks] {total_tasks} tasks queued…")
            except Exception as exc:
                warnings.warn(f"[tasks] Row error task_id={tid}: {exc}")

            # ---- custom fields ----
            for cf in custom_fields:
                fid = cf.get("id")
                if not fid:
                    continue
                try:
                    extracted = extract_cf_value(cf)
                    # Skip if all values are None (empty field)
                    if all(v is None for v in extracted.values()):
                        continue
                    cf_stmts.append({
                        "sql": (
                            "INSERT OR REPLACE INTO task_custom_fields "
                            "(task_id, field_id, field_name, field_type, "
                            "value_text, value_number, value_date, value_boolean, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                        ),
                        "params": [
                            tid,
                            fid,
                            cf.get("name"),
                            cf.get("type"),
                            extracted["value_text"],
                            extracted["value_number"],
                            extracted["value_date"],
                            extracted["value_boolean"],
                            ms_to_iso(task.get("date_updated")),
                        ],
                    })
                    total_cfs += 1
                except Exception as exc:
                    warnings.warn(f"[tasks] CF error task_id={tid} field_id={fid}: {exc}")

            # ---- linked tasks ----
            for link in (task.get("linked_tasks") or []):
                link_id = link.get("id")
                if not link_id:
                    continue
                try:
                    link_stmts.append({
                        "sql": (
                            "INSERT OR REPLACE INTO task_links "
                            "(id, task_id, linked_task_id, link_direction, link_type, "
                            "created_by, created_at, source) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                        ),
                        "params": [
                            link_id,
                            tid,
                            link.get("task_id") or link.get("linked_task_id"),
                            link.get("link_direction") or link.get("direction"),
                            link.get("link_type") or link.get("type"),
                            str(link.get("userid") or link.get("created_by") or ""),
                            ms_to_iso(link.get("date_created")),
                            SOURCE,
                        ],
                    })
                    total_links += 1
                except Exception as exc:
                    warnings.warn(f"[tasks] Link error task_id={tid}: {exc}")

            # ---- checklists + items ----
            for cl in (task.get("checklists") or []):
                cl_id = cl.get("id")
                if not cl_id:
                    continue
                try:
                    cl_stmts.append({
                        "sql": (
                            "INSERT OR REPLACE INTO task_checklists "
                            "(id, task_id, name, position, created_at, fetched_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)"
                        ),
                        "params": [
                            cl_id,
                            tid,
                            cl.get("name"),
                            cl.get("orderindex"),
                            ms_to_iso(cl.get("date_created")),
                            fetched_at,
                        ],
                    })
                    total_checklists += 1
                except Exception as exc:
                    warnings.warn(f"[tasks] Checklist error task_id={tid}: {exc}")

                for item in (cl.get("items") or []):
                    iid = item.get("id")
                    if not iid:
                        continue
                    try:
                        resolved_by_obj = item.get("resolved_by") or {}
                        item_stmts.append({
                            "sql": (
                                "INSERT OR REPLACE INTO checklist_items "
                                "(id, checklist_id, name, resolved, resolved_by, "
                                "resolved_at, position, fetched_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                            ),
                            "params": [
                                iid,
                                cl_id,
                                item.get("name"),
                                1 if item.get("resolved") else 0,
                                str(resolved_by_obj.get("id")) if resolved_by_obj.get("id") else None,
                                ms_to_iso(item.get("date_resolved")),
                                item.get("orderindex"),
                                fetched_at,
                            ],
                        })
                        total_items += 1
                    except Exception as exc:
                        warnings.warn(f"[tasks] Checklist item error: {exc}")

            # ---- tags ----
            for tag in (task.get("tags") or []):
                tag_name = tag.get("name") if isinstance(tag, dict) else str(tag)
                if not tag_name:
                    continue
                try:
                    # Use tag_name as tag_id since ClickUp tags don't have separate IDs
                    tag_id = tag_name.lower().replace(" ", "_")
                    tag_stmts.append({
                        "sql": (
                            "INSERT OR REPLACE INTO task_tags "
                            "(task_id, tag_id, tag_name, created_at) "
                            "VALUES (?, ?, ?, ?)"
                        ),
                        "params": [tid, tag_id, tag_name, fetched_at],
                    })
                    total_tags += 1
                except Exception as exc:
                    warnings.warn(f"[tasks] Tag error task_id={tid}: {exc}")

            # ---- assignees ----
            for assignee in (task.get("assignees") or []):
                aid = assignee.get("id") if isinstance(assignee, dict) else assignee
                if not aid:
                    continue
                try:
                    assign_stmts.append({
                        "sql": (
                            "INSERT OR REPLACE INTO task_assignments "
                            "(task_id, user_id, assigned_at, assigned_by, "
                            "unassigned_at, is_current, source) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)"
                        ),
                        "params": [
                            tid,
                            str(aid),
                            fetched_at,
                            None,
                            None,
                            1,
                            SOURCE,
                        ],
                    })
                    total_assigns += 1
                except Exception as exc:
                    warnings.warn(f"[tasks] Assignment error task_id={tid}: {exc}")

        # Flush all statement batches for this list file
        for name, stmts in [
            ("tasks", task_stmts),
            ("custom_fields", cf_stmts),
            ("links", link_stmts),
            ("checklists", cl_stmts),
            ("checklist_items", item_stmts),
            ("tags", tag_stmts),
            ("assignments", assign_stmts),
        ]:
            if stmts:
                try:
                    execute_batch(stmts)
                except Exception as exc:
                    warnings.warn(f"[tasks] Batch flush error ({name}) list={list_id}: {exc}")

    print(
        f"[tasks] Done. tasks={total_tasks}, custom_fields={total_cfs}, "
        f"links={total_links}, checklists={total_checklists}, items={total_items}, "
        f"tags={total_tags}, assignments={total_assigns}"
    )


def load_comments(fetched_at: str) -> None:
    """Load comments_sample_{workspace_id}_*.json.gz into task_comments."""
    path = latest_file(f"comments_sample_{WORKSPACE_ID}_")
    if path is None:
        print("[comments] No snapshot file found — skipping.")
        return
    print(f"[comments] Loading from {path.name}")

    try:
        data = load_gz_json(path)
    except Exception as exc:
        print(f"[comments] Failed to load file: {exc}")
        return

    # data is an array of {"task_id": ..., "task_name": ..., "comments": [...]}
    if not isinstance(data, list):
        data = [data]

    statements = []
    count = 0

    for entry in data:
        task_id = entry.get("task_id")
        if not task_id:
            continue
        for comment in (entry.get("comments") or []):
            try:
                row = parse_comment(comment, task_id, fetched_at)
                if row is None:
                    continue
                statements.append({
                    "sql": (
                        "INSERT OR REPLACE INTO task_comments "
                        "(id, task_id, user_id, user_name, content, comment_count, "
                        "mention_count, attachment_count, created_at, updated_at, "
                        "fetched_at, source, file_paths, licensor_hint) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    "params": [
                        row["id"],
                        row["task_id"],
                        row["user_id"],
                        row["user_name"],
                        row["content"],
                        row["comment_count"],
                        row["mention_count"],
                        row["attachment_count"],
                        row["created_at"],
                        row["updated_at"],
                        row["fetched_at"],
                        row["source"],
                        row["file_paths"],
                        row["licensor_hint"],
                    ],
                })
                count += 1
                if count % PROGRESS_EVERY == 0:
                    print(f"  [comments] {count} rows queued…")
            except Exception as exc:
                warnings.warn(f"[comments] Row error task_id={task_id}: {exc}")

    execute_batch(statements)
    print(f"[comments] Upserted {count} rows.")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not API_TOKEN:
        print("ERROR: CLOUDFLARE_API_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    if not SNAPSHOT_DIR.is_dir():
        print(f"ERROR: snapshot directory does not exist: {SNAPSHOT_DIR}", file=sys.stderr)
        sys.exit(1)

    fetched_at = now_iso()
    print(f"=== load_snapshot_to_d1.py starting at {fetched_at} ===")
    print(f"Snapshot dir : {SNAPSHOT_DIR}")
    print(f"D1 account   : {ACCOUNT_ID}")
    print(f"D1 database  : {DATABASE_ID}")
    print()

    load_spaces(fetched_at)
    print()
    load_members(fetched_at)
    print()
    load_tasks(fetched_at)
    print()
    load_comments(fetched_at)
    print()
    print("=== load_snapshot_to_d1.py complete ===")


if __name__ == "__main__":
    main()
