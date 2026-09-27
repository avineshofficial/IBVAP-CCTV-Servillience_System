"""
IBVAP — Ingestion API Router
==============================
Receives edge sync payloads (POST /api/v1/edge/sync).
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.auth.jwt_auth import require_edge_api_key
from core.models import DetectionEvent, Alert, AlertEvent, Camera, SecurityAuditLog
from core.schemas import EdgeSyncPayload, EdgeSyncResponse
from core.alert_engine.engine import AlertEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/edge", tags=["Edge Sync"])

alert_engine = AlertEngine()


@router.post("/sync", response_model=EdgeSyncResponse)
async def edge_sync(
    payload: EdgeSyncPayload,
    edge_key: str = Depends(require_edge_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive a batch of events and alerts from an edge node.
    This is the primary data ingestion endpoint (secured with X-Edge-API-Key).
    """
    events_received = 0
    alerts_received = 0

    try:
        # Process events
        for edge_event in payload.events:
            db_event = DetectionEvent(
                camera_uid=edge_event.camera_id,
                track_id=edge_event.track_id,
                event_type=edge_event.event_type,
                confidence=edge_event.confidence,
                timestamp=edge_event.timestamp,
                metadata_json=edge_event.data,
                thumbnail_ref=edge_event.thumbnail_path,
            )
            db.add(db_event)
            events_received += 1
            await db.flush()

            # Check if camera exists in Camera table
            cam = (await db.execute(select(Camera).where(Camera.camera_uid == edge_event.camera_id))).scalar_one_or_none()
            if not cam:
                sec_log = SecurityAuditLog(
                    event_type="UNRESOLVED_CAMERA_EVENT",
                    severity="warning",
                    actor=payload.edge_id or "edge_sync",
                    ip_address="127.0.0.1",
                    details=f"DetectionEvent ID {db_event.id} (edge_event_id: {edge_event.edge_event_id}, type: '{edge_event.event_type}') received with unresolvable camera_id '{edge_event.camera_id}'."
                )
                db.add(sec_log)

        # Process alerts
        for edge_alert in payload.alerts:
            # Run through alert engine for confidence gating and dedup
            should_alert, severity = alert_engine.evaluate(
                alert_type=edge_alert.alert_type,
                severity=edge_alert.severity,
                data=edge_alert.data,
            )

            if should_alert:
                alert_bop = getattr(edge_alert, "bop_id", None) or (edge_alert.data.get("bop_id") if isinstance(edge_alert.data, dict) else None)
                camera_uid = getattr(edge_alert, "camera_id", None) or (edge_alert.data.get("camera_id") if isinstance(edge_alert.data, dict) else None) or (edge_alert.data.get("camera_uid") if isinstance(edge_alert.data, dict) else None)
                if not camera_uid and edge_alert.event_id:
                    for ev in payload.events:
                        if ev.edge_event_id == edge_alert.event_id:
                            camera_uid = ev.camera_id
                            break
                if not alert_bop and camera_uid:
                    cam = (await db.execute(select(Camera).where(Camera.camera_uid == camera_uid))).scalar_one_or_none()
                    if cam:
                        alert_bop = cam.bop_id
                if not alert_bop:
                    alert_bop = "unassigned"

                db_alert = Alert(
                    severity=severity,
                    alert_type=edge_alert.alert_type,
                    status="new",
                    message=edge_alert.message,
                    bop_id=alert_bop,
                    data_json=edge_alert.data,
                )
                db.add(db_alert)
                alerts_received += 1
                await db.flush()

                if alert_bop == "unassigned":
                    sec_log = SecurityAuditLog(
                        event_type="UNRESOLVED_CAMERA_ALERT",
                        severity="warning",
                        actor=payload.edge_id or "edge_sync",
                        ip_address="127.0.0.1",
                        details=f"Alert ID {db_alert.id} (edge_alert_id: {edge_alert.edge_alert_id}, type: '{edge_alert.alert_type}') received with unresolvable camera_id '{camera_uid or 'unknown'}'. Quarantined to bop_id='unassigned'."
                    )
                    db.add(sec_log)

                # Import here to avoid circular reference
                from core.audit_chain.ledger import audit_ledger
                await audit_ledger.append_record(db, db_alert)

        await db.commit()

        # Broadcast to WebSocket clients
        from core.dashboard_api.websocket import alert_manager
        if alerts_received > 0:
            await alert_manager.broadcast({
                "type": "new_alerts",
                "count": alerts_received,
                "edge_id": payload.edge_id,
                "timestamp": payload.timestamp,
            })

        logger.info(
            f"Sync from {payload.edge_id}: {events_received} events, "
            f"{alerts_received} alerts ingested"
        )

        return EdgeSyncResponse(
            status="ok",
            events_received=events_received,
            alerts_received=alerts_received,
            message=f"Ingested {events_received} events and {alerts_received} alerts",
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"Sync error: {e}")
        return EdgeSyncResponse(
            status="error",
            events_received=0,
            alerts_received=0,
            message=str(e),
        )
