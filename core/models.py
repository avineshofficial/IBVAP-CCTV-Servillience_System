"""
IBVAP — SQLAlchemy ORM Models
===============================
All data models from §6 of the architecture document.
"""

import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime,
    ForeignKey, JSON, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from core.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    camera_uid = Column(String(50), unique=True, nullable=False)
    bop_id = Column(String(50), nullable=False, default="bop_01")
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    rtsp_url = Column(String(500), nullable=True)
    onvif_profile = Column(String(100), nullable=True)
    homography_matrix = Column(Text, nullable=True)  # JSON-serialized
    is_ptz = Column(Boolean, default=False)
    status = Column(String(20), default="online")  # online / offline / error
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    events = relationship("DetectionEvent", back_populates="camera")
    zones = relationship("Zone", back_populates="camera")


class DetectionEvent(Base):
    __tablename__ = "detection_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    camera_uid = Column(String(50), nullable=False, default="cam_01")
    track_id = Column(Integer, nullable=True)
    event_type = Column(String(50), nullable=False)
    # Types: human, vehicle, face, plate, fence_breach, activity, night_motion
    confidence = Column(Float, nullable=True)
    timestamp = Column(Float, nullable=False)
    thumbnail_ref = Column(String(500), nullable=True)
    clip_ref = Column(String(500), nullable=True)
    geo_lat = Column(Float, nullable=True)
    geo_lng = Column(Float, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    camera = relationship("Camera", back_populates="events")
    alerts = relationship("Alert", secondary="alert_events", back_populates="events")
    audit_records = relationship("AuditRecord", back_populates="event")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    severity = Column(String(20), nullable=False, default="medium")
    # Severity: low, medium, high, critical
    alert_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="new")
    # Status: new, acknowledged, resolved, false_positive
    message = Column(Text, nullable=True)
    bop_id = Column(String(50), nullable=True, default="unassigned")
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    data_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    events = relationship("DetectionEvent", secondary="alert_events", back_populates="alerts")
    assignee = relationship("User", back_populates="assigned_alerts")


class AlertEvent(Base):
    """Association table between alerts and events."""
    __tablename__ = "alert_events"

    alert_id = Column(Integer, ForeignKey("alerts.id"), primary_key=True)
    event_id = Column(Integer, ForeignKey("detection_events.id"), primary_key=True)


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    zone_uid = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    camera_uid = Column(String(50), nullable=False)
    polygon_points_pixel = Column(JSON, nullable=False)
    polygon_points_geo = Column(JSON, nullable=True)
    rule_type = Column(String(30), nullable=False)
    # Types: line_cross, dwell, direction, exclusion
    dwell_threshold = Column(Float, nullable=True, default=30.0)
    direction_vector = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    camera = relationship("Camera", back_populates="zones")


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("detection_events.id"), nullable=True)
    record_hash = Column(String(64), nullable=False)
    prev_hash = Column(String(64), nullable=False)
    merkle_root_ref = Column(String(64), nullable=True)
    timestamp = Column(Float, nullable=False)
    signer = Column(String(100), nullable=True, default="edge_01")
    data_snapshot = Column(Text, nullable=True)  # Canonical JSON snapshot
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    event = relationship("DetectionEvent", back_populates="audit_records")


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_type = Column(String(20), nullable=False)  # face, plate
    reference_hash = Column(String(128), nullable=False)  # Embedding hash or plate hash
    reference_embedding = Column(Text, nullable=True)  # JSON-serialized embedding vector
    label = Column(String(200), nullable=True)  # Descriptive label
    category = Column(String(50), nullable=True)  # wanted, suspect, vip, etc.
    source_agency = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    added_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    creator = relationship("User", back_populates="watchlist_entries")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    email = Column(String(200), nullable=True)
    hashed_password = Column(String(200), nullable=False)
    role = Column(String(30), nullable=False, default="field_officer")
    # Roles: field_officer, post_commander, hq_analyst, admin
    bop_id = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    assigned_alerts = relationship("Alert", back_populates="assignee")
    watchlist_entries = relationship("WatchlistEntry", back_populates="creator")


class SecurityAuditLog(Base):
    """System-wide security event log for RBAC, auth, DPDP, and key management."""
    __tablename__ = "security_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="info")  # info, warning, critical
    actor = Column(String(100), nullable=False, default="system")
    ip_address = Column(String(50), nullable=True, default="127.0.0.1")
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

