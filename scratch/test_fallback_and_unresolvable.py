"""Probe script to test:
1. Fallback bop_id resolution via associated event (alert has NO camera_id, but event has camera_id='cam_04').
2. Nonexistent / unresolvable camera_id (camera not in Camera table).
"""
import time
import sqlite3
import httpx
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path("s:/IBVAP-CCTV-Servillience_System")
load_dotenv(PROJECT_ROOT / ".env")

BASE = "http://127.0.0.1:8000"
EDGE_KEY = os.getenv("EDGE_API_KEY")

print("=" * 80)
print("PROBE: FALLBACK VIA EVENT & UNRESOLVABLE CAMERA INGESTION")
print("=" * 80)

# Authenticate demo users for visibility testing
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

# ─── TEST 1: FALLBACK RESOLUTION VIA ASSOCIATED EVENT ──────────────────────────
print("\n[TEST 1] Fallback Resolution Via Associated Event:")
msg_event_fallback = f"TEST_EVENT_FALLBACK_{int(time.time())}"
event_id_1 = 55501

payload_1 = {
    "edge_id": "edge_node_test",
    "timestamp": time.time(),
    "events": [
        {
            "edge_event_id": event_id_1,
            "event_type": "intrusion",
            "camera_id": "cam_04",  # cam_04 is BOP Bravo
            "track_id": 101,
            "timestamp": time.time(),
            "data": {"class": "person"}
        }
    ],
    "alerts": [
        {
            "edge_alert_id": 66601,
            "event_id": event_id_1,
            # Notice: NO camera_id, NO bop_id
            "severity": "high",
            "alert_type": "intrusion",
            "message": msg_event_fallback,
            "data": {"track_id": 101, "speed": 2.5}
        }
    ]
}

print(f"  Sending POST /api/v1/edge/sync with alert tied to event_id={event_id_1} (camera_id='cam_04' on event only)...")
r1 = httpx.post(f"{BASE}/api/v1/edge/sync", json=payload_1, headers={"X-Edge-API-Key": EDGE_KEY})
print(f"  HTTP Status: {r1.status_code}")
print(f"  Response: {r1.json()}")

conn = sqlite3.connect(PROJECT_ROOT / "ibvap.db")
cur = conn.cursor()
row1 = cur.execute(
    "SELECT id, alert_type, severity, bop_id, message FROM alerts WHERE message = ?",
    (msg_event_fallback,)
).fetchone()

if row1:
    aid, atype, asev, abop, amsg = row1
    print(f"  DB Record Found: ID={aid}, bop_id='{abop}'")
    test1_resolved = (abop == "bop_bravo")
    print(f"  Resolution via event camera lookup: {'SUCCESS (bop_bravo)' if test1_resolved else 'FAIL'}")
else:
    print("  DB Record NOT Found!")
    test1_resolved = False

# Visibility check for Test 1
print("  Checking role visibility for event fallback alert:")
for uname, _, role, user_bop in demo_users:
    r = httpx.get(f"{BASE}/api/v1/alerts", headers={"Authorization": f"Bearer {tokens[uname]}"})
    alerts = r.json()
    visible = any(a.get("message") == msg_event_fallback for a in alerts)
    print(f"    User {uname:<12s} ({role:<14s}, {user_bop:<9s}) -> Can see? {visible}")

# ─── TEST 2: NONEXISTENT / UNRESOLVABLE CAMERA ID ──────────────────────────────
print("\n[TEST 2] Nonexistent / Unresolvable Camera ID:")
msg_unresolvable = f"TEST_UNRESOLVABLE_CAM_{int(time.time())}"
unknown_cam_uid = "cam_ghost_nonexistent_99"

payload_2 = {
    "edge_id": "edge_node_test",
    "timestamp": time.time(),
    "events": [],
    "alerts": [
        {
            "edge_alert_id": 66602,
            "camera_id": unknown_cam_uid,  # Does NOT exist in cameras table
            # NO bop_id
            "severity": "high",
            "alert_type": "intrusion",
            "message": msg_unresolvable,
            "data": {"track_id": 202, "speed": 3.0}
        }
    ]
}

print(f"  Sending POST /api/v1/edge/sync with camera_id='{unknown_cam_uid}' (not in DB)...")
r2 = httpx.post(f"{BASE}/api/v1/edge/sync", json=payload_2, headers={"X-Edge-API-Key": EDGE_KEY})
print(f"  HTTP Status: {r2.status_code}")
print(f"  Response: {r2.json()}")

row2 = cur.execute(
    "SELECT id, alert_type, severity, bop_id, message FROM alerts WHERE message = ?",
    (msg_unresolvable,)
).fetchone()

if row2:
    aid2, atype2, asev2, abop2, amsg2 = row2
    print(f"  DB Record Found: ID={aid2}, bop_id='{abop2}'")
    print(f"  Behavior: Alert accepted and bop_id stamped as '{abop2}'")
else:
    print(f"  DB Record NOT Found: Alert was rejected/dropped.")

# Visibility check for Test 2
print("  Checking role visibility for unresolvable camera alert:")
for uname, _, role, user_bop in demo_users:
    r = httpx.get(f"{BASE}/api/v1/alerts", headers={"Authorization": f"Bearer {tokens[uname]}"})
    alerts = r.json()
    visible = any(a.get("message") == msg_unresolvable for a in alerts)
    print(f"    User {uname:<12s} ({role:<14s}, {user_bop:<9s}) -> Can see? {visible}")

conn.close()
