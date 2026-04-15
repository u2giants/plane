#!/usr/bin/env python3
"""
fetch_task_activity.py

Populates status_transitions in D1 from two sources:

  1. SYNTHESIZED (default, fast):
     Reads task snapshot files already on disk. For each task writes one
     'estimated' transition record: task entered its CURRENT status at
     approximately date_updated.  No ClickUp API calls required.

  2. HISTORICAL (optional, slow, add --fetch-history flag):
     Calls GET /api/v2/task/{taskId}/history for each task and writes
     real status-change events (source='api_history').  Subject to
     ClickUp's 100 req/min rate limit — plan ~3 hrs for 17 k tasks.
     Falls back to synthesized automatically if the endpoint is unavailable.

Usage:
    # Fast synthesized pass (minutes):
    python fetch_task_activity.py

    # Full historical pass (hours, requires CLICKUP_TOKEN):
    python fetch_task_activity.py --fetch-history

    # Process one list only (useful for testing):
    python fetch_task_activity.py --fetch-history --list-id 901802738119

Env vars:
    CLOUDFLARE_ACCOUNT_ID       (required)
    CLOUDFLARE_D1_DATABASE_ID   (required)
    CLOUDFLARE_API_TOKEN        (required)
    CLICKUP_TOKEN               (required only with --fetch-history)
"""

import argparse
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

WORKSPACE_ID    = "2298436"
CLICKUP_BASE    = "https://api.clickup.com/api/v2"
RATE_LIMIT      = 100          # ClickUp requests per minute
RATE_WINDOW     = 60.0         # seconds
CHECKPOINT_EVERY = 200         # tasks between checkpoints
D1_MAX_PARAMS   = 90

ACCOUNT_ID  = os.environ.get("CLOUDFLARE_ACCOUNT_ID",  "8303d11002766bf1cc36bf2f07ba6f20")
DATABASE_ID = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "c37aeb36-e16e-416b-b699-c910f6f8dc10")
CF_TOKEN    = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CU_TOKEN    = os.environ.get("CLICKUP_TOKEN", "")

SCRIPT_DIR   = Path(__file__).parent
SNAPSHOT_DIR = SCRIPT_DIR / "snapshot_output"
CHECKPOINT   = SCRIPT_DIR / "_activity_checkpoint.json"

D1_BASE = (
    f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
    f"/d1/database/{DATABASE_ID}"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ms_to_iso(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    try:
        ms = int(ts)
        return datetime.utcfromtimestamp(ms / 1000).isoformat() if ms else None
    except Exception:
        return None


def load_gz_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Rate limiter (token bucket)
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, calls_per_minute: int):
        self._interval = RATE_WINDOW / calls_per_minute
        self._last = 0.0

    def wait(self):
        elapsed = time.monotonic() - self._last
        gap = self._interval - elapsed
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


_rl = RateLimiter(RATE_LIMIT)

# ---------------------------------------------------------------------------
# D1 REST client
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
                    err = data.get("errors", ["(unknown)"])
                    raise RuntimeError(f"D1 error: {err}")
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
        except Exception as exc:
            if attempt < retry - 1:
                time.sleep(2 ** attempt)
            else:
                raise
    raise RuntimeError("D1 retries exhausted")


def d1_exec(sql: str, params: list) -> None:
    clean = [str(p) if isinstance(p, int) and not isinstance(p, bool) else p
             for p in params]
    _d1_request({"sql": sql, "params": clean})


def d1_bulk_insert(sql_template: str, rows: list) -> None:
    """Multi-row INSERT respecting D1 param limit."""
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

# ---------------------------------------------------------------------------
# ClickUp REST client
# ---------------------------------------------------------------------------

def cu_get(path: str, params: dict = None) -> dict:
    """GET from ClickUp API with rate limiting."""
    _rl.wait()
    url = f"{CLICKUP_BASE}{path}"
    if params:
        qs  = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": CU_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            wait = int(exc.headers.get("Retry-After", "60"))
            print(f"  [ClickUp rate-limit] sleeping {wait}s")
            time.sleep(wait)
            return cu_get(path, params)   # one retry
        raise RuntimeError(f"ClickUp HTTP {exc.code}: {exc.read().decode()[:200]}") from exc

# ---------------------------------------------------------------------------
# Snapshot reader
# ---------------------------------------------------------------------------

def iter_snapshot_tasks(list_id_filter: Optional[str] = None):
    """Yield (list_id, task_dict) from every tasks_list_*.json.gz file."""
    _re = re.compile(r"tasks_list_([^_]+)_")
    seen: dict = {}
    for p in sorted(SNAPSHOT_DIR.glob("tasks_list_*.json.gz")):
        m = _re.search(p.name)
        if not m:
            continue
        lid = m.group(1)
        seen[lid] = p          # last one wins (latest timestamp)

    for lid, path in seen.items():
        if list_id_filter and lid != list_id_filter:
            continue
        try:
            data  = load_gz_json(path)
            tasks = data.get("tasks", [])
            sid   = data.get("space_id")
            for t in tasks:
                t["_space_id"] = sid   # stash for transition row
                yield lid, t
        except Exception as exc:
            warnings.warn(f"Failed to read {path.name}: {exc}")

# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def load_checkpoint() -> set:
    if CHECKPOINT.exists():
        try:
            return set(json.loads(CHECKPOINT.read_text()))
        except Exception:
            pass
    return set()


def save_checkpoint(done: set) -> None:
    CHECKPOINT.write_text(json.dumps(sorted(done)))

# ---------------------------------------------------------------------------
# Core: synthesized transitions
# ---------------------------------------------------------------------------

INSERT_TRANSITION = (
    "INSERT OR IGNORE INTO status_transitions "
    "(task_id, from_status, to_status, from_status_type, to_status_type, "
    "user_id, user_name, list_id, space_id, workspace_id, event_id, "
    "transitioned_at, source) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def build_synthesized_row(task: dict, list_id: str) -> list:
    """One estimated transition: task entered current status ≈ date_updated."""
    status_obj = task.get("status") or {}
    return [
        task["id"],
        None,                              # from_status unknown
        status_obj.get("status"),
        None,                              # from_status_type unknown
        status_obj.get("type"),
        None, None,                        # user_id, user_name
        list_id,
        task.get("_space_id"),
        WORKSPACE_ID,
        None,                              # event_id
        ms_to_iso(task.get("date_updated") or task.get("date_created")),
        "estimated",
    ]


def run_synthesized(list_id_filter: Optional[str]) -> int:
    """
    Write one 'estimated' transition per task from snapshot files.
    Fast — no API calls.
    """
    print("[synthesized] Reading snapshot files…")

    # Clear previous estimated records for a clean re-run
    print("[synthesized] Clearing old estimated transitions…")
    if list_id_filter:
        d1_exec("DELETE FROM status_transitions WHERE source='estimated' AND list_id=?",
                [list_id_filter])
    else:
        d1_exec("DELETE FROM status_transitions WHERE source='estimated'", [])

    rows  = []
    total = 0
    for lid, task in iter_snapshot_tasks(list_id_filter):
        tid = task.get("id")
        if not tid:
            continue
        rows.append(build_synthesized_row(task, lid))
        total += 1
        if len(rows) >= 200:
            d1_bulk_insert(INSERT_TRANSITION, rows)
            rows = []
        if total % 1000 == 0:
            print(f"  [synthesized] {total} tasks processed…")

    if rows:
        d1_bulk_insert(INSERT_TRANSITION, rows)

    print(f"[synthesized] Done — wrote {total} estimated transition records.")
    return total

# ---------------------------------------------------------------------------
# Core: real history via ClickUp API
# ---------------------------------------------------------------------------

def parse_history_items(task_id: str, list_id: str, space_id: Optional[str],
                         history: list) -> list:
    """Convert ClickUp history_items to status_transitions rows."""
    rows = []
    for item in history:
        if item.get("field") != "status":
            continue
        before = item.get("before") or {}
        after  = item.get("after")  or {}
        user   = item.get("user")   or {}
        rows.append([
            task_id,
            before.get("status") if isinstance(before, dict) else str(before),
            after.get("status")  if isinstance(after,  dict) else str(after),
            before.get("type")   if isinstance(before, dict) else None,
            after.get("type")    if isinstance(after,  dict) else None,
            str(user.get("id") or "") or None,
            user.get("username") or user.get("email"),
            list_id,
            space_id,
            WORKSPACE_ID,
            item.get("id"),
            ms_to_iso(item.get("date")),
            "api_history",
        ])
    return rows


def probe_history_endpoint(task_id: str) -> Optional[list]:
    """
    Try to fetch task history from ClickUp API.
    Returns list of history items, or None if endpoint unavailable.
    """
    try:
        resp = cu_get(f"/task/{task_id}/history")
        # ClickUp may return {"history": [...]} or {"items": [...]}
        items = resp.get("history") or resp.get("items") or []
        return items
    except RuntimeError as exc:
        msg = str(exc)
        if "404" in msg or "400" in msg:
            return None      # endpoint doesn't exist
        raise


def run_historical(list_id_filter: Optional[str]) -> int:
    """
    Fetch real status-change history from ClickUp API per task.
    Writes source='api_history' records.
    Checkpoints every CHECKPOINT_EVERY tasks.
    """
    if not CU_TOKEN:
        print("[history] ERROR: CLICKUP_TOKEN not set — skipping historical fetch.")
        return 0

    done      = load_checkpoint()
    total_new = 0
    probed    = False
    hist_available = True

    print(f"[history] Starting — {len(done)} tasks already in checkpoint.")

    for lid, task in iter_snapshot_tasks(list_id_filter):
        tid = task.get("id")
        if not tid or tid in done:
            continue

        if not probed:
            probed = True
            print(f"[history] Probing endpoint with task {tid}…")
            result = probe_history_endpoint(tid)
            if result is None:
                hist_available = False
                print("[history] /task/{id}/history not available — falling back to synthesized only.")
            else:
                print(f"[history] Endpoint available (got {len(result)} items for probe task).")
                if result:
                    rows = parse_history_items(tid, lid, task.get("_space_id"), result)
                    if rows:
                        d1_bulk_insert(INSERT_TRANSITION, rows)
                        total_new += len(rows)
            done.add(tid)
            continue

        if not hist_available:
            break      # no point continuing

        try:
            items = probe_history_endpoint(tid)
            if items:
                rows = parse_history_items(tid, lid, task.get("_space_id"), items)
                if rows:
                    d1_bulk_insert(INSERT_TRANSITION, rows)
                    total_new += len(rows)
        except Exception as exc:
            warnings.warn(f"[history] task {tid}: {exc}")

        done.add(tid)

        if len(done) % CHECKPOINT_EVERY == 0:
            save_checkpoint(done)
            print(f"  [history] checkpoint: {len(done)} tasks, {total_new} transitions written")

    save_checkpoint(done)
    print(f"[history] Done — {total_new} api_history transition records written.")
    return total_new

# ---------------------------------------------------------------------------
# Summary query
# ---------------------------------------------------------------------------

def print_summary() -> None:
    data = _d1_request({
        "sql": (
            "SELECT source, COUNT(*) as cnt "
            "FROM status_transitions GROUP BY source"
        ),
        "params": [],
    })
    rows = data["result"][0]["results"] if data.get("result") else []
    print("\n[summary] status_transitions breakdown:")
    for r in rows:
        print(f"  {r['source']:20s}  {r['cnt']:>6,} rows")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch-history", action="store_true",
                        help="Also call ClickUp /task/{id}/history API for real transitions")
    parser.add_argument("--list-id", default=None,
                        help="Only process this list ID (for testing)")
    parser.add_argument("--skip-synthesized", action="store_true",
                        help="Skip the synthesized pass (only run history fetch)")
    args = parser.parse_args()

    if not CF_TOKEN:
        print("ERROR: CLOUDFLARE_API_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    if not SNAPSHOT_DIR.is_dir():
        print(f"ERROR: snapshot directory not found: {SNAPSHOT_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"=== fetch_task_activity.py starting at {now_iso()} ===")
    print(f"D1 database  : {DATABASE_ID}")
    print(f"Snapshot dir : {SNAPSHOT_DIR}")
    print(f"Fetch history: {args.fetch_history}")
    print(f"List filter  : {args.list_id or '(all)'}")
    print()

    if not args.skip_synthesized:
        run_synthesized(args.list_id)
        print()

    if args.fetch_history:
        run_historical(args.list_id)
        print()

    print_summary()
    print(f"\n=== fetch_task_activity.py complete ===")


if __name__ == "__main__":
    main()
