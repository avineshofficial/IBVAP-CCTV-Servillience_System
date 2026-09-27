"""Verification script for UNRESOLVED_CAMERA_EVENT and improved ID labeling in SecurityAuditLog."""
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
print("VERIFICATION: EVENT & ALERT AUDIT LOGGING FOR UNREGISTERED CAMERAS")
print("=" * 80)

edge_event_uid = 12301
edge_alert_uid = 45601
unreg_cam = "cam_unregistered_sensor_99"
msg = f"TEST_AUDIT_LOG_IDS_{int(time.time())}"

payload = {
    "edge_id": "edge_remote_node",
    "timestamp": time.time(),
    "events": [
        {
            "edge_event_id": edge_event_uid,
            "event_type": "motion",
            "camera_id": unreg_cam,
            "track_id": 999,
            "timestamp": time.time(),
            "data": {"class": "vehicle"}
        }
    ],
    "alerts": [
        {
            "edge_alert_id": edge_alert_uid,
            "camera_id": unreg_cam,
            "severity": "high",
            "alert_type": "intrusion",
            "message": msg,
            "data": {"track_id": 999, "speed": 5.0}
        }
    ]
}

print(f"\n1. Sending POST /api/v1/edge/sync with event and alert for '{unreg_cam}'...")
r = httpx.post(f"{BASE}/api/v1/edge/sync", json=payload, headers={"X-Edge-API-Key": EDGE_KEY})
print(f"   HTTP Status: {r.status_code}")
print(f"   Response: {r.json()}")

assert r.status_code == 200
assert r.json()["events_received"] == 1
assert r.json()["alerts_received"] == 1

print("\n2. Inspecting SQLite Database for Core Primary Keys and Audit Logs:")
conn = sqlite3.connect(PROJECT_ROOT / "ibvap.db")
cur = conn.cursor()

# Get the inserted event row
event_row = cur.execute(
    "SELECT id, camera_uid, event_type FROM detection_events WHERE camera_uid = ? ORDER BY id DESC LIMIT 1",
    (unreg_cam,)
).fetchone()
assert event_row is not None
event_core_id, ev_cam, ev_type = event_row
print(f"   DetectionEvent in DB: Core ID={event_core_id}, Camera='{ev_cam}', Type='{ev_type}'")

# Get the inserted alert row
alert_row = cur.execute(
    "SELECT id, alert_type, severity, bop_id, message FROM alerts WHERE message = ?",
    (msg,)
).fetchone()
assert alert_row is not None
alert_core_id, al_type, al_sev, al_bop, al_msg = alert_row
print(f"   Alert in DB:          Core ID={alert_core_id}, bop_id='{al_bop}', Severity='{al_sev}'")

# Check UNRESOLVED_CAMERA_EVENT log
event_log_row = cur.execute(
    "SELECT id, event_type, severity, actor, details, timestamp FROM security_audit_logs WHERE event_type = 'UNRESOLVED_CAMERA_EVENT' ORDER BY id DESC LIMIT 1"
).fetchone()
assert event_log_row is not None
elog_id, elog_type, elog_sev, elog_actor, elog_det, elog_time = event_log_row
print(f"\n   [UNRESOLVED_CAMERA_EVENT Log]")
print(f"     Log ID:    {elog_id}")
print(f"     Severity:  {elog_sev}")
print(f"     Details:   {elog_det}")

expected_event_snippet = f"DetectionEvent ID {event_core_id} (edge_event_id: {edge_event_uid}"
event_log_ok = (expected_event_snippet in elog_det and unreg_cam in elog_det)
print(f"     Verification: {'PASS (matches core event ID and edge ID)' if event_log_ok else 'FAIL'}")

# Check UNRESOLVED_CAMERA_ALERT log
alert_log_row = cur.execute(
    "SELECT id, event_type, severity, actor, details, timestamp FROM security_audit_logs WHERE event_type = 'UNRESOLVED_CAMERA_ALERT' ORDER BY id DESC LIMIT 1"
).fetchone()
assert alert_log_row is not None
alog_id, alog_type, alog_sev, alog_actor, alog_det, alog_time = alert_log_row
print(f"\n   [UNRESOLVED_CAMERA_ALERT Log]")
print(f"     Log ID:    {alog_id}")
print(f"     Severity:  {alog_sev}")
print(f"     Details:   {alog_det}")

expected_alert_snippet = f"Alert ID {alert_core_id} (edge_alert_id: {edge_alert_uid}"
alert_log_ok = (expected_alert_snippet in alog_det and unreg_cam in alog_det and "Quarantined to bop_id='unassigned'" in alog_det)
print(f"     Verification: {'PASS (matches core alert ID and edge ID)' if alert_log_ok else 'FAIL'}")

conn.close()
print("\n" + "=" * 80)
print(f"ALL TESTS PASSED: {'YES' if (event_log_ok and alert_log_ok and al_bop == 'unassigned') else 'NO'}")
print("=" * 80)
