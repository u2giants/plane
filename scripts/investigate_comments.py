"""Investigate the 703 'unknown' comment types."""
import json
from pathlib import Path
from collections import Counter

SNAPSHOT_DIR = Path(".")

def main():
    comments = json.load(open("comments_sample_2298436_20260331_023108.json", encoding="utf-8", errors="replace"))
    
    unknown_types = []
    
    for task_data in comments:
        for comment in task_data.get("comments", []):
            for part in comment.get("comment", []):
                ctype = part.get("type", "unknown")
                if ctype == "unknown":
                    unknown_types.append({
                        "task": task_data.get("task_name", ""),
                        "comment_id": comment.get("id", ""),
                        "part": part
                    })
    
    print(f"Found {len(unknown_types)} 'unknown' comment parts\n")
    
    # Sample a few to understand the structure
    print("=" * 70)
    print("SAMPLE UNKNOWN TYPES (first 10)")
    print("=" * 70)
    
    for i, unk in enumerate(unknown_types[:10]):
        print(f"\n{i+1}. Task: {unk['task'][:60]}")
        print(f"   Comment ID: {unk['comment_id']}")
        part = unk['part']
        print(f"   Keys: {list(part.keys())}")
        # Print the part without the 'type' field to see what it actually contains
        type_field = part.pop('type', None)
        print(f"   Type was: {type_field}")
        print(f"   Content: {json.dumps(part, indent=2, default=str)[:500]}")
        part['type'] = type_field  # Put it back

if __name__ == "__main__":
    main()
