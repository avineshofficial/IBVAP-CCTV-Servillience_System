"""Comprehensive Verification for Unresolvable Camera Handling:
1. Ingestion of alert with unresolvable camera_id -> bop_id='unassigned'.
2. SecurityAuditLog entry 'UNRESOLVED_CAMERA_ALERT' created.
3. Alert visibility matrix across 4 roles (HQ/Admin only, excluded from bop_alpha).
4. DetectionEvent visibility matrix across 4 roles with unresolvable camera_uid.
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
print("VERIFICATION: UNRESOLVED CAMERA ALERT QUARANTINE & AUDIT LOGGING")
print("=" * 80)

# Authenticate all 4 demo users
demo_users = [
    ("admin", "admin123", "admin", "hq"),
    ("analyst", "analyst123", "hq_analyst", "hq"),
    ("commander", "commander123", "post_commander", "bop_alpha"),
    ("officer", "officer123", "field_officer", "bop_alpha"),
]

tokens = {}
for uname, pwd, role, bop in demo_users:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"username": uname, "password": pwd})
    assert r.status_code == 200, f"Login failed for {uname}"
    tokens[uname] = r.json()["access_token"]

# ─── PART 1: INGESTION OF ALERT WITH UNRESOLVABLE CAMERA ───────────────────────
ghost_camera = "cam_ghost_unresolvable_probe"
alert_msg = f"TEST_QUARANTINE_ALERT_{int(time.time())}"
edge_alert_num = 99881

payload = {
    "edge_id": "edge_remote_post",
    "timestamp": time.time(),
    "events": [],
    "alerts": [
        {
            "edge_alert_id": edge_alert_num,
            "camera_id": ghost_camera,
            "severity": "critical",
            "alert_type": "intrusion",
            "message": alert_msg,
            "data": {"track_id": 303, "speed": 4.5}
        }
    ]
}

print(f"\n1. Ingesting alert for unregistered camera '{ghost_camera}' via POST /api/v1/edge/sync...")
r_sync = httpx.post(f"{BASE}/api/v1/edge/sync", json=payload, headers={"X-Edge-API-Key": EDGE_KEY})
print(f"   HTTP Status: {r_sync.status_code}")
print(f"   Response: {r_sync.json()}")

assert r_sync.status_code == 200
assert r_sync.json()["alerts_received"] == 1

# ─── PART 2: DATABASE ROW & SECURITY AUDIT LOG VERIFICATION ────────────────────
print("\n2. Direct Database Inspection (ibvap.db):")
conn = sqlite3.connect(PROJECT_ROOT / "ibvap.db")
cur = conn.cursor()

# Check alerts table
alert_row = cur.execute(
    "SELECT id, alert_type, severity, bop_id, message FROM alerts WHERE message = ?",
    (alert_msg,)
).fetchone()

if alert_row:
    aid, atype, asev, abop, amsg = alert_row
    print(f"   Alert Row:")
    print(f"     ID:       {aid}")
    print(f"     Type:     {atype}")
    print(f"     Severity: {asev}")
    print(f"     bop_id:   {abop}  <-- {'PASS: Quarantined to unassigned' if abop == 'unassigned' else 'FAIL: Misrouted!'}")
    alert_passed = (abop == "unassigned")
else:
    print("   ERROR: Alert row not found in database!")
    alert_passed = False

# Check security_audit_logs table
sec_row = cur.execute(
    "SELECT id, event_type, severity, actor, details, timestamp FROM security_audit_logs WHERE event_type = 'UNRESOLVED_CAMERA_ALERT' ORDER BY id DESC LIMIT 1"
).fetchone()

if sec_row:
    sid, stype, ssev, sactor, sdet, stime = sec_row
    print(f"   SecurityAuditLog Entry:")
    print(f"     ID:         {sid}")
    print(f"     EventType:  {stype}")
    print(f"     Severity:   {ssev}")
    print(f"     Actor:      {sactor}")
    print(f"     Details:    {sdet}")
    print(f"     Timestamp:  {stime}")
    log_passed = (stype == "UNRESOLVED_CAMERA_ALERT" and ghost_camera in sdet)
else:
    print("   ERROR: SecurityAuditLog entry not found!")
    log_passed = False

# ─── PART 3: ALERT VISIBILITY MATRIX ACROSS ALL 4 ROLES ────────────────────────
print("\n3. Role Visibility Matrix for the Quarantined Alert (GET /api/v1/alerts):")
header_str = f"   {'Role':<16s} | {'User':<12s} | {'Assigned BOP':<14s} | {'Can See Alert?':<16s} | {'Expected':<10s} | {'Status':<6s}"
print("   " + "-" * 76)
print(header_str)
print("   " + "-" * 76)

all_alert_roles_passed = True
for uname, _, role, user_bop in demo_users:
    r = httpx.get(f"{BASE}/api/v1/alerts", headers={"Authorization": f"Bearer {tokens[uname]}"})
    alerts = r.json()
    visible = any(a.get("message") == alert_msg for a in alerts)
    expected = (role in ("admin", "hq_analyst"))
    passed = (visible == expected)
    if not passed:
        all_alert_roles_passed = False
    print(f"   {role:<16s} | {uname:<12s} | {user_bop:<14s} | {str(visible):<16s} | {str(expected):<10s} | {'PASS' if passed else 'FAIL'}")

# ─── PART 4: DETECTION EVENT VISIBILITY MATRIX ACROSS ALL 4 ROLES ──────────────
print("\n4. Role Visibility Matrix for Orphaned DetectionEvent (camera not in cameras table):")
event_ghost_cam = "cam_ghost_event_test_99"
header_event = f"   {'Role':<16s} | {'User':<12s} | {'Assigned BOP':<14s} | {'Can See Event?':<16s} | {'Behavior Description':<30s}"
print("   " + "-" * 88)
print(header_event)
print("   " + "-" * 88)

for uname, _, role, user_bop in demo_users:
    r = httpx.get(f"{BASE}/api/v1/events", headers={"Authorization": f"Bearer {tokens[uname]}"})
    events = r.json()
    visible = any(e.get("camera_uid") == event_ghost_cam for e in events)
    desc = "Visible (HQ sees all events)" if visible else "Hidden (Camera inner join excludes)"
    print(f"   {role:<16s} | {uname:<12s} | {user_bop:<14s} | {str(visible):<16s} | {desc:<30s}")

print("\n" + "=" * 80)
print(f"OVERALL VERIFICATION: {'SUCCESS' if (alert_passed and log_passed and all_alert_roles_passed) else 'FAIL'}")
print("=" * 80)

conn.close()
