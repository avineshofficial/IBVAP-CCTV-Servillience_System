"""Probe to test DetectionEvent behavior with unresolvable camera_uid."""
import time
import httpx
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path("s:/IBVAP-CCTV-Servillience_System")
load_dotenv(PROJECT_ROOT / ".env")

BASE = "http://127.0.0.1:8000"
EDGE_KEY = os.getenv("EDGE_API_KEY")

demo_users = [
    ("admin", "admin123", "admin", "hq"),
    ("analyst", "analyst123", "hq_analyst", "hq"),
    ("commander", "commander123", "post_commander", "bop_alpha"),
    ("officer", "officer123", "field_officer", "bop_alpha"),
]

tokens = {}
for uname, pwd, role, bop in demo_users:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"username": uname, "password": pwd})
    tokens[uname] = r.json()["access_token"]

test_event_id = 88123
ghost_cam = "cam_ghost_event_test_99"
payload = {
    "edge_id": "edge_test_node",
    "timestamp": time.time(),
    "events": [
        {
            "edge_event_id": test_event_id,
            "event_type": "motion",
            "camera_id": ghost_cam,
            "track_id": 777,
            "timestamp": time.time(),
            "data": {"class": "vehicle", "test": "probe_unresolvable_event"}
        }
    ],
    "alerts": []
}

print(f"Sending POST /api/v1/edge/sync with event on unresolvable camera '{ghost_cam}'...")
r_sync = httpx.post(f"{BASE}/api/v1/edge/sync", json=payload, headers={"X-Edge-API-Key": EDGE_KEY})
print(f"Sync status: {r_sync.status_code}, Response: {r_sync.json()}")

print("\nChecking visibility of the orphaned event in GET /api/v1/events across all 4 roles:")
for uname, _, role, user_bop in demo_users:
    r = httpx.get(f"{BASE}/api/v1/events", headers={"Authorization": f"Bearer {tokens[uname]}"})
    events = r.json()
    visible = any(e.get("camera_uid") == ghost_cam for e in events)
    print(f"  User {uname:<12s} ({role:<14s}, {user_bop:<9s}) -> Can see unresolvable camera event? {visible}")
