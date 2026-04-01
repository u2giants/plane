"""Find tasks with dependencies and linked_tasks."""
import json
from pathlib import Path

SNAPSHOT_DIR = Path(".")

def main():
    task_files = list(SNAPSHOT_DIR.glob("tasks_list_*_20260331_023108.json"))
    
    deps_count = 0
    linked_count = 0
    deps_examples = []
    linked_examples = []
    
    for tf in task_files:
        data = json.load(open(tf, encoding="utf-8", errors="replace"))
        tasks = data.get("tasks", [])
        
        for t in tasks:
            deps = t.get("dependencies", [])
            linked = t.get("linked_tasks", [])
            
            if deps and len(deps_examples) < 3:
                deps_examples.append({
                    "task": t.get("name", ""),
                    "task_id": t.get("id"),
                    "dependencies": deps
                })
            deps_count += len(deps)
            
            if linked and len(linked_examples) < 3:
                linked_examples.append({
                    "task": t.get("name", ""),
                    "task_id": t.get("id"),
                    "linked_tasks": linked
                })
            linked_count += len(linked)
    
    print(f"Total dependencies: {deps_count}")
    print(f"Total linked_tasks: {linked_count}")
    
    print("\n=== Dependency Examples ===")
    for ex in deps_examples:
        print(f"\nTask: {ex['task']}")
        print(f"  Dependencies: {json.dumps(ex['dependencies'], indent=4)}")
    
    print("\n=== Linked Tasks Examples ===")
    for ex in linked_examples:
        print(f"\nTask: {ex['task']}")
        print(f"  Linked: {json.dumps(ex['linked_tasks'], indent=4)}")

if __name__ == "__main__":
    main()
