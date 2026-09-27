"""Verification probe for Stage B Follow-Ups:
1. Security Endpoints RBAC (logs, stats, dpdp-compliance gated to hq_analyst-or-above; rbac-matrix & audit open)
2. Live Ingestion Path BOP Resolution (POST /edge/sync alert with camera_id='cam_04' and NO bop_id resolves to 'bop_bravo')
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
print("STAGE B FOLLOW-UP VERIFICATION PROBE")
print("=" * 80)

# 1. Log in all 4 demo users
demo_users = [
    ("admin", "admin123", "admin", "hq"),
    ("analyst", "analyst123", "hq_analyst", "hq"),
    ("commander", "commander123", "post_commander", "bop_alpha"),
    ("officer", "officer123", "field_officer", "bop_alpha"),
]

tokens = {}
for uname, pwd, role, bop in demo_users:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"username": uname, "password": pwd})
    if r.status_code != 200:
        print(f"FAILED TO LOGIN: {uname} -> {r.text}")
        exit(1)
    tokens[uname] = r.json()["access_token"]

# ─── ITEM 1: SECURITY ENDPOINTS RBAC AUDIT ─────────────────────────────────────
print("\n[ITEM 1] Security Endpoints Access Across All 4 Roles:")
sec_endpoints = [
    ("GET", "/api/v1/security/stats", "Security Stats (Gated: hq_analyst+)", [200, 200, 403, 403]),
    ("GET", "/api/v1/security/logs", "Security Logs (Gated: hq_analyst+)", [200, 200, 403, 403]),
    ("GET", "/api/v1/security/dpdp-compliance", "DPDP Compliance (Gated: hq_analyst+)", [200, 200, 403, 403]),
    ("GET", "/api/v1/security/rbac-matrix", "RBAC Matrix (Open to All Authenticated)", [200, 200, 200, 200]),
    ("GET", "/api/v1/audit/chain", "Audit Chain (Open to All Authenticated)", [200, 200, 200, 200]),
    ("GET", "/api/v1/audit/stats", "Audit Stats (Open to All Authenticated)", [200, 200, 200, 200]),
]

header_str = f"  {'Endpoint':<34s} | {'admin':^8s} | {'hq_analyst':^10s} | {'post_commander':^14s} | {'field_officer':^13s} | {'Status':^8s}"
print("-" * len(header_str))
print(header_str)
print("-" * len(header_str))

all_sec_passed = True
for method, ep, desc, expected in sec_endpoints:
    codes = []
    for uname, _, _, _ in demo_users:
        h = {"Authorization": f"Bearer {tokens[uname]}"}
        r = httpx.get(f"{BASE}{ep}", headers=h)
        codes.append(r.status_code)
    
    passed = codes == expected
    if not passed:
        all_sec_passed = False
    status_tag = "PASS" if passed else "FAIL"
    print(f"  {ep:<34s} | {codes[0]:^8d} | {codes[1]:^10d} | {codes[2]:^14d} | {codes[3]:^13d} | {status_tag:^8s}")

print(f"\nItem 1 RBAC Verification: {'SUCCESS (All gated/open as specified)' if all_sec_passed else 'FAILURE'}")

# ─── ITEM 2: REAL INGESTION PATH BOP RESOLUTION ────────────────────────────────
print("\n[ITEM 2] Live Ingestion Path BOP Resolution Test:")
test_alert_msg = f"LIVE_INGEST_TEST_CAM04_{int(time.time())}"

ingest_payload = {
    "edge_id": "edge_real_ingest_node",
    "timestamp": time.time(),
    "events": [],
    "alerts": [
        {
            "edge_alert_id": 77701,
            "camera_id": "cam_04",  # cam_04 is assigned to bop_bravo
            "severity": "high",
            "alert_type": "intrusion",
            "message": test_alert_msg,
            "data": {"confidence": 0.94, "zone": "Bravo Perimeter North"}
            # NOTE: Absolutely NO bop_id in payload!
        }
    ]
}

print(f"  1. Sending real POST /api/v1/edge/sync with edge API key...")
print(f"     Payload contains camera_id='cam_04', NO bop_id field.")
r_sync = httpx.post(
    f"{BASE}/api/v1/edge/sync",
    json=ingest_payload,
    headers={"X-Edge-API-Key": EDGE_KEY}
)
print(f"     Status Code: {r_sync.status_code}")
print(f"     Response: {r_sync.json()}")

assert r_sync.status_code == 200, f"Sync failed: {r_sync.text}"
assert r_sync.json()["alerts_received"] >= 1, "Alert was not ingested!"

print("\n  2. Querying SQLite database directly to inspect stamped bop_id...")
conn = sqlite3.connect(PROJECT_ROOT / "ibvap.db")
cur = conn.cursor()
row = cur.execute(
    "SELECT id, alert_type, severity, bop_id, message, created_at FROM alerts WHERE message = ?",
    (test_alert_msg,)
).fetchone()

if row:
    alert_db_id, a_type, a_sev, a_bop, a_msg, a_time = row
    print(f"     Found Alert Row in DB:")
    print(f"       ID:         {alert_db_id}")
    print(f"       Type:       {a_type}")
    print(f"       Severity:   {a_sev}")
    print(f"       bop_id:     {a_bop}  <-- {'CORRECT (Resolved dynamically from cam_04)' if a_bop == 'bop_bravo' else 'INCORRECT'}")
    print(f"       Message:    {a_msg}")
    print(f"       Timestamp:  {a_time}")
    db_passed = (a_bop == "bop_bravo")
else:
    print("     ERROR: Alert not found in database!")
    db_passed = False

print("\n  3. Checking Visibility of the Ingested Alert in GET /api/v1/alerts by Role:")
role_checks = {}
for uname, _, role, user_bop in demo_users:
    h = {"Authorization": f"Bearer {tokens[uname]}"}
    r = httpx.get(f"{BASE}/api/v1/alerts", headers=h)
    assert r.status_code == 200
    alerts = r.json()
    found = any(a.get("message") == test_alert_msg for a in alerts)
    role_checks[uname] = found
    
    expected_see = (role in ("admin", "hq_analyst"))
    match = (found == expected_see)
    print(f"     User: {uname:<12s} (Role: {role:<14s}, BOP: {user_bop:<9s}) -> Can see Bravo Alert? {str(found):<5s} | Expected: {str(expected_see):<5s} ({'PASS' if match else 'FAIL'})")

item2_passed = db_passed and not role_checks["officer"] and not role_checks["commander"] and role_checks["analyst"] and role_checks["admin"]
print(f"\nItem 2 Ingestion Resolution Verification: {'SUCCESS' if item2_passed else 'FAILURE'}")

conn.close()
