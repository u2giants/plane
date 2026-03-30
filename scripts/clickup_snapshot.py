"""
ClickUp full workspace snapshot.
Pulls all structural data from the ClickUp API and saves as JSON artifacts.

Run via GitHub Actions (workflows/clickup-snapshot.yml) or locally:
  CLICKUP_TOKEN=pk_xxx CLICKUP_WORKSPACE_ID=2298436 python clickup_snapshot.py
"""
import os
import json
import time
import sys
from datetime import datetime
from pathlib import Path

import requests

TOKEN       = os.environ["CLICKUP_TOKEN"]
WORKSPACE   = os.environ["CLICKUP_WORKSPACE_ID"]
INCLUDE_CLOSED = os.environ.get("INCLUDE_CLOSED", "true").lower() == "true"
BASE        = "https://api.clickup.com/api/v2"
HEADERS     = {"Authorization": TOKEN}
OUT         = Path("snapshot_output")
OUT.mkdir(exist_ok=True)

RUN_TS = datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def get(path, params=None, retries=3):
    url = f"{BASE}{path}"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                print(f"  Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
    return None


def save(name, data):
    fname = OUT / f"{name}_{RUN_TS}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    size = fname.stat().st_size
    print(f"  ✓ {fname.name}  ({size:,} bytes)")
    return fname


def get_tasks_paged(list_id, include_closed):
    """Fetch all tasks from a list, handling pagination."""
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
        if len(batch) < 100:  # ClickUp returns up to 100 per page
            break
        page += 1
        time.sleep(0.3)  # be polite
    return tasks


def main():
    print(f"\n=== ClickUp Snapshot  workspace={WORKSPACE}  ts={RUN_TS} ===\n")

    # --- Workspace / team ---
    print("Fetching workspaces...")
    teams_data = get("/team")
    if not teams_data:
        sys.exit("Could not fetch workspaces — check CLICKUP_TOKEN")
    teams = teams_data.get("teams", [])
    save("workspaces", teams)

    for team in teams:
        tid = team["id"]
        if tid != WORKSPACE:
            continue  # only process our target workspace

        print(f"\n→ Workspace: {team['name']} ({tid})")

        # Members
        print("  Members...")
        members = get(f"/team/{tid}/member")
        save(f"members_{tid}", members)

        # Custom fields (workspace-level)
        print("  Custom fields...")
        fields = get(f"/team/{tid}/field")
        save(f"custom_fields_{tid}", fields)

        # Goals
        print("  Goals...")
        goals = get(f"/team/{tid}/goal")
        save(f"goals_{tid}", goals)

        # Views (workspace-level)
        print("  Workspace views...")
        views = get(f"/team/{tid}/view")
        save(f"views_workspace_{tid}", views)

        # Spaces
        print("  Spaces...")
        spaces_data = get(f"/team/{tid}/space", params={"archived": "false"})
        spaces = spaces_data.get("spaces", []) if spaces_data else []
        save(f"spaces_{tid}", spaces)

        all_tasks = []

        for space in spaces:
            sid = space["id"]
            print(f"\n  Space: {space['name']} ({sid})")

            # Space-level views
            sv = get(f"/space/{sid}/view")
            save(f"views_space_{sid}", sv)

            # Folders
            folders_data = get(f"/space/{sid}/folder", params={"archived": "false"})
            folders = folders_data.get("folders", []) if folders_data else []
            print(f"    {len(folders)} folder(s)")

            for folder in folders:
                fid = folder["id"]
                lists_data = get(f"/folder/{fid}/list", params={"archived": "false"})
                lists = lists_data.get("lists", []) if lists_data else []

                for lst in lists:
                    lid = lst["id"]
                    lname = lst["name"]
                    print(f"      List: {lname} — fetching tasks...")
                    tasks = get_tasks_paged(lid, INCLUDE_CLOSED)
                    print(f"        {len(tasks)} tasks")
                    all_tasks.extend(tasks)
                    # Save per-list for granular reference
                    save(f"tasks_list_{lid}", {"list_name": lname, "list_id": lid, "tasks": tasks})

            # Folderless lists
            flists_data = get(f"/space/{sid}/list", params={"archived": "false"})
            flists = flists_data.get("lists", []) if flists_data else []
            for lst in flists:
                lid = lst["id"]
                lname = lst["name"]
                print(f"    List (no folder): {lname} — fetching tasks...")
                tasks = get_tasks_paged(lid, INCLUDE_CLOSED)
                print(f"      {len(tasks)} tasks")
                all_tasks.extend(tasks)
                save(f"tasks_list_{lid}", {"list_name": lname, "list_id": lid, "tasks": tasks})

        # Save all tasks in one file for easy global analysis
        save(f"ALL_tasks_{tid}", all_tasks)
        print(f"\n  Total tasks across all lists: {len(all_tasks)}")

    # --- Summary manifest ---
    manifest = {
        "snapshot_ts": RUN_TS,
        "workspace_id": WORKSPACE,
        "include_closed": INCLUDE_CLOSED,
        "files": [f.name for f in sorted(OUT.iterdir())],
    }
    save("_manifest", manifest)
    print(f"\n=== Snapshot complete — {len(list(OUT.iterdir()))} files in snapshot_output/ ===\n")


if __name__ == "__main__":
    main()
