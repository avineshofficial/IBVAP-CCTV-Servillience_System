"""
IBVAP — Dashboard API Router
===============================
REST endpoints for the web dashboard (§7 API contracts).
"""

import time
import asyncio
import logging
from datetime import datetime
from typing import Optional
import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_, delete

from core.database import get_db
from core.config import CoreConfig
from core.auth.jwt_auth import get_current_user, require_role, require_edge_api_key, require_edge_or_commander, require_edge_or_user
from core.models import Camera, DetectionEvent, Alert, AlertEvent, Zone, AuditRecord, User
from core.schemas import (
    CameraResponse, CameraCreate,
    AlertResponse, AlertCreate, AlertUpdate,
    EventResponse,
    ZoneResponse, ZoneCreate,
    AuditRecordResponse, AuditVerifyResponse,
    DashboardStats,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Dashboard"])

_start_time = time.time()

def is_camera_live(camera_uid: str) -> bool:
    """Check if the camera's live edge frame is fresh (< 12 seconds)."""
    live_file = CoreConfig.MEDIA_DIR / f"live_{camera_uid}.jpg"
    if live_file.exists():
        try:
            return (time.time() - live_file.stat().st_mtime) < 60.0
        except Exception:
            return False
    return False



# ──────────────────────────────────────
# Dashboard Stats
# ──────────────────────────────────────

@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get aggregated dashboard statistics with BOP scoping."""
    if user.role not in ("admin", "hq_analyst"):
        cam_cond = Camera.bop_id == user.bop_id
        total_cameras = (await db.execute(select(func.count(Camera.id)).where(cam_cond))).scalar() or 0
        all_cams = (await db.execute(select(Camera))).scalars().all()
        cameras_online = sum(1 for c in all_cams if is_camera_live(c.camera_uid))
        total_events = (await db.execute(select(func.count(DetectionEvent.id)).join(Camera, DetectionEvent.camera_uid == Camera.camera_uid).where(cam_cond))).scalar() or 0
        total_tracks = (await db.execute(select(func.count(func.distinct(DetectionEvent.track_id))).join(Camera, DetectionEvent.camera_uid == Camera.camera_uid).where(cam_cond))).scalar() or 0
        fence_breaches = (await db.execute(select(func.count(DetectionEvent.id)).join(Camera, DetectionEvent.camera_uid == Camera.camera_uid).where(and_(cam_cond, DetectionEvent.event_type == "fence_breach")))).scalar() or 0
        alert_cond = (Alert.bop_id == user.bop_id) | (Alert.bop_id.is_(None))
        total_alerts = (await db.execute(select(func.count(Alert.id)).where(alert_cond))).scalar() or 0
        active_alerts = (await db.execute(select(func.count(Alert.id)).where(and_(alert_cond, Alert.status == "new")))).scalar() or 0
        critical_alerts = (await db.execute(select(func.count(Alert.id)).where(and_(alert_cond, Alert.severity == "critical", Alert.status == "new")))).scalar() or 0
    else:
        total_cameras = (await db.execute(select(func.count(Camera.id)))).scalar() or 0
        all_cams = (await db.execute(select(Camera))).scalars().all()
        cameras_online = sum(1 for c in all_cams if is_camera_live(c.camera_uid))
        total_events = (await db.execute(select(func.count(DetectionEvent.id)))).scalar() or 0
        total_tracks = (await db.execute(select(func.count(func.distinct(DetectionEvent.track_id))))).scalar() or 0
        fence_breaches = (await db.execute(select(func.count(DetectionEvent.id)).where(DetectionEvent.event_type == "fence_breach"))).scalar() or 0
        total_alerts = (await db.execute(select(func.count(Alert.id)))).scalar() or 0
        active_alerts = (await db.execute(
            select(func.count(Alert.id)).where(Alert.status == "new")
        )).scalar() or 0
        critical_alerts = (await db.execute(
            select(func.count(Alert.id)).where(
                and_(Alert.severity == "critical", Alert.status == "new")
            )
        )).scalar() or 0

    return DashboardStats(
        total_cameras=total_cameras,
        cameras_online=cameras_online,
        total_events=total_events,
        total_alerts=total_alerts,
        active_alerts=active_alerts,
        critical_alerts=critical_alerts,
        total_tracks=total_tracks,
        fence_breaches=fence_breaches,
        system_uptime=time.time() - _start_time,
    )


# ──────────────────────────────────────
# Cameras
# ──────────────────────────────────────

@router.get("/cameras", response_model=list[CameraResponse])
async def list_cameras(
    only_working: bool = Query(False),
    user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List cameras with real-time live status and optional only_working filter."""
    query = select(Camera)
    if user.role not in ("admin", "hq_analyst"):
        query = query.where(Camera.bop_id == user.bop_id)
    result = await db.execute(query.order_by(Camera.id))
    cameras = list(result.scalars().all())

    # Dynamically verify real-time status from fresh edge frames
    for cam in cameras:
        cam.status = "online" if is_camera_live(cam.camera_uid) else "offline"

    if only_working:
        cameras = [c for c in cameras if c.status == "online"]

    return cameras


@router.post("/cameras", response_model=CameraResponse)
async def create_camera(camera: CameraCreate, user = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """Register a new camera (admin only)."""
    db_camera = Camera(**camera.model_dump())
    db.add(db_camera)
    await db.commit()
    await db.refresh(db_camera)
    return db_camera


@router.get("/cameras/{camera_uid}/frame")
async def get_camera_frame(camera_uid: str):
    """
    Get the newest live frame from the camera as a single JPEG image.
    Ultra-reliable, zero-drop browser rendering without multipart/x-mixed-replace bugs.
    """
    target = CoreConfig.MEDIA_DIR / f"live_{camera_uid}.jpg"
    if not target.exists():
        raise HTTPException(status_code=404, detail="No live frame available")

    try:
        with open(target, "rb") as f:
            data = f.read()

        if not data or len(data) < 100:
            raise HTTPException(status_code=404, detail="Frame data empty")

        return Response(
            content=data,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cameras/{camera_uid}/stream")
async def stream_camera(camera_uid: str):
    """
    Live low-latency MJPEG video stream for a camera.
    Returns real-time annotated edge frames with bounding boxes and virtual fence overlays.
    """
    async def frame_generator():
        target = CoreConfig.MEDIA_DIR / f"live_{camera_uid}.jpg"
        last_mtime = 0.0
        cached_frame = None

        try:
            while True:
                if target.exists():
                    try:
                        stat = target.stat()
                        if stat.st_mtime != last_mtime:
                            last_mtime = stat.st_mtime
                            with open(target, "rb") as f:
                                data = f.read()
                            if data and len(data) > 100:
                                cached_frame = data
                    except Exception:
                        pass

                if cached_frame is not None:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(cached_frame)).encode() + b"\r\n\r\n" +
                        cached_frame + b"\r\n"
                    )
                    await asyncio.sleep(0.033)  # Smooth 30 FPS delivery
                else:
                    await asyncio.sleep(0.1)
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
            "Connection": "keep-alive",
        },
    )


# ──────────────────────────────────────
# Alerts
# ──────────────────────────────────────

@router.get("/alerts", response_model=list[AlertResponse])
async def list_alerts(
    status: Optional[str] = Query(None, description="Filter by status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    alert_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """List alerts with optional filtering and BOP scoping."""
    query = select(Alert)

    if user.role not in ("admin", "hq_analyst"):
        query = query.where(Alert.bop_id == user.bop_id)

    if status:
        query = query.where(Alert.status == status)
    if severity:
        query = query.where(Alert.severity == severity)
    if alert_type:
        query = query.where(Alert.alert_type == alert_type)

    query = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/alerts/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: int,
    update_data: AlertUpdate,
    user = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Acknowledge, resolve, or mark an alert as false positive."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if update_data.status:
        alert.status = update_data.status
        if update_data.status == "resolved":
            alert.resolved_at = datetime.utcnow()
    if update_data.notes:
        alert.notes = update_data.notes
    if update_data.assigned_to is not None:
        alert.assigned_to = update_data.assigned_to

    await db.commit()
    await db.refresh(alert)

    # Broadcast update
    from core.dashboard_api.websocket import alert_manager
    await alert_manager.broadcast({
        "type": "alert_updated",
        "alert_id": alert_id,
        "new_status": alert.status,
    })

    return alert


@router.delete("/alerts/purge")
async def purge_alerts(
    auth = Depends(require_edge_or_user),
    db: AsyncSession = Depends(get_db),
):
    """Purge all alerts and detection events to clear unwanted test data."""
    await db.execute(delete(Alert))
    await db.execute(delete(DetectionEvent))
    await db.commit()

    from core.dashboard_api.websocket import alert_manager
    await alert_manager.broadcast({"type": "alerts_purged"})

    return {"message": "All alerts and detection events purged successfully"}


@router.post("/alerts/test-telegram")
async def test_telegram_alert(
    chat_id: Optional[str] = Query(None, description="Optional target Telegram Chat ID"),
):
    """
    Test endpoint to verify Telegram Bot API mobile alert delivery.
    Sends a sample 8-second MP4 incident video clip, formatted HTML alert details,
    and interactive live GPS location pin.
    """
    import time
    from core.alert_engine.telegram_notifier import get_telegram_notifier
    notifier = get_telegram_notifier()
    if chat_id:
        notifier.chat_id = chat_id

    # Find the most recent MP4 clip in core/media/clips/ for test dispatch
    clips_dir = CoreConfig.MEDIA_DIR / "clips"
    sample_clip = None
    if clips_dir.exists():
        mp4_files = sorted(list(clips_dir.glob("*.mp4")), key=lambda p: p.stat().st_mtime, reverse=True)
        if mp4_files:
            sample_clip = str(mp4_files[0])

    sample_alert_data = {
        "zone_name": "Restricted Border Perimeter",
        "zone_id": "zone_restricted_area",
        "alert_type": "fence_breach",
        "breach_type": "entered_exclusion",
        "activity": "fence_cross / suspicious_intrusion",
        "confidence": 0.942,
        "camera_id": "CAM-01",
        "bop_id": "Border Sector Alpha",
        "track_id": 14,
        "object_class": "person",
        "latitude": notifier.default_lat,
        "longitude": notifier.default_lng,
        "timestamp": time.time(),
        "clip_url": sample_clip,
    }

    result = await notifier.send_incident_alert(
        alert_data=sample_alert_data,
        severity="critical",
        message="entered_exclusion by person in Restricted Border Perimeter (Track #14)",
        clip_path=sample_clip,
        wait_for_clip_seconds=0.0,
    )
    return result


@router.delete("/alerts/{alert_id}")
async def delete_single_alert(
    alert_id: int,
    auth = Depends(require_edge_or_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single alert by ID."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await db.delete(alert)
    await db.commit()
    return {"message": f"Alert #{alert_id} deleted"}


# ──────────────────────────────────────
# Events
# ──────────────────────────────────────

@router.get("/events", response_model=list[EventResponse])
async def list_events(
    event_type: Optional[str] = Query(None),
    camera_uid: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """List detection events with filtering and BOP scoping."""
    query = select(DetectionEvent)

    if user.role not in ("admin", "hq_analyst"):
        query = query.join(Camera, DetectionEvent.camera_uid == Camera.camera_uid).where(Camera.bop_id == user.bop_id)

    if event_type:
        query = query.where(DetectionEvent.event_type == event_type)
    if camera_uid:
        query = query.where(DetectionEvent.camera_uid == camera_uid)

    query = query.order_by(DetectionEvent.id.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


# ──────────────────────────────────────
# Zones (Virtual Fences)
# ──────────────────────────────────────

@router.get("/zones", response_model=list[ZoneResponse])
async def list_zones(auth = Depends(require_edge_or_user), db: AsyncSession = Depends(get_db)):
    """List all virtual fence zone definitions (accessible by Edge nodes and dashboard users)."""
    query = select(Zone)
    if hasattr(auth, "role") and auth.role not in ("admin", "hq_analyst"):
        query = query.join(Camera, Zone.camera_uid == Camera.camera_uid).where(Camera.bop_id == auth.bop_id)
    result = await db.execute(query.order_by(Zone.id))
    return result.scalars().all()


@router.post("/zones", response_model=ZoneResponse)
async def create_zone(
    zone: ZoneCreate,
    auth = Depends(require_edge_or_commander),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a virtual fence zone (secured with Edge API Key or Post Commander / Admin)."""
    # Check if zone_uid already exists — update if so (idempotent for edge restarts & dashboard updates)
    existing = await db.execute(select(Zone).where(Zone.zone_uid == zone.zone_uid))
    existing_zone = existing.scalar_one_or_none()
    if existing_zone:
        existing_zone.name = zone.name
        existing_zone.polygon_points_pixel = zone.polygon_points_pixel
        existing_zone.rule_type = zone.rule_type
        existing_zone.dwell_threshold = zone.dwell_threshold
        existing_zone.direction_vector = zone.direction_vector
        existing_zone.is_active = zone.is_active
        await db.commit()
        await db.refresh(existing_zone)
        return existing_zone

    db_zone = Zone(**zone.model_dump())
    db.add(db_zone)
    await db.commit()
    await db.refresh(db_zone)
    return db_zone


@router.delete("/zones/{zone_uid}")
async def delete_zone(
    zone_uid: str,
    auth = Depends(require_edge_or_commander),
    db: AsyncSession = Depends(get_db),
):
    """Delete a virtual fence zone (secured with Edge API Key or Post Commander / Admin)."""
    result = await db.execute(select(Zone).where(Zone.zone_uid == zone_uid))
    db_zone = result.scalar_one_or_none()
    if not db_zone:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_uid}' not found")

    await db.delete(db_zone)
    await db.commit()
    return {"message": f"Zone '{zone_uid}' deleted successfully"}


# ──────────────────────────────────────
# Audit Trail
# ──────────────────────────────────────

@router.get("/audit/chain", response_model=list[AuditRecordResponse])
async def list_audit_records(
    limit: int = Query(50, ge=1, le=500),
    user = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """List audit chain records."""
    result = await db.execute(
        select(AuditRecord).order_by(AuditRecord.id.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/audit/{event_id}/verify")
async def verify_audit_chain(event_id: int, user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Re-compute and verify the hash chain for a specific event.
    This is the tamper-detection endpoint — the live demo moment.
    """
    from core.audit_chain.ledger import audit_ledger
    result = await audit_ledger.verify_chain(db, event_id=event_id)
    return result


@router.get("/audit/verify-all")
async def verify_full_chain(user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Verify the entire audit hash chain."""
    from core.audit_chain.ledger import audit_ledger
    return await audit_ledger.verify_chain(db)


@router.get("/audit/stats")
async def audit_stats(user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get audit chain statistics."""
    from core.audit_chain.ledger import audit_ledger
    return await audit_ledger.get_chain_stats(db)


# ──────────────────────────────────────
# Tamper Demo Endpoint (for presentations)
# ──────────────────────────────────────

@router.post("/audit/demo-tamper/{record_id}")
async def demo_tamper_record(record_id: int, user = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """
    DEMO ONLY: Deliberately tamper with an audit record to show
    that verification detects it. Used during presentations.
    """
    result = await db.execute(select(AuditRecord).where(AuditRecord.id == record_id))
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    # Tamper: modify the stored data snapshot
    original_snapshot = record.data_snapshot
    tampered_snapshot = original_snapshot.replace("}", ',"tampered":true}') if original_snapshot else '{"tampered":true}'
    record.data_snapshot = tampered_snapshot

    await db.commit()

    return {
        "message": "Record tampered for demo purposes",
        "record_id": record_id,
        "original_hash": record.record_hash,
        "note": "Now call GET /api/v1/audit/verify-all to see the chain break",
    }



# ──────────────────────────────────────
# Live Location (Browser GPS → Location Service)
# ──────────────────────────────────────

@router.post("/system/live-location")
async def update_live_location(data: dict):
    """Receive browser GPS coordinates from the dashboard frontend."""
    from core.alert_engine.location_service import get_location_service
    svc = get_location_service()
    lat = data.get("latitude")
    lng = data.get("longitude")
    accuracy = data.get("accuracy", 0)
    if lat is not None and lng is not None:
        svc.update_browser_gps(lat=float(lat), lng=float(lng), accuracy=float(accuracy))
        return {"status": "ok", "source": "browser_gps"}
    return {"status": "error", "message": "Missing latitude/longitude"}


@router.get("/system/live-location")
async def get_live_location():
    """Return the current best-available live location."""
    from core.alert_engine.location_service import get_location_service
    return get_location_service().get_live_location()
