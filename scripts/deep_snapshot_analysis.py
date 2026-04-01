"""Deep analysis of ClickUp data - find ALL gaps."""
import json
from pathlib import Path
from collections import Counter

SNAPSHOT_DIR = Path(".")

def load_json(fname):
    with open(fname, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)

def main():
    print("=" * 70)
    print("DEEP CLICKUP DATA GAP ANALYSIS")
    print("=" * 70)
    
    # 1. Check what data is in task payloads vs what we're capturing
    print("\n" + "=" * 70)
    print("1. TASK PAYLOAD ANALYSIS")
    print("=" * 70)
    
    task_files = list(SNAPSHOT_DIR.glob("tasks_list_*_20260331_023108.json"))
    total_tasks = 0
    subtask_count = 0
    attachment_count = 0
    checklist_count = 0
    linked_tasks_count = 0
    dependencies_count = 0
    points_count = 0
    
    field_keys = Counter()
    
    for tf in task_files[:10]:  # Sample 10 lists
        data = load_json(tf)
        tasks = data.get("tasks", [])
        total_tasks += len(tasks)
        
        for t in tasks:
            # Check for subtasks
            if t.get("subtasks", {}).get("count", 0) > 0:
                subtask_count += 1
            
            # Check for attachments
            att = t.get("attachments", {}).get("attachments", [])
            attachment_count += len(att)
            
            # Check for checklists
            cl = t.get("checklists", [])
            checklist_count += len(cl)
            
            # Check for linked tasks
            lt = t.get("linked_tasks", [])
            linked_tasks_count += len(lt)
            
            # Check for dependencies
            dep = t.get("dependencies", [])
            dependencies_count += len(dep)
            
            # Check for points/story points
            if t.get("points") is not None:
                points_count += 1
            
            # Track all keys
            for k in t.keys():
                field_keys[k] += 1
    
    print(f"Sampled {total_tasks} tasks from 10 lists")
    print(f"  - Tasks with subtasks: {subtask_count}")
    print(f"  - Total attachments: {attachment_count}")
    print(f"  - Total checklists: {checklist_count}")
    print(f"  - Total linked tasks: {linked_tasks_count}")
    print(f"  - Total dependencies: {dependencies_count}")
    print(f"  - Tasks with points: {points_count}")
    
    print("\nAll keys in task payload:")
    for k, cnt in field_keys.most_common(30):
        print(f"  {k}: {cnt}")
    
    # 2. Check comments for more data types
    print("\n" + "=" * 70)
    print("2. COMMENT DATA TYPES")
    print("=" * 70)
    
    comments = load_json("comments_sample_2298436_20260331_023108.json")
    comment_types = Counter()
    
    for task in comments[:20]:  # Sample
        for comment in task.get("comments", []):
            for part in comment.get("comment", []):
                ctype = part.get("type", "unknown")
                comment_types[ctype] += 1
    
    print(f"Comment types (from sample of 20 tasks):")
    for ct, cnt in comment_types.most_common():
        print(f"  {ct}: {cnt}")
    
    # 3. Check views structure
    print("\n" + "=" * 70)
    print("3. VIEWS STRUCTURE")
    print("=" * 70)
    
    views = load_json("views_workspace_2298436_20260331_023108.json")
    if isinstance(views, dict) and "views" in views:
        views = views["views"]
    
    for v in views:
        print(f"\nView: {v.get('name', 'Unnamed')} ({v.get('type')})")
        print(f"  ID: {v.get('id')}")
        print(f"  Space/Project: {v.get('project', {}).get('id')}")
        print(f"  Owner: {v.get('owner', {}).get('username')}")
        # Show settings if present
        settings = v.get("settings", {})
        if settings:
            print(f"  Settings keys: {list(settings.keys())}")
    
    # 4. Check space views for more
    print("\n" + "=" * 70)
    print("4. SPACE VIEWS")
    print("=" * 70)
    
    for space_id in ["2571984", "4294720", "90114122073"]:
        fname = f"views_space_{space_id}_20260331_023108.json"
        try:
            views = load_json(fname)
            if isinstance(views, dict) and "views" in views:
                views = views["views"]
            print(f"\nSpace {space_id}: {len(views)} views")
            view_types = Counter(v.get("type") for v in views)
            print(f"  Types: {dict(view_types)}")
        except:
            print(f"\nSpace {space_id}: No views file")
    
    # 5. What webhook events could capture what we're missing
    print("\n" + "=" * 70)
    print("5. DATA WE COULD BE CAPTURING VIA WEBHOOKS")
    print("=" * 70)
    
    print("\nMissing webhook subscriptions:")
    missing = [
        ("taskAttachmentUpdated", f"Captures {attachment_count} attachment events we don't have"),
        ("taskChecklistItemCompleted", "Tracks checklist completion progress"),
        ("taskChecklistItemDeleted", "Tracks checklist changes"),
        ("taskDependencyUpdated", "Tracks {dependencies_count} dependency changes"),
        ("taskLinkedTasksUpdated", "Tracks linked task relationships"),
        ("taskUrlUpdated", "Tracks URL/link changes"),
    ]
    for event, desc in missing:
        print(f"  - {event}: {desc}")
    
    # 6. Summary of critical gaps
    print("\n" + "=" * 70)
    print("6. CRITICAL GAPS SUMMARY")
    print("=" * 70)
    
    gaps = []
    
    # Custom fields at space/list level not captured
    gaps.append("Custom field DEFINITIONS at list level - only workspace-level captured")
    
    # Attachments not webhook'd
    gaps.append("Attachments - 91 found in comments but not as separate webhook events")
    
    # Linked tasks not captured
    if linked_tasks_count > 0:
        gaps.append(f"Linked tasks - {linked_tasks_count} found in task data")
    
    # Dependencies not being extracted
    if dependencies_count > 0:
        gaps.append(f"Dependencies - {dependencies_count} found but 0 in ALL_dependencies")
    
    # Members endpoint returning null
    gaps.append("Members API (/seat) returning null - need alternate endpoint")
    
    # Time tracking 0 entries
    gaps.append("Time tracking - 0 entries despite being enabled in spaces")
    
    for i, g in enumerate(gaps, 1):
        print(f"{i}. {g}")
    
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    print("""
1. FIX snapshot script to fetch custom fields at list level
   - GET /list/{list_id}/field returns list-specific custom fields
   
2. ADD missing webhook subscriptions:
   - taskAttachmentUpdated
   - taskChecklistItemCompleted  
   - taskChecklistItemDeleted
   - taskDependencyUpdated
   - taskLinkedTasksUpdated
   
3. FIX dependencies extraction in snapshot.py
   - ALL_dependencies file has 0 entries but tasks have dependencies
   
4. TRY alternate members endpoint:
   - GET /team/{id}/member (may require different API key)
   
5. INVESTIGATE time tracking:
   - Spaces have it enabled but 0 entries captured
   - May need to check ClickUp plan tier
""")

if __name__ == "__main__":
    main()
