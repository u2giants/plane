"""
Analyze ClickUp snapshot data to identify gaps in data capture.
"""
import json
from pathlib import Path

SNAPSHOT_DIR = Path(".")

def load_json(fname):
    """Load JSON with proper encoding handling."""
    try:
        with open(fname, "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        # Try with error handling
        with open(fname, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)

def main():
    print("=" * 60)
    print("CLICKUP DATA CAPTURE ANALYSIS")
    print("=" * 60)
    
    # Load manifest
    manifest = load_json("_manifest_20260331_023108.json")
    print(f"\nSnapshot date: {manifest['snapshot_ts']}")
    print(f"Workspace: {manifest['workspace_id']}")
    print(f"Included closed: {manifest['include_closed']}")
    
    # 1. Analyze workspaces
    print("\n" + "=" * 60)
    print("1. WORKSPACES")
    print("=" * 60)
    workspaces = load_json("workspaces_20260331_023108.json")
    if isinstance(workspaces, dict) and "teams" in workspaces:
        workspaces = workspaces["teams"]
    print(f"Total workspaces: {len(workspaces)}")
    for w in workspaces:
        print(f"  - {w.get('name', 'Unknown')} (ID: {w.get('id')})")
    
    # 2. Analyze spaces
    print("\n" + "=" * 60)
    print("2. SPACES")
    print("=" * 60)
    spaces_data = load_json("spaces_2298436_20260331_023108.json")
    if isinstance(spaces_data, dict):
        spaces = spaces_data if isinstance(spaces_data, list) else [spaces_data]
    else:
        spaces = spaces_data
    print(f"Total spaces: {len(spaces)}")
    for s in spaces:
        print(f"  - {s.get('name', 'Unknown')} (ID: {s.get('id')})")
        features = s.get('features', {})
        print(f"      Time tracking: {features.get('time_tracking', {}).get('enabled')}")
        print(f"      Sprints: {features.get('sprints', {}).get('enabled')}")
        print(f"      Milestones: {features.get('milestones', {}).get('enabled')}")
        print(f"      Custom fields: {features.get('custom_fields', {}).get('enabled')}")
    
    # 3. Analyze tags
    print("\n" + "=" * 60)
    print("3. TAGS")
    print("=" * 60)
    for space_id in ["2571984", "4294720", "90114122073"]:
        fname = f"tags_space_{space_id}_20260331_023108.json"
        try:
            tags_data = load_json(fname)
            if isinstance(tags_data, dict) and "tags" in tags_data:
                tags = tags_data["tags"]
                print(f"Space {space_id}: {len(tags)} tags")
        except FileNotFoundError:
            print(f"Space {space_id}: No tags file")
    
    # 4. Analyze views
    print("\n" + "=" * 60)
    print("4. VIEWS")
    print("=" * 60)
    views = load_json("views_workspace_2298436_20260331_023108.json")
    if isinstance(views, dict) and "views" in views:
        views = views["views"]
    print(f"Workspace views: {len(views)}")
    view_types = {}
    for v in views:
        vt = v.get("type", "unknown")
        view_types[vt] = view_types.get(vt, 0) + 1
    print(f"View types: {view_types}")
    
    # 5. Check custom fields
    print("\n" + "=" * 60)
    print("5. CUSTOM FIELDS")
    print("=" * 60)
    cf_data = load_json("custom_fields_2298436_20260331_023108.json")
    if isinstance(cf_data, dict) and "fields" in cf_data:
        fields = cf_data["fields"]
        print(f"Total custom fields: {len(fields)}")
        for f in fields:
            print(f"  - {f.get('name', 'Unknown')}: {f.get('type', '?')}")
    else:
        print(f"Custom fields data: {cf_data}")
    
    # 6. Check goals
    print("\n" + "=" * 60)
    print("6. GOALS")
    print("=" * 60)
    goals_data = load_json("goals_2298436_20260331_023108.json")
    print(f"Goals: {json.dumps(goals_data, indent=2)}")
    
    # 7. Check members
    print("\n" + "=" * 60)
    print("7. MEMBERS")
    print("=" * 60)
    members_data = load_json("members_seats_2298436_20260331_023108.json")
    print(f"Members data: {json.dumps(members_data, indent=2)[:500]}")
    
    # 8. Analyze task lists
    print("\n" + "=" * 60)
    print("8. TASK LISTS")
    print("=" * 60)
    task_files = list(SNAPSHOT_DIR.glob("tasks_list_*_20260331_023108.json"))
    print(f"Task list files: {len(task_files)}")
    total_tasks = 0
    for tf in task_files[:5]:  # Sample first 5
        data = load_json(tf)
        if isinstance(data, dict):
            tasks = data.get("tasks", [])
            print(f"  {data.get('list_name', tf.name)}: {len(tasks)} tasks")
            total_tasks += len(tasks)
    print(f"  ... (sampling shows {total_tasks} tasks in first 5 lists)")
    
    # 9. Check comments
    print("\n" + "=" * 60)
    print("9. COMMENTS SAMPLE")
    print("=" * 60)
    comments_data = load_json("comments_sample_2298436_20260331_023108.json")
    if isinstance(comments_data, list):
        print(f"Sample size: {len(comments_data)} tasks with comments")
        total_comments = sum(len(c.get("comments", [])) for c in comments_data)
        print(f"Total comments in sample: {total_comments}")
        # Check for attachment types
        attachment_count = 0
        for task in comments_data:
            for comment in task.get("comments", []):
                for part in comment.get("comment", []):
                    if part.get("type") == "attachment":
                        attachment_count += 1
        print(f"Attachments found: {attachment_count}")
    else:
        print(f"Comments: {comments_data}")
    
    # 10. Check for missing API data
    print("\n" + "=" * 60)
    print("10. POTENTIAL DATA GAPS IDENTIFIED")
    print("=" * 60)
    gaps = []
    
    # Dependencies
    deps = load_json("ALL_dependencies_2298436_20260331_023108.json")
    if isinstance(deps, list):
        gaps.append(f"Dependencies captured: {len(deps)}")
    else:
        gaps.append("Dependencies: API returned null/empty")
    
    # Time tracking
    time_data = load_json("time_tracking_2298436_20260331_023108.json")
    if isinstance(time_data, dict):
        time_entries = time_data.get("data", [])
        gaps.append(f"Time tracking entries: {len(time_entries)}")
    
    # Goals
    if isinstance(goals_data, dict):
        goals = goals_data.get("goals", [])
        folders = goals_data.get("folders", [])
        gaps.append(f"Goals: {len(goals)}, Folders: {len(folders)}")
    
    print("Gaps analysis:")
    for g in gaps:
        print(f"  - {g}")
    
    # Missing data we could be capturing
    print("\n" + "=" * 60)
    print("11. CLICKUP API ENDPOINTS NOT BEING PULLED")
    print("=" * 60)
    missing_endpoints = [
        ("/team/{id}/time_entry", "Individual time entries with notes"),
        ("/team/{id}/guest", "Guest users/external collaborators"),
        ("/task/{id}/task", "Linked tasks (relates to)"),
        ("/task/{id}/linked_tasks", "Task relationships"),
        ("/task/{id}/attachments", "Direct task attachments"),
        ("/task/{id}/checklist/{checklist_id}/checklist_item", "Checklist item details"),
        ("/list/{id}/task/{task_id}/recursive", "Recursive subtask fetch"),
        ("/space/{id}/goal", "Space-level goals"),
        ("/team/{id}/recurring_task", "Recurring tasks"),
        ("/team/{id}/bulk_custom_field_tasks", "Custom field values per task"),
    ]
    print("Not currently captured:")
    for endpoint, desc in missing_endpoints:
        print(f"  - {endpoint}: {desc}")
    
    print("\n" + "=" * 60)
    print("12. WEBHOOK EVENTS NOT SUBSCRIBED")
    print("=" * 60)
    current_webhooks = [
        "taskCreated", "taskUpdated", "taskDeleted", "taskMoved",
        "taskCommentPosted", "taskCommentUpdated", "taskAssigneeUpdated",
        "taskStatusUpdated", "taskTimeEstimateUpdated", "taskTimeTrackedUpdated",
        "taskPriorityUpdated", "taskDueDateUpdated", "taskTagUpdated",
        "listCreated", "listUpdated", "listDeleted",
        "folderCreated", "folderUpdated", "folderDeleted",
        "spaceCreated", "spaceUpdated", "spaceDeleted"
    ]
    missing_webhooks = [
        ("taskTimeTrackedUpdated", "Already subscribed - time tracking happens"),
        ("taskAttachmentUpdated", "Attachments on tasks"),
        ("taskChecklistItemCompleted", "Checklist progress"),
        ("taskChecklistItemDeleted", "Checklist changes"),
        ("taskDependencyUpdated", "Dependency changes"),
        ("taskUrlUpdated", "URL/link changes on tasks"),
        ("listTaskPositionUpdated", "Task reordering in lists"),
        ("projectViewUpdated", "View configuration changes"),
    ]
    print("Already subscribed: 22 event types")
    print("Not subscribed but available:")
    for event, desc in missing_webhooks:
        print(f"  - {event}: {desc}")

if __name__ == "__main__":
    main()
