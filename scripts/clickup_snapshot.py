"""
ClickUp full workspace snapshot — optimized version.
Features: parallel API calls, resume capability, compression.

Run via GitHub Actions (workflows/clickup-snapshot.yml) or locally:
  CLICKUP_TOKEN=pk_xxx CLICKUP_WORKSPACE_ID=2298436 python clickup_snapshot.py
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

TOKEN            = os.environ["CLICKUP_TOKEN"]
WORKSPACE        = os.environ["CLICKUP_WORKSPACE_ID"]
INCLUDE_CLOSED   = os.environ.get("INCLUDE_CLOSED", "true").lower() == "true"
BASE             = "https://api.clickup.com/api/v2"
HEADERS          = {"Authorization": TOKEN}
OUT              = Path("snapshot_output")
OUT.mkdir(exist_ok=True)
RUN_TS           = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
MANIFEST_FILE    = OUT / "_manifest.json"

# Configuration
COMMENT_SAMPLE_SIZE = 200
MAX_WORKERS = 10  # Parallel API calls
RETRY_DELAY = 2   # Seconds between retries


def get(path, params=None, retries=3, retry_delay=RETRY_DELAY):
    """Fetch with retries and exponential backoff."""
    url = f"{BASE}{path}"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 15))
                print(f"  Rate limited — waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"  ERROR {url}: {e}", file=sys.stderr)
                return None
            time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
    return None


def save(name, data, compress=True):
    """Save JSON with optional gzip compression."""
    fname = OUT / f"{name}_{RUN_TS}.json"
    fname_gz = fname.with_suffix('.json.gz')
    
    if compress:
        with gzip.open(fname_gz, 'wt', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        size = fname_gz.stat().st_size
        print(f"  ✓ {fname_gz.name}  ({size:,} bytes compressed)", flush=True)
        return fname_gz
    else:
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        size = fname.stat().st_size
        print(f"  ✓ {fname.name}  ({size:,} bytes)", flush=True)
        return fname


def save_compressed(name, data):
    """Alias for save with compression."""
    return save(name, data, compress=True)


def load_manifest():
    """Load existing manifest for resume capability."""
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, 'r') as f:
            return json.load(f)
    return None


def save_manifest(manifest):
    """Save manifest for tracking progress."""
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(manifest, f, indent=2)


def mark_list_done(list_id, manifest):
    """Mark a list as processed (for resume)."""
    if 'completed_lists' not in manifest:
        manifest['completed_lists'] = []
    manifest['completed_lists'].append(list_id)
    save_manifest(manifest)


def get_tasks_paged(list_id, include_closed):
    """Fetch all tasks from a list with pagination."""
    tasks = []
    page = 0
    while True:
        params = {
            "subtasks": "true",
            "include_closed": str(include_closed).lower(),
            "page": page,
        }
        data = get(f"/list/{list_id}/task", params=params)
        if not data:
            break
        batch = data.get("tasks", [])
        tasks.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.2)
    return tasks


def process_list_parallel(args):
    """Process a single list - for parallel execution."""
    lst, space_id, include_closed, = args
    lid, lname = lst["id"], lst["name"]
    
    try:
        tasks = get_tasks_paged(lid, include_closed)
        linked = extract_linked_tasks(tasks)
        checklists = extract_checklists(tasks)
        
        return {
            'list_id': lid,
            'list_name': lname,
            'space_id': space_id,
            'tasks': tasks,
            'linked': linked,
            'checklists': checklists,
            'success': True
        }
    except Exception as e:
        print(f"  ✗ Failed list {lname}: {e}", flush=True)
        return {'list_id': lid, 'success': False, 'error': str(e)}


def extract_linked_tasks(tasks):
    """Pull linked task relationships from task payloads."""
    linked = []
    for t in tasks:
        for link in t.get("linked_tasks", []):
            linked.append({
                "task_id":        t["id"],
                "task_name":      t.get("name", ""),
                "linked_task_id": link.get("task_id", ""),
                "link_id":        link.get("link_id", ""),
                "date_created":   link.get("date_created", ""),
                "user_id":        link.get("userid", ""),
            })
    return linked


def extract_checklists(tasks):
    """Pull checklist data embedded in task payloads."""
    result = []
    for t in tasks:
        for cl in t.get("checklists", []):
            result.append({
                "task_id":   t["id"],
                "task_name": t.get("name", ""),
                "checklist": cl,
            })
    return result


def main():
    print(f"\n=== ClickUp Optimized Snapshot  workspace={WORKSPACE}  ts={RUN_TS} ===\n", flush=True)
    print(f"Parallel workers: {MAX_WORKERS}", flush=True)

    # Check for resume
    manifest = load_manifest()
    if manifest:
        print(f"Resuming from previous run ({len(manifest.get('completed_lists', []))} lists done)", flush=True)
    else:
        manifest = {
            "snapshot_ts": RUN_TS,
            "workspace_id": WORKSPACE,
            "include_closed": INCLUDE_CLOSED,
            "comment_sample": COMMENT_SAMPLE_SIZE,
            "completed_lists": [],
            "files": []
        }

    # Fetch workspace
    print("Fetching workspaces...", flush=True)
    teams_data = get("/team")
    if not teams_data:
        sys.exit("Could not fetch workspaces — check CLICKUP_TOKEN")
    teams = teams_data.get("teams", [])
    
    # Save manifest first (for resume on crash)
    save_manifest(manifest)

    for team in teams:
        tid = team["id"]
        if tid != WORKSPACE:
            continue

        print(f"\n→ Workspace: {team['name']} ({tid})", flush=True)

        # Fetch all static data (sequential - small payloads)
        print("  Fetching workspace data...", flush=True)
        
        # Members, fields, goals, views, time, docs (parallelize small requests)
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(get, f"/team/{tid}/seat"): "members",
                executor.submit(get, f"/team/{tid}/field"): "fields",
                executor.submit(get, f"/team/{tid}/goal"): "goals",
                executor.submit(get, f"/team/{tid}/view"): "views",
                executor.submit(get, f"/team/{tid}/page"): "docs",
            }
            
            now_ms   = int(datetime.utcnow().timestamp() * 1000)
            start_ms = int((datetime.utcnow() - timedelta(days=90)).timestamp() * 1000)
            futures[executor.submit(get, f"/team/{tid}/time_entries", 
                          params={"start_date": start_ms, "end_date": now_ms})] = "time"
            
            for future in as_completed(futures):
                name = futures[future]
                try:
                    data = future.result()
                    if name == "members": save_compressed(f"members_seats_{tid}", data)
                    elif name == "fields": save_compressed(f"custom_fields_{tid}", data)
                    elif name == "goals": save_compressed(f"goals_{tid}", data)
                    elif name == "views": save_compressed(f"views_workspace_{tid}", data)
                    elif name == "time": save_compressed(f"time_tracking_{tid}", data)
                    elif name == "docs": 
                        if data: save_compressed(f"docs_{tid}", data)
                        else: print("    (docs not available on this plan tier)")
                except Exception as e:
                    print(f"  ✗ Failed {name}: {e}", flush=True)

        # Fetch spaces
        print("  Spaces...", flush=True)
        spaces_data = get(f"/team/{tid}/space", params={"archived": "false"})
        spaces = spaces_data.get("spaces", []) if spaces_data else []
        save_compressed(f"spaces_{tid}", spaces)

        # Collect all lists to process
        all_lists_to_process = []
        completed_lists = set(manifest.get('completed_lists', []))
        
        for space in spaces:
            sid = space["id"]
            print(f"\n  Space: {space['name']} ({sid})", flush=True)

            # Tags and views (parallel)
            with ThreadPoolExecutor(max_workers=2) as executor:
                executor.submit(lambda s: save_compressed(f"tags_space_{s}", get(f"/space/{s}/tag")), sid)
                executor.submit(lambda s: save_compressed(f"views_space_{s}", get(f"/space/{s}/view")), sid)

            # Folders
            folders_data = get(f"/space/{sid}/folder", params={"archived": "false"})
            folders = folders_data.get("folders", []) if folders_data else []
            print(f"    {len(folders)} folder(s)", flush=True)

            for folder in folders:
                lists_data = get(f"/folder/{folder['id']}/list", params={"archived": "false"})
                for lst in lists_data.get("lists", []) if lists_data else []:
                    if lst["id"] not in completed_lists:
                        all_lists_to_process.append((lst, sid, INCLUDE_CLOSED))

            # Folderless lists
            flists_data = get(f"/space/{sid}/list", params={"archived": "false"})
            for lst in flists_data.get("lists", []) if flists_data else []:
                if lst["id"] not in completed_lists:
                    all_lists_to_process.append((lst, sid, INCLUDE_CLOSED))

        # Process lists in parallel
        print(f"\n  Processing {len(all_lists_to_process)} lists with {MAX_WORKERS} workers...", flush=True)
        
        all_tasks = []
        all_linked = []
        all_checklists = []
        comment_candidates = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_list_parallel, args): args for args in all_lists_to_process}
            
            for i, future in enumerate(as_completed(futures)):
                args = futures[future]
                lst = args[0]
                result = future.result()
                
                if result['success']:
                    all_tasks.extend(result['tasks'])
                    all_linked.extend(result['linked'])
                    all_checklists.extend(result['checklists'])
                    comment_candidates.extend(result['tasks'])
                    
                    # Save individual list (compressed)
                    save_compressed(f"tasks_list_{result['list_id']}", {
                        "list_name": result['list_name'],
                        "list_id": result['list_id'],
                        "space_id": result['space_id'],
                        "tasks": result['tasks']
                    })
                    
                    # Mark done for resume
                    mark_list_done(result['list_id'], manifest)
                    
                    if (i + 1) % 50 == 0:
                        print(f"    {i+1}/{len(all_lists_to_process)} lists done...", flush=True)
                else:
                    print(f"    ✗ List {lst['name']} failed: {result.get('error')}", flush=True)

        # Save aggregated data
        print("\n  Saving aggregated data...", flush=True)
        save_compressed(f"ALL_tasks_{tid}", all_tasks)
        save_compressed(f"ALL_linked_tasks_{tid}", all_linked)
        save_compressed(f"ALL_checklists_{tid}", all_checklists)

        # Comments sample (parallel)
        print(f"\n  Sampling comments for {COMMENT_SAMPLE_SIZE} most-recently-updated tasks...", flush=True)
        sorted_tasks = sorted(
            [t for t in comment_candidates if t.get("date_updated")],
            key=lambda t: int(t.get("date_updated", 0)),
            reverse=True
        )[:COMMENT_SAMPLE_SIZE]

        comments_sample = []
        def fetch_comments(t):
            cdata = get(f"/task/{t['id']}/comment")
            if cdata and cdata.get("comments"):
                return {
                    "task_id":   t["id"],
                    "task_name": t.get("name", ""),
                    "comments":  cdata["comments"],
                }
            return None

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_comments, t): t for t in sorted_tasks}
            for i, future in enumerate(as_completed(futures)):
                result = future.result()
                if result:
                    comments_sample.append(result)
                if (i + 1) % 25 == 0:
                    print(f"    {i+1}/{len(sorted_tasks)} comments done...", flush=True)

        save_compressed(f"comments_sample_{tid}", comments_sample)
        print(f"  Comments: {sum(len(c['comments']) for c in comments_sample)} from {len(comments_sample)} tasks", flush=True)

        print(f"\n  Totals: {len(all_tasks)} tasks | {len(all_linked)} linked | {len(all_checklists)} checklists", flush=True)

    # Final manifest
    manifest['files'] = [f.name for f in sorted(OUT.iterdir())]
    manifest['completed'] = True
    save_manifest(manifest)
    
    print(f"\n=== Snapshot complete — {len(manifest['files'])} files ===\n", flush=True)


if __name__ == "__main__":
    main()
