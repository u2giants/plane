"""
ClickUp full workspace snapshot — enriched version.
Captures: spaces, folders, lists, tasks (with checklists + dependencies),
members (via /seat), custom fields, goals, views, tags, time tracking, docs.

Run via GitHub Actions (workflows/clickup-snapshot.yml) or locally:
  CLICKUP_TOKEN=pk_xxx CLICKUP_WORKSPACE_ID=2298436 python clickup_snapshot.py
"""
import os
import json
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

TOKEN            = os.environ["CLICKUP_TOKEN"]
WORKSPACE        = os.environ["CLICKUP_WORKSPACE_ID"]
INCLUDE_CLOSED   = os.environ.get("INCLUDE_CLOSED", "true").lower() == "true"
BASE             = "https://api.clickup.com/api/v2"
HEADERS          = {"Authorization": TOKEN}
OUT              = Path("snapshot_output")
OUT.mkdir(exist_ok=True)
RUN_TS           = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

# How many of the "most recently updated" tasks to pull full comments for
# (avoids 11K+ individual API calls for the full task list)
COMMENT_SAMPLE_SIZE = 200


def get(path, params=None, retries=3):
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
                return None   # endpoint not available on this plan tier
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"  ERROR {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
    return None


def save(name, data):
    fname = OUT / f"{name}_{RUN_TS}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    size = fname.stat().st_size
    print(f"  ✓ {fname.name}  ({size:,} bytes)", flush=True)
    return fname


def get_tasks_paged(list_id, include_closed):
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
        time.sleep(0.3)
    return tasks


def extract_dependencies(tasks):
    """Pull the dependency graph from task payloads — no extra API calls needed."""
    graph = []
    for t in tasks:
        for dep in t.get("dependencies", []):
            graph.append({
                "task_id":      t["id"],
                "task_name":    t.get("name", ""),
                "depends_on":   dep.get("task_id") or dep.get("depends_on", ""),
                "type":         dep.get("type", ""),
            })
    return graph


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
    print(f"\n=== ClickUp Enriched Snapshot  workspace={WORKSPACE}  ts={RUN_TS} ===\n", flush=True)

    # ── Workspace ──────────────────────────────────────────────────────────────
    print("Fetching workspaces...", flush=True)
    teams_data = get("/team")
    if not teams_data:
        sys.exit("Could not fetch workspaces — check CLICKUP_TOKEN")
    teams = teams_data.get("teams", [])
    save("workspaces", teams)

    for team in teams:
        tid = team["id"]
        if tid != WORKSPACE:
            continue

        print(f"\n→ Workspace: {team['name']} ({tid})", flush=True)

        # ── Members via /seat (replaces broken /member endpoint) ──────────────
        print("  Members (via /seat)...", flush=True)
        seats = get(f"/team/{tid}/seat")
        save(f"members_seats_{tid}", seats)

        # ── Custom fields ──────────────────────────────────────────────────────
        print("  Custom fields...", flush=True)
        fields = get(f"/team/{tid}/field")
        save(f"custom_fields_{tid}", fields)

        # ── Goals ──────────────────────────────────────────────────────────────
        print("  Goals...", flush=True)
        goals = get(f"/team/{tid}/goal")
        save(f"goals_{tid}", goals)

        # ── Workspace-level views ──────────────────────────────────────────────
        print("  Workspace views...", flush=True)
        views = get(f"/team/{tid}/view")
        save(f"views_workspace_{tid}", views)

        # ── Time tracking (last 90 days) ───────────────────────────────────────
        print("  Time tracking (last 90 days)...", flush=True)
        now_ms     = int(datetime.utcnow().timestamp() * 1000)
        start_ms   = int((datetime.utcnow() - timedelta(days=90)).timestamp() * 1000)
        time_data  = get(f"/team/{tid}/time_entries", params={"start_date": start_ms, "end_date": now_ms})
        save(f"time_tracking_{tid}", time_data)

        # ── Docs / Pages (may 404 on lower plan tiers) ────────────────────────
        print("  Docs/Pages (attempting)...", flush=True)
        docs = get(f"/team/{tid}/page")
        if docs is not None:
            save(f"docs_{tid}", docs)
        else:
            print("    (not available on this plan tier)", flush=True)

        # ── Spaces ────────────────────────────────────────────────────────────
        print("  Spaces...", flush=True)
        spaces_data = get(f"/team/{tid}/space", params={"archived": "false"})
        spaces = spaces_data.get("spaces", []) if spaces_data else []
        save(f"spaces_{tid}", spaces)

        all_tasks      = []
        all_deps       = []
        all_checklists = []
        comment_candidates = []   # recently updated tasks to sample comments from

        for space in spaces:
            sid = space["id"]
            print(f"\n  Space: {space['name']} ({sid})", flush=True)

            # Tags per space
            tags = get(f"/space/{sid}/tag")
            if tags:
                save(f"tags_space_{sid}", tags)

            # Space views
            sv = get(f"/space/{sid}/view")
            save(f"views_space_{sid}", sv)

            # Folders
            folders_data = get(f"/space/{sid}/folder", params={"archived": "false"})
            folders = folders_data.get("folders", []) if folders_data else []
            print(f"    {len(folders)} folder(s)", flush=True)

            for folder in folders:
                fid = folder["id"]
                lists_data = get(f"/folder/{fid}/list", params={"archived": "false"})
                lists = lists_data.get("lists", []) if lists_data else []

                for lst in lists:
                    lid, lname = lst["id"], lst["name"]
                    print(f"      List: {lname} — fetching tasks...", flush=True)
                    tasks = get_tasks_paged(lid, INCLUDE_CLOSED)
                    print(f"        {len(tasks)} tasks", flush=True)
                    all_tasks.extend(tasks)
                    all_deps.extend(extract_dependencies(tasks))
                    all_checklists.extend(extract_checklists(tasks))
                    comment_candidates.extend(tasks)
                    save(f"tasks_list_{lid}", {"list_name": lname, "list_id": lid, "space_id": sid, "tasks": tasks})

            # Folderless lists
            flists_data = get(f"/space/{sid}/list", params={"archived": "false"})
            flists = flists_data.get("lists", []) if flists_data else []
            for lst in flists:
                lid, lname = lst["id"], lst["name"]
                print(f"    List (no folder): {lname} — fetching tasks...", flush=True)
                tasks = get_tasks_paged(lid, INCLUDE_CLOSED)
                print(f"      {len(tasks)} tasks", flush=True)
                all_tasks.extend(tasks)
                all_deps.extend(extract_dependencies(tasks))
                all_checklists.extend(extract_checklists(tasks))
                comment_candidates.extend(tasks)
                save(f"tasks_list_{lid}", {"list_name": lname, "list_id": lid, "space_id": sid, "tasks": tasks})

        # ── Save aggregated data ───────────────────────────────────────────────
        save(f"ALL_tasks_{tid}", all_tasks)
        save(f"ALL_dependencies_{tid}", all_deps)
        save(f"ALL_checklists_{tid}", all_checklists)

        # ── Comments sample (top N most recently updated tasks) ───────────────
        print(f"\n  Sampling comments for {COMMENT_SAMPLE_SIZE} most-recently-updated tasks...", flush=True)
        # Sort by date_updated descending, take top N
        sorted_tasks = sorted(
            [t for t in comment_candidates if t.get("date_updated")],
            key=lambda t: int(t.get("date_updated", 0)),
            reverse=True
        )[:COMMENT_SAMPLE_SIZE]

        comments_sample = []
        for i, t in enumerate(sorted_tasks):
            cdata = get(f"/task/{t['id']}/comment")
            if cdata and cdata.get("comments"):
                comments_sample.append({
                    "task_id":   t["id"],
                    "task_name": t.get("name", ""),
                    "comments":  cdata["comments"],
                })
            if (i + 1) % 25 == 0:
                print(f"    {i+1}/{len(sorted_tasks)} done...", flush=True)
            time.sleep(0.2)

        save(f"comments_sample_{tid}", comments_sample)
        print(f"  Comments captured: {sum(len(c['comments']) for c in comments_sample)} from {len(comments_sample)} tasks", flush=True)

        print(f"\n  Totals: {len(all_tasks)} tasks | {len(all_deps)} dependencies | {len(all_checklists)} checklists", flush=True)

    # ── Manifest ──────────────────────────────────────────────────────────────
    manifest = {
        "snapshot_ts":      RUN_TS,
        "workspace_id":     WORKSPACE,
        "include_closed":   INCLUDE_CLOSED,
        "comment_sample":   COMMENT_SAMPLE_SIZE,
        "files":            [f.name for f in sorted(OUT.iterdir())],
    }
    save("_manifest", manifest)
    print(f"\n=== Snapshot complete — {len(manifest['files'])} files ===\n", flush=True)


if __name__ == "__main__":
    main()
