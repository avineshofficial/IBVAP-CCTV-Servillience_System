"""
IBVAP — Dashboard API Router
===============================
REST endpoints for the web dashboard (§7 API contracts).
"""

import time
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_

from core.database import get_db
from core.auth.jwt_auth import get_current_user, require_role, require_edge_api_key
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


# ──────────────────────────────────────
# Dashboard Stats
# ──────────────────────────────────────

@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get aggregated dashboard statistics with BOP scoping."""
    if user.role not in ("admin", "hq_analyst"):
        cam_cond = Camera.bop_id == user.bop_id
        total_cameras = (await db.execute(select(func.count(Camera.id)).where(cam_cond))).scalar() or 0
        cameras_online = (await db.execute(select(func.count(Camera.id)).where(and_(cam_cond, Camera.status == "online")))).scalar() or 0
        total_events = (await db.execute(select(func.count(DetectionEvent.id)).join(Camera, DetectionEvent.camera_uid == Camera.camera_uid).where(cam_cond))).scalar() or 0
        alert_cond = (Alert.bop_id == user.bop_id) | (Alert.bop_id.is_(None))
        total_alerts = (await db.execute(select(func.count(Alert.id)).where(alert_cond))).scalar() or 0
        active_alerts = (await db.execute(select(func.count(Alert.id)).where(and_(alert_cond, Alert.status == "new")))).scalar() or 0
        critical_alerts = (await db.execute(select(func.count(Alert.id)).where(and_(alert_cond, Alert.severity == "critical", Alert.status == "new")))).scalar() or 0
    else:
        total_cameras = (await db.execute(select(func.count(Camera.id)))).scalar() or 0
        cameras_online = (await db.execute(
            select(func.count(Camera.id)).where(Camera.status == "online")
        )).scalar() or 0
        total_events = (await db.execute(select(func.count(DetectionEvent.id)))).scalar() or 0
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
        system_uptime=time.time() - _start_time,
    )


# ──────────────────────────────────────
# Cameras
# ──────────────────────────────────────

@router.get("/cameras", response_model=list[CameraResponse])
async def list_cameras(user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all cameras with BOP scoping (hq_analyst/admin see all)."""
    query = select(Camera)
    if user.role not in ("admin", "hq_analyst"):
        query = query.where(Camera.bop_id == user.bop_id)
    result = await db.execute(query.order_by(Camera.id))
    cameras = result.scalars().all()
    return cameras


@router.post("/cameras", response_model=CameraResponse)
async def create_camera(camera: CameraCreate, user = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """Register a new camera (admin only)."""
    db_camera = Camera(**camera.model_dump())
    db.add(db_camera)
    await db.commit()
    await db.refresh(db_camera)
    return db_camera


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
async def list_zones(user = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all virtual fence zone definitions with BOP scoping."""
    query = select(Zone)
    if user.role not in ("admin", "hq_analyst"):
        query = query.join(Camera, Zone.camera_uid == Camera.camera_uid).where(Camera.bop_id == user.bop_id)
    result = await db.execute(query.order_by(Zone.id))
    return result.scalars().all()


@router.post("/zones", response_model=ZoneResponse)
async def create_zone(
    zone: ZoneCreate,
    edge_key: str = Depends(require_edge_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a new virtual fence zone (idempotent on zone_uid; secured with X-Edge-API-Key)."""
    # Check if zone_uid already exists — return it if so (idempotent for edge restarts)
    existing = await db.execute(select(Zone).where(Zone.zone_uid == zone.zone_uid))
    existing_zone = existing.scalar_one_or_none()
    if existing_zone:
        return existing_zone

    db_zone = Zone(**zone.model_dump())
    db.add(db_zone)
    await db.commit()
    await db.refresh(db_zone)
    return db_zone


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
