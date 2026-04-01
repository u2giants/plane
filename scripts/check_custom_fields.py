"""Check custom fields in actual tasks."""
import json
from pathlib import Path

# Load a task file
fname = "tasks_list_901103451188_20260331_023108.json"
with open(fname, "r", encoding="utf-8", errors="replace") as f:
    data = json.load(f)

tasks = data.get("tasks", [])
if tasks:
    task = tasks[0]
    print(f"Task: {task.get('name', 'Unknown')}")
    print(f"\nCustom fields in task:")
    for cf in task.get("custom_fields", []):
        print(f"  - {cf.get('name')}: {cf.get('type')} = {cf.get('value')}")
    
    # Count all unique custom field names across tasks
    all_fields = {}
    for t in tasks[:100]:  # Sample 100 tasks
        for cf in t.get("custom_fields", []):
            name = cf.get("name", "Unknown")
            if name not in all_fields:
                all_fields[name] = {"type": cf.get("type"), "count": 0}
            all_fields[name]["count"] += 1
    
    print(f"\n--- Unique custom fields in {min(100, len(tasks))} tasks ---")
    for name, info in sorted(all_fields.items(), key=lambda x: -x[1]["count"]):
        print(f"  {name} ({info['type']}): {info['count']} tasks")
