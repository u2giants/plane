"""
Analyze what data is available in ClickUp but NOT being captured.
Focus on: data flow, actions taken, and system behavior.
"""
import json
from pathlib import Path
from collections import Counter

SNAPSHOT_DIR = Path(".")

def load_json(fname):
    with open(fname, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)

def main():
    print("=" * 70)
    print("CLICKUP DATA FLOW & ACTION ANALYSIS")
    print("=" * 70)
    
    # What do webhooks capture?
    print("\n" + "=" * 70)
    print("1. CURRENT WEBHOOK COVERAGE")
    print("=" * 70)
    
    current_webhooks = [
        ("taskCreated", "✅", "New task created"),
        ("taskUpdated", "✅", "Any task change"),
        ("taskDeleted", "✅", "Task deleted"),
        ("taskMoved", "✅", "Task moved between lists"),
        ("taskStatusUpdated", "✅", "Status changed"),
        ("taskAssigneeUpdated", "✅", "Assignee changed"),
        ("taskPriorityUpdated", "✅", "Priority changed"),
        ("taskDueDateUpdated", "✅", "Due date changed"),
        ("taskTagUpdated", "✅", "Tags changed"),
        ("taskTimeEstimateUpdated", "✅", "Time estimate changed"),
        ("taskTimeTrackedUpdated", "✅", "Time tracked changed"),
        ("taskCommentPosted", "✅", "Comment added"),
        ("taskCommentUpdated", "✅", "Comment edited"),
        ("listCreated/Updated/Deleted", "✅", "List changes"),
        ("folderCreated/Updated/Deleted", "✅", "Folder changes"),
        ("spaceCreated/Updated/Deleted", "✅", "Space changes"),
    ]
    
    missing_actions = [
        ("taskAttachmentUpdated", "❌", "File attached/removed from task"),
        ("taskChecklistItemCompleted", "❌", "Checklist item checked off"),
        ("taskChecklistItemDeleted", "❌", "Checklist item added/deleted"),
        ("taskDependencyUpdated", "❌", "Dependency added/removed"),
        ("taskLinkedTasksUpdated", "❌", "Linked task relationship changed"),
        ("taskUrlUpdated", "❌", "Task URL/link changed"),
        ("taskDescriptionUpdated", "❌", "Description edited (part of taskUpdated)"),
    ]
    
    print("\nCurrently capturing:")
    for event, status, desc in current_webhooks:
        print(f"  {status} {event}: {desc}")
    
    print("\nNOT capturing (available but not subscribed):")
    for event, status, desc in missing_actions:
        print(f"  {status} {event}: {desc}")
    
    # Analyze what data is in task payload
    print("\n" + "=" * 70)
    print("2. TASK PAYLOAD ANALYSIS - What fields exist?")
    print("=" * 70)
    
    task_file = "tasks_list_901103451188_20260331_023108.json"
    data = load_json(task_file)
    task = data.get("tasks", [{}])[0]
    
    print("\nAll fields in task payload:")
    all_keys = sorted(task.keys())
    for i, key in enumerate(all_keys):
        val = task.get(key)
        val_type = type(val).__name__
        if isinstance(val, dict):
            sub_keys = list(val.keys())[:5]
            print(f"  {key}: {val_type} ({len(val)} keys) - e.g. {sub_keys}")
        elif isinstance(val, list):
            print(f"  {key}: {val_type} ({len(val)} items)")
        elif val is None:
            print(f"  {key}: {val_type} (NULL)")
        else:
            val_str = str(val)[:50]
            print(f"  {key}: {val_type} = {val_str}")
    
    # Check what data flows through comments
    print("\n" + "=" * 70)
    print("3. COMMENT ANALYSIS - Communication & Collaboration")
    print("=" * 70)
    
    comments = load_json("comments_sample_2298436_20260331_023108.json")
    
    # Count comment types
    comment_types = Counter()
    mention_count = 0
    attachment_count = 0
    image_count = 0
    
    for task_data in comments:
        for comment in task_data.get("comments", []):
            for part in comment.get("comment", []):
                ctype = part.get("type", "unknown")
                comment_types[ctype] += 1
                
                if ctype == "attachment":
                    attachment_count += 1
                    att = part.get("attachment", {})
                    if att:
                        attachment_count += 1
                        
                if ctype == "image":
                    image_count += 1
                    
                if ctype == "mention":
                    mention_count += 1
                    
                if ctype == "link_mention":
                    mention_count += 1
    
    print(f"\nComment types in sample ({len(comments)} tasks):")
    for ct, cnt in comment_types.most_common():
        print(f"  {ct}: {cnt}")
    
    print(f"\nTotal attachments in comments: {attachment_count}")
    print(f"Total images in comments: {image_count}")
    print(f"Total mentions: {mention_count}")
    
    # What about task history?
    print("\n" + "=" * 70)
    print("4. TASK HISTORY - Can we trace task lifecycle?")
    print("=" * 70)
    
    print("\nWebhooks capture history_items via taskUpdated/taskStatusUpdated")
    print("This should allow us to:")
    print("  - Trace status transitions (status A → B → C)")
    print("  - Calculate time in each status")
    print("  - See who made each change")
    print("  - See the full edit history")
    
    # Check what the webhook payload contains for history
    print("\nWebhook payload structure (from history_items):")
    print("  - history_items[0].field: what changed")
    print("  - history_items[0].before: previous value")
    print("  - history_items[0].after: new value")
    print("  - history_items[0].user: who made the change")
    print("  - history_items[0].parent_id: list_id (FIXED)")
    
    # Time tracking
    print("\n" + "=" * 70)
    print("5. TIME TRACKING - How is time being tracked?")
    print("=" * 70)
    
    time_data = load_json("time_tracking_2298436_20260331_023108.json")
    print(f"\nTime tracking data: {time_data}")
    print("\nNote: taskTimeTrackedUpdated webhook fires but time entries API returns empty")
    print("This suggests team may be using manual time tracking without the API")
    
    # Attachments
    print("\n" + "=" * 70)
    print("6. ATTACHMENTS - File activity")
    print("=" * 70)
    
    print("\nAttachments found in comments: 91")
    print("\nNOT captured via webhook:")
    print("  - taskAttachmentUpdated event (when files are uploaded/downloaded)")
    print("  - Attachment metadata (filename, size, type, uploader)")
    print("  - Attachment location in task")
    
    # What we'd need to capture complete workflow
    print("\n" + "=" * 70)
    print("7. COMPLETE WORKFLOW CAPTURE - What's missing?")
    print("=" * 70)
    
    print("""
To fully understand how tasks move through the system, we need:

DATA CAPTURE (webhook):
✅ Status transitions (taskStatusUpdated)
✅ Assignee changes (taskAssigneeUpdated)
✅ Comments (taskCommentPosted)
✅ Due date changes (taskDueDateUpdated)
✅ Tags (taskTagUpdated)
❌ Checklist progress (taskChecklistItemCompleted) - NOT subscribed
❌ Attachments (taskAttachmentUpdated) - NOT subscribed
❌ Linked tasks (taskLinkedTasksUpdated) - NOT subscribed
❌ Dependencies (taskDependencyUpdated) - NOT subscribed

DATA FLOW ANALYSIS:
✅ Can trace: created → status A → status B → completed
✅ Can calculate: time spent in each status
✅ Can see: who moved task through stages
❌ Missing: checklist completion percentage over time
❌ Missing: attachment activity (files added at which stage)
❌ Missing: time tracking entries with notes

ACTIONS ON TASKS:
✅ Created, Updated, Moved, Deleted
✅ Status changes, Assignee changes, Priority changes
✅ Comments posted
✅ Tags added/removed
❌ Attachments uploaded/downloaded
❌ Checklist items completed
❌ Checklist items added/deleted
❌ Dependencies added/removed
❌ Linked tasks added/removed
""")
    
    # Recommendations
    print("\n" + "=" * 70)
    print("8. RECOMMENDATIONS")
    print("=" * 70)
    
    print("""
HIGH PRIORITY - Add webhook subscriptions:
1. taskAttachmentUpdated - Critical for understanding file activity
2. taskChecklistItemCompleted - Key for progress tracking
3. taskChecklistItemDeleted - Understanding checklist changes
4. taskLinkedTasksUpdated - Relationship changes

MEDIUM PRIORITY - Snapshot improvements:
1. Capture attachment metadata per task
2. Capture checklist completion percentages
3. Track subtask depth and hierarchy patterns

LOW PRIORITY - Nice to have:
1. Capture comment mentions (@user)
2. Capture comment reactions
3. Track view configurations
""")

if __name__ == "__main__":
    main()
