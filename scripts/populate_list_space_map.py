"""
Populate list_space_map table from snapshot data.
Run: python scripts/populate_list_space_map.py
Then copy the SQL output to execute against D1.
"""
import json
import sys
from pathlib import Path

SNAPSHOT_DIR = Path(".")

SPACE_NAMES = {
    "2571984":      "Spruce Line",
    "4294720":      "POP Creations",
    "90114122073":  "designflow",
}

def esc(v):
    """Escape SQL string values."""
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"

def main():
    mappings = {}  # list_id → dict

    for f in sorted(SNAPSHOT_DIR.glob("tasks_list_*_20260331_023108.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            print(f"  skip {f.name}: {e}", file=sys.stderr)
            continue

        list_id   = data.get("list_id")
        list_name = data.get("list_name")
        tasks     = data.get("tasks", [])

        if not list_id:
            continue

        # Pull space/folder from first task that has them
        space_id    = None
        folder_id   = None
        folder_name = None

        for t in tasks:
            sp = t.get("space", {})
            fo = t.get("folder", {})
            if sp.get("id"):
                space_id    = str(sp["id"])
                folder_id   = str(fo.get("id", "")) or None
                folder_name = fo.get("name") or None
                break

        mappings[list_id] = {
            "list_id":     list_id,
            "list_name":   list_name,
            "space_id":    space_id,
            "space_name":  SPACE_NAMES.get(space_id, space_id),
            "folder_id":   folder_id,
            "folder_name": folder_name,
        }

    if not mappings:
        sys.exit("No mappings found - check snapshot_output directory")

    # Print summary
    print(f"Found {len(mappings)} lists:\n")
    for m in sorted(mappings.values(), key=lambda x: (x["space_name"] or "", x["list_name"] or "")):
        sn = (m['space_name'] or '')[:15]
        fn = (m['folder_name'] or '(no folder)')[:25]
        print(f"  [{sn:15s}] {fn:25s} > {m['list_name']} ({m['list_id']})")

    # Print SQL
    print("\n--- SQL for D1 ---\n")
    
    # Build VALUES rows correctly
    rows = []
    for m in mappings.values():
        rows.append(
            f"({esc(m['list_id'])}, {esc(m['list_name'])}, {esc(m['space_id'])}, {esc(m['space_name'])}, {esc(m['folder_id'])}, {esc(m['folder_name'])})"
        )
    
    sql = (
        "DELETE FROM list_space_map;\n\n"
        "INSERT INTO list_space_map\n"
        "  (list_id, list_name, space_id, space_name, folder_id, folder_name)\n"
        "VALUES\n"
        + ",\n".join(rows)
        + ";"
    )
    print(sql)
    
    # Save to file for easy access
    output_file = SNAPSHOT_DIR / "list_space_map.sql"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("-- Populate list_space_map from snapshot\n")
        f.write("-- Run this SQL against D1 to enable division-level analysis\n\n")
        f.write(sql)
    print(f"\nSQL saved to: {output_file}")

if __name__ == "__main__":
    main()
