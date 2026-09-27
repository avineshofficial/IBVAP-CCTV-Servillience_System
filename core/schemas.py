"""
IBVAP — Pydantic Schemas
===========================
Request/response schemas for all API endpoints.
"""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


# ──────────────────────────────────────
# Camera Schemas
# ──────────────────────────────────────

class CameraBase(BaseModel):
    name: str
    camera_uid: str
    bop_id: str = "bop_01"
    lat: Optional[float] = None
    lng: Optional[float] = None
    rtsp_url: Optional[str] = None
    is_ptz: bool = False

class CameraCreate(CameraBase):
    pass

class CameraResponse(CameraBase):
    id: int
    status: str = "online"
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# Detection Event Schemas
# ──────────────────────────────────────

class EventBase(BaseModel):
    camera_uid: str = "cam_01"
    track_id: Optional[int] = None
    event_type: str
    confidence: Optional[float] = None
    timestamp: float
    metadata_json: Optional[dict] = None

class EventCreate(EventBase):
    thumbnail_ref: Optional[str] = None
    clip_ref: Optional[str] = None

class EventResponse(EventBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# Alert Schemas
# ──────────────────────────────────────

class AlertBase(BaseModel):
    severity: str = "medium"
    alert_type: str
    message: Optional[str] = None
    bop_id: Optional[str] = "bop_alpha"
    data_json: Optional[dict] = None

class AlertCreate(AlertBase):
    event_ids: list[int] = []

class AlertUpdate(BaseModel):
    status: Optional[str] = None  # acknowledged, resolved, false_positive
    notes: Optional[str] = None
    assigned_to: Optional[int] = None

class AlertResponse(AlertBase):
    id: int
    status: str = "new"
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# Zone (Virtual Fence) Schemas
# ──────────────────────────────────────

class ZoneBase(BaseModel):
    zone_uid: str
    name: str
    camera_uid: str
    polygon_points_pixel: list[list[float]]
    rule_type: str  # line_cross, dwell, direction, exclusion
    dwell_threshold: Optional[float] = 30.0
    direction_vector: Optional[list[float]] = None
    polygon_points_geo: Optional[list[list[float]]] = None

class ZoneCreate(ZoneBase):
    pass

class ZoneResponse(ZoneBase):
    id: int
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# Audit Schemas
# ──────────────────────────────────────

class AuditRecordResponse(BaseModel):
    id: int
    event_id: Optional[int]
    record_hash: str
    prev_hash: str
    timestamp: float
    signer: Optional[str]
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class AuditVerifyResponse(BaseModel):
    event_id: int
    verified: bool
    chain_length: int
    computed_hash: str
    stored_hash: str
    message: str


# ──────────────────────────────────────
# Watchlist Schemas
# ──────────────────────────────────────

class WatchlistEntryBase(BaseModel):
    entry_type: str  # face, plate
    label: Optional[str] = None
    category: Optional[str] = None
    source_agency: Optional[str] = None

class WatchlistCreate(WatchlistEntryBase):
    reference_data: str  # Embedding or plate text to hash

class WatchlistResponse(WatchlistEntryBase):
    id: int
    reference_hash: str
    is_active: bool
    added_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# User / Auth Schemas
# ──────────────────────────────────────

class UserBase(BaseModel):
    username: str
    name: str
    email: Optional[str] = None
    role: str = "field_officer"
    bop_id: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ──────────────────────────────────────
# Edge Sync Schemas
# ──────────────────────────────────────

class EdgeSyncEvent(BaseModel):
    edge_event_id: int
    event_type: str
    camera_id: str
    track_id: Optional[int] = None
    confidence: Optional[float] = None
    timestamp: float
    data: dict = {}
    thumbnail_path: Optional[str] = None

class EdgeSyncAlert(BaseModel):
    edge_alert_id: int
    event_id: Optional[int] = None
    camera_id: Optional[str] = None
    bop_id: Optional[str] = None
    severity: str
    alert_type: str
    message: Optional[str] = None
    data: dict = {}

class EdgeSyncPayload(BaseModel):
    edge_id: str
    timestamp: float
    events: list[EdgeSyncEvent] = []
    alerts: list[EdgeSyncAlert] = []

class EdgeSyncResponse(BaseModel):
    status: str
    events_received: int
    alerts_received: int
    message: str


# ──────────────────────────────────────
# Dashboard Stats
# ──────────────────────────────────────

class DashboardStats(BaseModel):
    total_cameras: int = 0
    cameras_online: int = 0
    total_events: int = 0
    total_alerts: int = 0
    active_alerts: int = 0
    critical_alerts: int = 0
    total_tracks: int = 0
    fence_breaches: int = 0
    system_uptime: float = 0.0
