"""
Query D1 database for event analysis.
"""
import os
import requests
import json

ACCOUNT_ID = "8303d11002766bf1cc36bf2f07ba6f20"
DATABASE_ID = "c37aeb36-e16e-416b-b699-c910f6f8dc10"
API_TOKEN = "cfut_qlhKZXlVmVaBTz5RpAPJhj7jRJyRo6v7LeCDDELG62a50c0a"
BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DATABASE_ID}/query"

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

def query(sql):
    """Execute a SQL query against D1."""
    response = requests.post(BASE_URL, headers=HEADERS, json={"sql": sql})
    data = response.json()
    if data.get("success"):
        return data.get("result", [{}])[0].get("results", [])
    else:
        print(f"Error: {data.get('errors')}")
        return []

def main():
    print("=== D1 Event Analysis ===\n")
    
    # Total events
    results = query("SELECT COUNT(*) as total FROM events WHERE event_type != 'test'")
    print(f"Total events (excluding test): {results[0]['total'] if results else 'N/A'}")
    
    # Events by type
    print("\n--- Events by Type ---")
    results = query("""
        SELECT event_type, COUNT(*) as cnt 
        FROM events 
        WHERE event_type NOT IN ('test') 
        GROUP BY event_type 
        ORDER BY cnt DESC
    """)
    for r in results:
        print(f"  {r['event_type']}: {r['cnt']}")
    
    # Field changes
    print("\n--- Field Changes ---")
    results = query("""
        SELECT field_changed, COUNT(*) as cnt 
        FROM events 
        WHERE field_changed IS NOT NULL AND event_type != 'test'
        GROUP BY field_changed 
        ORDER BY cnt DESC
    """)
    for r in results:
        print(f"  {r['field_changed']}: {r['cnt']}")
    
    # Top users
    print("\n--- Top Users (unique actions) ---")
    results = query("""
        SELECT user_name, COUNT(*) as actions 
        FROM events 
        WHERE user_name IS NOT NULL AND event_type NOT IN ('test', 'taskUpdated')
        GROUP BY user_name 
        ORDER BY actions DESC 
        LIMIT 20
    """)
    for r in results:
        print(f"  {r['user_name']}: {r['actions']}")
    
    # List ID population (should be fixed now)
    print("\n--- List ID Population ---")
    results = query("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN list_id IS NOT NULL THEN 1 ELSE 0 END) as with_list_id
        FROM events 
        WHERE event_type != 'test'
    """)
    if results:
        r = results[0]
        pct = (r['with_list_id'] / r['total'] * 100) if r['total'] > 0 else 0
        print(f"  {r['with_list_id']}/{r['total']} ({pct:.1f}%) have list_id")
    
    # Workspace ID check
    print("\n--- Workspace ID Values ---")
    results = query("""
        SELECT workspace_id, COUNT(*) as cnt 
        FROM events 
        WHERE event_type != 'test'
        GROUP BY workspace_id
    """)
    for r in results:
        print(f"  {r['workspace_id']}: {r['cnt']}")
    
    # Recent events sample
    print("\n--- Recent Events (sample) ---")
    results = query("""
        SELECT id, event_type, task_id, list_id, user_name, field_changed, received_at
        FROM events 
        WHERE event_type NOT IN ('test')
        ORDER BY id DESC 
        LIMIT 5
    """)
    for r in results:
        print(f"  {r}")

if __name__ == "__main__":
    main()
