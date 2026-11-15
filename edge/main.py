"""
IBVAP — Edge Pipeline Orchestrator
====================================
Main entry point for the edge inference engine.
Coordinates camera → detection → tracking → fence → activity → buffer → sync.
"""

import os
import sys
import cv2
import time
import json
import logging
import asyncio
import collections
import numpy as np
import signal
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from edge.config import EdgeConfig
from edge.ingestion.camera import CameraStream
from edge.inference.tracking import Tracker
from edge.fence.virtual_fence import VirtualFenceEngine
from edge.buffer.local_store import LocalStore
from edge.sync_agent.uplink import SyncAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("IBVAP.Edge")


class EdgePipeline:
    """
    Main edge inference pipeline.
    Processes video frames through detection → tracking → fence → alerts.
    """

    def __init__(self, config: EdgeConfig = None):
        self.config = config or EdgeConfig()
        self._running = False
        self._frame_count = 0
        self._start_time = 0.0
        # Rolling buffer for pre-incident footage: stores every 3rd frame (~5fps into buffer)
        # 60 entries = ~12 seconds of coverage, more than enough for 3.5s pre-incident
        self._frame_buffer = collections.deque(maxlen=60)
        self._active_recorders = []
        self._last_breach_clip_time = 0.0
        self._active_breach_until = 0.0
        self._active_incident_lock_until = 0.0
        self._breached_track_ids = set()
        # Per-person alert cooldown: prevents flooding duplicate alerts for the same person,
        # while ensuring EVERY person who breaches triggers an alert independently
        self._track_alert_cooldown: dict[int, float] = {}

        # Statistics
        self._stats = {
            "frames_processed": 0,
            "detections_total": 0,
            "tracks_active": 0,
            "fence_breaches": 0,
            "alerts_generated": 0,
            "avg_fps": 0.0,
            "avg_latency_ms": 0.0,
        }

    def initialize(self):
        """Initialize all pipeline components."""
        logger.info("=" * 60)
        logger.info("IBVAP Edge Pipeline — Initializing")
        logger.info("=" * 60)

        # Camera
        source = self.config.get_camera_source()
        self.camera = CameraStream(
            source=source,
            camera_id="cam_01",
            target_fps=self.config.camera_fps,
            width=self.config.frame_width,
            height=self.config.frame_height,
        )

        # Tracker (includes detection)
        self.tracker = Tracker(
            model_name=self.config.yolo_model,
            tracker_config=self.config.tracker_type,
            confidence_threshold=self.config.detection_confidence,
            target_classes=self.config.detection_classes,
        )

        # Virtual Fence
        self.fence_engine = VirtualFenceEngine()

        # Night Enhancement (lazy load)
        self._night_enhancer = None

        # Face Detection (lazy load)
        self._face_detector = None

        # ANPR (lazy load)
        self._anpr_engine = None

        # Activity Detection (lazy load)
        self._activity_detector = None

        # Local Buffer
        self.local_store = LocalStore(db_path=self.config.local_db_path)

        # Sync Agent
        self.sync_agent = SyncAgent(
            core_api_url=self.config.core_api_url,
            sync_interval=self.config.sync_interval,
            batch_size=self.config.sync_batch_size,
        )

        logger.info("All components initialized")

    def _get_night_enhancer(self):
        """Lazy-load night enhancement module."""
        if self._night_enhancer is None and self.config.night_enhance_enabled:
            try:
                from edge.inference.night_enhance import NightEnhancer
                self._night_enhancer = NightEnhancer(
                    threshold=self.config.night_enhance_threshold
                )
                logger.info("Night enhancer loaded")
            except Exception as e:
                logger.warning(f"Night enhancer unavailable: {e}")
        return self._night_enhancer

    def _get_face_detector(self):
        """Lazy-load face detection module."""
        if self._face_detector is None and self.config.face_detection_enabled:
            try:
                from edge.inference.face import FaceDetector
                self._face_detector = FaceDetector(
                    model_pack=self.config.face_model_pack,
                )
                logger.info("Face detector loaded")
            except Exception as e:
                logger.warning(f"Face detector unavailable: {e}")
        return self._face_detector

    def _get_anpr_engine(self):
        """Lazy-load ANPR module."""
        if self._anpr_engine is None and self.config.anpr_enabled:
            try:
                from edge.inference.anpr import ANPREngine
                self._anpr_engine = ANPREngine(
                    confidence=self.config.anpr_confidence,
                    vote_frames=self.config.anpr_vote_frames,
                )
                logger.info("ANPR engine loaded")
            except Exception as e:
                logger.warning(f"ANPR engine unavailable: {e}")
        return self._anpr_engine

    def _get_activity_detector(self):
        """Lazy-load activity detection."""
        if self._activity_detector is None and self.config.activity_detection_enabled:
            try:
                from edge.inference.activity import ActivityDetector
                self._activity_detector = ActivityDetector(
                    loiter_threshold=self.config.loiter_threshold,
                    sprint_speed_threshold=self.config.sprint_speed_threshold,
                    group_radius=self.config.group_radius,
                    group_min_count=self.config.group_min_count,
                )
                logger.info("Activity detector loaded")
            except Exception as e:
                logger.warning(f"Activity detector unavailable: {e}")
        return self._activity_detector

    def _sync_zones_to_core(self):
        """Push local fence zones to the core platform so the dashboard can see them.

        Non-fatal: if core is unreachable the edge continues running
        (offline-first — §13 of the architecture doc).
        """
        import httpx

        zones = self.fence_engine.get_zones()
        if not zones:
            return

        base_url = self.config.core_api_url.rstrip("/")
        synced = 0

        for zone in zones:
            payload = {
                "zone_uid": zone.zone_id,
                "name": zone.name,
                "camera_uid": zone.camera_id,
                "polygon_points_pixel": [
                    [float(p[0]), float(p[1])] for p in zone.polygon_points_pixel
                ],
                "rule_type": zone.rule_type.value,
                "dwell_threshold": zone.dwell_threshold,
                "direction_vector": (
                    list(zone.direction_vector) if zone.direction_vector else None
                ),
                "polygon_points_geo": (
                    [list(p) for p in zone.polygon_points_geo]
                    if zone.polygon_points_geo
                    else None
                ),
            }
            try:
                headers = {"X-Edge-API-Key": self.config.edge_api_key}
                resp = httpx.post(
                    f"{base_url}/api/v1/zones",
                    json=payload,
                    headers=headers,
                    timeout=5.0,
                )
                if resp.status_code in (200, 201):
                    synced += 1
                elif resp.status_code == 409 or "UNIQUE constraint" in resp.text:
                    # Zone already exists in core — that's fine
                    synced += 1
                else:
                    logger.warning(
                        f"Zone sync failed for {zone.name}: HTTP {resp.status_code}"
                    )
            except httpx.ConnectError:
                logger.warning(
                    f"Core unreachable at {base_url} — zone sync skipped "
                    f"(edge will operate offline)"
                )
                return
            except Exception as e:
                logger.warning(f"Zone sync error for {zone.name}: {e}")

        if synced:
            logger.info(f"Synced {synced}/{len(zones)} fence zones to core")

    def _pull_zones_from_core(self):
        """Pull virtual fence zones defined in Core (e.g. drawn from dashboard)."""
        import httpx
        from edge.fence.virtual_fence import FenceZone, FenceRuleType

        base_url = self.config.core_api_url.rstrip("/")
        try:
            headers = {"X-Edge-API-Key": self.config.edge_api_key}
            resp = httpx.get(f"{base_url}/api/v1/zones", headers=headers, timeout=3.0)
            if resp.status_code == 200:
                core_zones = resp.json()
                for z in core_zones:
                    if z.get("camera_uid") == self.camera.camera_id or not z.get("camera_uid"):
                        rule_str = z.get("rule_type", "exclusion")
                        try:
                            rule_type = FenceRuleType(rule_str)
                        except Exception:
                            rule_type = FenceRuleType.EXCLUSION
                        
                        pts = [tuple(p) for p in z.get("polygon_points_pixel", [])]
                        if len(pts) >= 2:
                            fz = FenceZone(
                                zone_id=z["zone_uid"],
                                name=z["name"],
                                camera_id=self.camera.camera_id,
                                polygon_points_pixel=pts,
                                rule_type=rule_type,
                                dwell_threshold=float(z.get("dwell_threshold") or 30.0),
                                direction_vector=tuple(z["direction_vector"]) if z.get("direction_vector") else None,
                                is_active=z.get("is_active", True),
                            )
                            self.fence_engine.add_zone(fz)
        except Exception:
            pass

    def _start_incident_clip_recording(self, camera_id: str, track_id: int) -> str:
        """
        Record a focused 8.0-second incident clip (~3.5s BEFORE and ~4.5s AFTER line touch/crossing).
        Calculates exact writer FPS so playback in the web player lasts exactly 7 to 8 seconds at 1x real-time speed.
        """
        try:
            now = time.time()
            # If an active recorder is already running, prevent duplicate/corrupt clips
            if self._active_recorders:
                return self._active_recorders[0]["clip_url"]

            if now - self._last_breach_clip_time < 5.0:
                ts = int(self._last_breach_clip_time)
                return f"/media/clips/incident_{camera_id}_trk{track_id}_{ts}.webm"

            self._last_breach_clip_time = now
            clips_dir = self.config.media_dir / "clips"
            clips_dir.mkdir(parents=True, exist_ok=True)
            ts = int(now)
            filename = f"incident_{camera_id}_trk{track_id}_{ts}.webm"
            out_path = clips_dir / filename

            # 1. Snapshot past ~3.5 seconds of rolling frames (3.5s BEFORE incident)
            pre_incident_frames = [f for t, f in self._frame_buffer if t >= (now - 3.5)]
            if not pre_incident_frames and self._frame_buffer:
                pre_incident_frames = [f for _, f in list(self._frame_buffer)[-15:]]

            rec = {
                "camera_id": camera_id,
                "track_id": track_id,
                "filename": filename,
                "out_path": out_path,
                "clip_url": f"/media/clips/{filename}",
                "frames": list(pre_incident_frames),
                "stop_time": now + 4.5,  # capture 4.5s AFTER touch -> total 8.0s
                "target_duration": 8.0,
            }
            self._active_recorders.append(rec)
            logger.info(
                f"[INCIDENT CAPTURE STARTED] Snapshot {len(pre_incident_frames)} frames (3.5s BEFORE). "
                f"Capturing next 4.5s AFTER touch for track #{track_id} -> total ~8.0s video ({filename})"
            )
            return f"/media/clips/{filename}"
        except Exception as e:
            logger.warning(f"Failed to start incident clip recording: {e}")
            return ""

    def _save_incident_clip(self, camera_id: str, track_id: int) -> str:
        return self._start_incident_clip_recording(camera_id, track_id)

    def _encode_clip_background(self, out_path: Path, frames: list, target_duration: float = 8.0):
        def _encode_worker():
            try:
                if not frames:
                    return
                out_path.parent.mkdir(parents=True, exist_ok=True)
                h, w = frames[0].shape[:2]

                # Dynamically set writer FPS so video playback in HTML5 player is exactly 7.5 - 8.0s!
                num_frames = len(frames)
                fps = max(3.0, min(30.0, round(num_frames / target_duration, 1)))

                webm_path = out_path.with_suffix(".webm")
                fourcc = cv2.VideoWriter_fourcc(*"VP80")
                writer = cv2.VideoWriter(str(webm_path), fourcc, fps, (w, h))
                for f in frames:
                    writer.write(f)
                writer.release()
                logger.info(
                    f"[EVIDENCE CAPTURE COMPLETE] Saved 7.5s WebM clip: {webm_path.name} "
                    f"({num_frames} frames @ {fps} FPS = {num_frames/fps:.1f}s playback)"
                )
            except Exception as e:
                logger.warning(f"Failed to encode incident clip: {e}")

        import threading
        threading.Thread(target=_encode_worker, daemon=True).start()

    def _save_thumbnail(self, frame, track_id: int, frame_id: int) -> str:
        """Save a detection thumbnail to disk."""
        thumb_dir = self.config.media_dir / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        filename = f"thumb_{frame_id}_{track_id}.jpg"
        path = thumb_dir / filename
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return str(path)

    def _draw_overlays(self, frame, tracks, fence_zones, breaches):
        """Draw modern high-precision surveillance overlays with breach alerts.
        Performance-optimized: draws directly on frame to avoid full-frame copies.
        """
        overlay = frame  # Draw directly on frame — no copy (caller handles copy if needed)
        h, w = overlay.shape[:2]

        breached_track_ids = {b.track_id: b for b in breaches}
        has_active_breach = len(breaches) > 0 or (time.time() < self._active_breach_until)
        if time.time() < self._active_breach_until:
            for tid in self._breached_track_ids:
                breached_track_ids[tid] = True

        # Real-time check: mark EVERY track whose position is inside the restricted area or touching the line
        # This runs every frame independently of cooldowns so ALL persons who breach are shown in RED
        exclusion_zones = [z for z in fence_zones if z.rule_type.value == "exclusion" and z.is_active]
        line_zones = [z for z in fence_zones if z.rule_type.value == "line_cross" and z.is_active]

        for track in tracks:
            if track.track_id in breached_track_ids:
                continue  # Already marked

            gp = track.ground_point
            bx1, by1, bx2, by2 = [int(c) for c in track.bbox] if track.bbox and len(track.bbox) == 4 else (0, 0, 0, 0)
            center = ((bx1 + bx2) / 2.0, (by1 + by2) / 2.0)
            bottom_center = ((bx1 + bx2) / 2.0, float(by2))

            is_intruder = False

            # Check exclusion polygons (restricted alert area)
            for ez in exclusion_zones:
                poly = ez.polygon_points_pixel
                if (self.fence_engine._point_in_polygon(gp, poly) or
                    self.fence_engine._point_in_polygon(center, poly) or
                    self.fence_engine._point_in_polygon(bottom_center, poly) or
                    self.fence_engine._point_in_polygon((float(bx1), float(by2)), poly) or
                    self.fence_engine._point_in_polygon((float(bx2), float(by2)), poly)):
                    is_intruder = True
                    break

            # Check border line (if touching line, or on restricted side below line)
            if not is_intruder:
                for lz in line_zones:
                    lpts = lz.polygon_points_pixel
                    if len(lpts) == 2:
                        lx1, ly1 = lpts[0]
                        lx2, ly2 = lpts[1]
                        line_y = (ly1 + ly2) / 2.0
                        min_x, max_x = min(lx1, lx2), max(lx1, lx2)
                        # Does bounding box touch or cross the border line?
                        touches = (by1 - 10 <= line_y <= by2 + 10) and (bx2 >= min_x and bx1 <= max_x)
                        # Is ground point or body bottom on the restricted side below the border line?
                        below_line = (gp[1] >= line_y or by2 >= line_y) and (bx2 >= min_x and bx1 <= max_x)
                        if touches or below_line:
                            is_intruder = True
                            break

            if is_intruder:
                breached_track_ids[track.track_id] = True
                self._breached_track_ids.add(track.track_id)
                has_active_breach = True

        # ──────────────────────────────────────────────────────────
        # 1. Draw Virtual Fence Zones & Border Lines
        # ──────────────────────────────────────────────────────────
        for zone in fence_zones:
            pts = np.array([(int(p[0]), int(p[1])) for p in zone.polygon_points_pixel], np.int32)
            if len(pts) < 2:
                continue

            zone_breached = any(b.zone_id == zone.zone_id for b in breaches) or (has_active_breach and ("restricted" in zone.zone_id or zone.rule_type.value == "exclusion"))
            
            if zone.rule_type.value == "line_cross":
                # ── Solid Red Border Line (clear divider between SAFE and RESTRICTED) ──
                pulse = int(time.time() * 4) % 2 == 0
                line_color = (255, 255, 255) if (zone_breached and pulse) else (0, 0, 255)
                # Solid visible line: 3px normal, 4px when breached
                line_th = 4 if zone_breached else 3

                if len(pts) == 2:
                    p1, p2 = tuple(pts[0]), tuple(pts[1])
                    # Primary solid red line
                    cv2.line(overlay, p1, p2, line_color, line_th, cv2.LINE_AA)

                    # Subtle endpoint markers
                    cv2.circle(overlay, p1, 4, (0, 0, 255), -1)
                    cv2.circle(overlay, p2, 4, (0, 0, 255), -1)

                    # Centered "-- RESTRICTED BORDER LINE --" label
                    mid_x = (p1[0] + p2[0]) // 2
                    mid_y = (p1[1] + p2[1]) // 2
                    status_txt = "RESTRICTED BORDER LINE // TOUCH BREACH" if zone_breached else "RESTRICTED BORDER LINE"
                    tag_color = (0, 0, 255) if zone_breached else (0, 220, 255)
                    # Get text size for centering
                    label = f"-- {status_txt} --"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                    text_x = mid_x - tw // 2
                    text_y = max(16, mid_y - 8)
                    # Dark background behind text for readability
                    cv2.rectangle(overlay, (text_x - 4, text_y - th - 4), (text_x + tw + 4, text_y + 4), (0, 0, 0), -1)
                    cv2.putText(
                        overlay,
                        label,
                        (text_x, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.42,
                        tag_color,
                        1,
                        cv2.LINE_AA,
                    )
                else:
                    cv2.polylines(overlay, [pts], True, line_color, line_th, cv2.LINE_AA)

            elif zone.rule_type.value == "exclusion":
                # ── RESTRICTED RED AREA — performance optimized ──
                # Use ROI-bounded blending instead of full-frame copy
                if zone_breached:
                    pulse = int(time.time() * 4) % 2 == 0
                    fill_color = (0, 0, 230) if pulse else (0, 30, 200)
                    opacity = 0.35
                    border_color = (0, 0, 255)
                    border_th = 3
                else:
                    fill_color = (0, 0, 180)
                    opacity = 0.28
                    border_color = (0, 0, 200)
                    border_th = 2

                # Compute bounding rect of the polygon for ROI-only blending
                bx, by, bw, bh = cv2.boundingRect(pts)
                bx2, by2 = min(bx + bw, w), min(by + bh, h)
                bx, by = max(bx, 0), max(by, 0)
                if bw > 0 and bh > 0:
                    roi = overlay[by:by2, bx:bx2].copy()
                    # Shift polygon points to ROI-local coords
                    local_pts = pts - np.array([bx, by])
                    sub_roi = roi.copy()
                    cv2.fillPoly(sub_roi, [local_pts], fill_color)
                    cv2.addWeighted(sub_roi, opacity, roi, 1.0 - opacity, 0, roi)
                    overlay[by:by2, bx:bx2] = roi

                # Border edge
                cv2.polylines(overlay, [pts], True, border_color, border_th, cv2.LINE_AA)

                # ── Warning Triangle Icon ──
                try:
                    cx = int(sum(p[0] for p in pts) / len(pts))
                    cy = int(sum(p[1] for p in pts) / len(pts))

                    tri_h, tri_w = 40, 44
                    tri_pts = np.array([
                        (cx, cy - tri_h // 2),
                        (cx - tri_w // 2, cy + tri_h // 2),
                        (cx + tri_w // 2, cy + tri_h // 2),
                    ], np.int32)

                    cv2.fillPoly(overlay, [tri_pts], (0, 0, 200))
                    cv2.polylines(overlay, [tri_pts], True, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.line(overlay, (cx, cy - tri_h // 2 + 12), (cx, cy + tri_h // 2 - 14), (255, 255, 255), 3, cv2.LINE_AA)
                    cv2.circle(overlay, (cx, cy + tri_h // 2 - 8), 3, (255, 255, 255), -1, cv2.LINE_AA)
                except Exception:
                    pass


            elif zone.rule_type.value == "dwell":
                # Dwell Monitoring Zone
                color = (0, 200, 255)
                cv2.polylines(overlay, [pts], True, color, 2)
                lx, ly = pts[0][0] + 8, pts[0][1] + 20
                lbl = f"[DWELL] {zone.name.upper()} ({int(zone.dwell_threshold)}s THRESHOLD)"
                cv2.putText(overlay, lbl, (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # ──────────────────────────────────────────────────────────
        # 2. Draw Target Bounding Boxes & Trajectories
        # ──────────────────────────────────────────────────────────
        for track in tracks:
            x1, y1, x2, y2 = [int(c) for c in track.bbox]
            bw, bh = max(10, x2 - x1), max(10, y2 - y1)
            is_breached = track.track_id in breached_track_ids

            # Primary track color
            if is_breached:
                box_color = (0, 0, 255)  # Bright Red for Intruder Breach
            elif track.class_name == "person":
                box_color = (0, 220, 255)  # Amber Yellow/Orange for Person
            else:
                box_color = (255, 180, 0)  # Cyan/Blue for Vehicle

            # Draw Main Bounding Box
            box_thick = 3 if is_breached else 2
            cv2.rectangle(overlay, (x1, y1), (x2, y2), box_color, box_thick)

            # Draw Corner Reticles for High Precision Aesthetic
            corner_len = min(15, bw // 4, bh // 4)
            # Top-Left corner
            cv2.line(overlay, (x1, y1), (x1 + corner_len, y1), (255, 255, 255), 2)
            cv2.line(overlay, (x1, y1), (x1, y1 + corner_len), (255, 255, 255), 2)
            # Bottom-Right corner
            cv2.line(overlay, (x2, y2), (x2 - corner_len, y2), (255, 255, 255), 2)
            cv2.line(overlay, (x2, y2), (x2, y2 - corner_len), (255, 255, 255), 2)

            # Label Header Tag
            if is_breached:
                label_text = f"[INTRUDER] #{track.track_id} {track.class_name.upper()} | {track.confidence:.0%}"
                bg_color = (0, 0, 220)
                text_color = (255, 255, 255)
            else:
                label_text = f"#{track.track_id} {track.class_name.upper()} ({int(track.confidence * 100)}%)"
                bg_color = box_color
                text_color = (0, 0, 0)

            (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(overlay, (x1, y1 - th - 10), (x1 + tw + 8, y1), bg_color, -1)
            cv2.putText(overlay, label_text, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, text_color, 1, cv2.LINE_AA)

            # Ground Point (Base Center Contact Point)
            gx, gy = int(track.ground_point[0]), int(track.ground_point[1])
            if is_breached:
                # Target Reticle on Ground Point for Breached Intruder
                cv2.circle(overlay, (gx, gy), 10, (0, 0, 255), 2)
                cv2.circle(overlay, (gx, gy), 4, (0, 0, 255), -1)
                cv2.line(overlay, (gx - 14, gy), (gx + 14, gy), (0, 0, 255), 1)
                cv2.line(overlay, (gx, gy - 14), (gx, gy + 14), (0, 0, 255), 1)
            else:
                cv2.circle(overlay, (gx, gy), 5, (0, 255, 0), -1)

            # Ground Trajectory History Line
            if len(track.ground_point_history) > 1:
                trail_color = (0, 0, 255) if is_breached else box_color
                pts_trail = np.array([(int(p[0]), int(p[1])) for p in track.ground_point_history], np.int32)
                cv2.polylines(overlay, [pts_trail], False, trail_color, 2 if is_breached else 1)

        # ──────────────────────────────────────────────────────────
        # 3. Top Banner Trigger for Border Breach Intrusion Alert
        # ──────────────────────────────────────────────────────────
        if has_active_breach:
            pulse = int(time.time() * 5) % 2 == 0
            banner_bg = (0, 0, 230) if pulse else (0, 0, 160)
            cv2.rectangle(overlay, (0, 0), (w, 42), banner_bg, -1)
            cv2.line(overlay, (0, 42), (w, 42), (255, 255, 255), 2)
            breach_msg = "[ALERT SIGNAL] RESTRICTED BORDER PERIMETER BREACHED! INTRUSION DETECTED"
            (tw, th), _ = cv2.getTextSize(breach_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.60, 2)
            tx = max(10, (w - tw) // 2)
            cv2.putText(overlay, breach_msg, (tx, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 255), 2, cv2.LINE_AA)
            # Skip old 2-line drawing below
            pass



        # ──────────────────────────────────────────────────────────
        # 4. Systems Status Overlay (Sleek Compact Top-Left Pill)
        # ──────────────────────────────────────────────────────────
        fps_val = self._stats['avg_fps']
        active_cnt = self._stats['tracks_active']
        stats_text = f"CAM-01 | {fps_val:.1f} FPS | {active_cnt} TARGET{'S' if active_cnt != 1 else ''}"
        (tw, th), _ = cv2.getTextSize(stats_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(overlay, (12, 12), (24 + tw, 20 + th + 6), (15, 20, 25), -1)
        cv2.rectangle(overlay, (12, 12), (24 + tw, 20 + th + 6), (0, 255, 200), 1)
        cv2.putText(overlay, stats_text, (18, 18 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 200), 1, cv2.LINE_AA)

        return overlay

    def run(self, show_display: bool = True, max_frames: int = 0):
        """
        Run the full edge inference pipeline.

        Args:
            show_display: Show OpenCV window with overlays
            max_frames: Stop after N frames (0 = unlimited)
        """
        self.initialize()
        self._running = True
        self._start_time = time.time()

        # Pull any existing custom zones from core
        self._pull_zones_from_core()

        # Initialize border line + restricted area if not present
        if not self.fence_engine.get_zones():
            self.fence_engine.create_restricted_border_zone(
                self.config.frame_width, self.config.frame_height, self.camera.camera_id
            )

        # Always ensure the restricted AREA polygon exists below the border line
        # (create_restricted_area_zone internally checks for duplicates)
        self.fence_engine.create_restricted_area_zone(
            self.config.frame_width, self.config.frame_height, self.camera.camera_id
        )


        # Push zones to core so dashboard can see them
        self._sync_zones_to_core()
        # Pull any existing custom zones from core
        self._pull_zones_from_core()

        # Start non-blocking background sync thread so video loop NEVER stutters
        def _bg_sync():
            while self._running:
                time.sleep(float(self.config.sync_interval))
                try:
                    self._pull_zones_from_core()
                    asyncio.run(self.sync_agent.sync_batch(self.local_store))
                except Exception:
                    pass
        import threading
        t_sync = threading.Thread(target=_bg_sync, daemon=True)
        t_sync.start()

        logger.info("=" * 60)
        logger.info("IBVAP Edge Pipeline — Running")
        logger.info(f"  Source: {self.config.get_camera_source()}")
        logger.info(f"  Target FPS: {self.config.camera_fps}")
        logger.info(f"  Detection confidence: {self.config.detection_confidence}")
        logger.info(f"  Show display: {show_display}")
        logger.info("=" * 60)

        try:
            for packet in self.camera.frames():
                if not self._running:
                    break

                if max_frames > 0 and self._frame_count >= max_frames:
                    break

                frame_start = time.time()
                frame = packet.frame
                self._frame_count += 1

                # --- Night Enhancement ---
                enhanced = False
                night_enhancer = self._get_night_enhancer()
                if night_enhancer:
                    frame, enhanced = night_enhancer.enhance_if_needed(frame)

                # --- Detection + Tracking ---
                tracks = self.tracker.update(
                    frame,
                    frame_id=packet.frame_id,
                    camera_id=packet.camera_id,
                    timestamp=packet.timestamp,
                )

                # --- Virtual Fence Evaluation ---
                all_breaches = []
                for track in tracks:
                    breaches = self.fence_engine.evaluate(
                        track_id=track.track_id,
                        object_class=track.class_name,
                        ground_point=track.ground_point,
                        confidence=track.confidence,
                        camera_id=packet.camera_id,
                        timestamp=packet.timestamp,
                        track_history=track.ground_point_history,
                        bbox=track.bbox,
                    )
                    all_breaches.extend(breaches)

                # --- Face Detection (on person crops) ---
                face_detector = self._get_face_detector()
                face_results = []
                if face_detector:
                    person_tracks = [t for t in tracks if t.class_name == "person"]
                    for track in person_tracks[:3]:  # Limit to 3 persons per frame
                        x1, y1, x2, y2 = [int(c) for c in track.bbox]
                        h, w = frame.shape[:2]
                        crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                        if crop.size > 0:
                            faces = face_detector.detect(crop, track.track_id)
                            face_results.extend(faces)

                # --- ANPR (on vehicle crops) ---
                anpr_engine = self._get_anpr_engine()
                plate_results = []
                if anpr_engine:
                    vehicle_tracks = [
                        t for t in tracks
                        if t.class_name in ("car", "truck", "bus", "motorcycle")
                    ]
                    for track in vehicle_tracks[:3]:
                        x1, y1, x2, y2 = [int(c) for c in track.bbox]
                        h, w = frame.shape[:2]
                        crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                        if crop.size > 0:
                            plate = anpr_engine.read_plate(crop, track.track_id)
                            if plate:
                                plate_results.append(plate)

                # --- Activity Detection ---
                activity_detector = self._get_activity_detector()
                activities = []
                if activity_detector:
                    activities = activity_detector.analyze(tracks, packet.timestamp)

                # --- Store Events Locally (sampled at 1Hz to eliminate disk IO bottleneck) ---
                if self._frame_count % 15 == 0:
                    for track in tracks:
                        event_data = {
                            "track_id": track.track_id,
                            "class": track.class_name,
                            "bbox": track.bbox,
                            "ground_point": track.ground_point,
                            "speed": track.speed,
                            "dwell_time": track.dwell_time,
                            "enhanced": enhanced,
                        }
                        self.local_store.store_event(
                            event_type=track.class_name,
                            camera_id=packet.camera_id,
                            data=event_data,
                            track_id=track.track_id,
                            confidence=track.confidence,
                            timestamp=packet.timestamp,
                        )

                # --- Render Surveillance HUD Overlay ---
                cached_zones = self.fence_engine.get_zones()
                overlay = self._draw_overlays(
                    frame, tracks, cached_zones, all_breaches
                )
                # Store frame with timestamp for incident extraction (copy only every 3rd frame to reduce memory pressure)
                if self._frame_count % 3 == 0:
                    self._frame_buffer.append((time.time(), overlay.copy()))

                # Feed active incident recorders
                if self._active_recorders:
                    frame_copy = overlay.copy()  # Single copy shared across all recorders
                    still_active = []
                    for rec in self._active_recorders:
                        rec["frames"].append(frame_copy)
                        if time.time() >= rec["stop_time"]:
                            self._encode_clip_background(rec["out_path"], rec["frames"], rec.get("target_duration", 8.0))
                        else:
                            still_active.append(rec)
                    self._active_recorders = still_active

                # Save live frame for real-time frontend streaming (throttled to ~5 FPS to reduce disk IO)
                if self._frame_count % 3 == 0:
                    try:
                        ret, jpeg_buf = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if ret:
                            live_path = self.config.media_dir / f"live_{packet.camera_id}.jpg"
                            tmp_path = self.config.media_dir / f"live_{packet.camera_id}.tmp.jpg"
                            with open(tmp_path, "wb") as f:
                                f.write(jpeg_buf)
                            os.replace(tmp_path, live_path)
                    except Exception:
                        pass

                # Store fence breach alerts for all breaching persons (per-person cooldown)
                now_breach = time.time()
                if all_breaches:
                    self._active_breach_until = now_breach + 5.0
                    for b in all_breaches:
                        self._breached_track_ids.add(b.track_id)

                    # Group breaches by track_id so each breaching person is alerted independently
                    breaches_by_track = {}
                    for b in all_breaches:
                        if b.track_id not in breaches_by_track:
                            breaches_by_track[b.track_id] = b

                    new_alerts_created = False
                    for trk_id, breach in breaches_by_track.items():
                        # Per-person alert cooldown: ensures every person triggers an alert,
                        # while rate-limiting repeat alerts for the exact same person to 5.0s
                        last_alert_time = self._track_alert_cooldown.get(trk_id, 0.0)
                        if now_breach - last_alert_time >= 5.0:
                            self._track_alert_cooldown[trk_id] = now_breach

                            clip_url = ""
                            if len(self._frame_buffer) >= 3:
                                clip_url = self._save_incident_clip(packet.camera_id, breach.track_id)

                            breach_data = {
                                "zone_id": breach.zone_id,
                                "zone_name": breach.zone_name,
                                "breach_type": breach.breach_type,
                                "track_id": breach.track_id,
                                "object_class": breach.object_class,
                                "ground_point": breach.ground_point_pixel,
                                "dwell_time": breach.dwell_time,
                                "clip_url": clip_url,
                                "camera_id": packet.camera_id,
                            }
                            event_id = self.local_store.store_event(
                                event_type="fence_breach",
                                camera_id=packet.camera_id,
                                data=breach_data,
                                track_id=breach.track_id,
                                confidence=breach.confidence,
                                timestamp=breach.timestamp,
                            )
                            self.local_store.store_alert(
                                event_id=event_id,
                                severity=breach.severity,
                                alert_type="fence_breach",
                                message=f"{breach.breach_type} by {breach.object_class} in {breach.zone_name} (Track #{breach.track_id})",
                                data=breach_data,
                            )
                            self._stats["fence_breaches"] += 1
                            self._stats["alerts_generated"] += 1
                            new_alerts_created = True

                    if new_alerts_created:
                        # Instantly push to core so the dashboard receives the alert signals for all breached persons
                        import threading
                        threading.Thread(
                            target=lambda: asyncio.run(self.sync_agent.sync_batch(self.local_store)),
                            daemon=True
                        ).start()
                elif now_breach > self._active_breach_until:
                    self._breached_track_ids.clear()

                # --- Update Stats ---
                elapsed = time.time() - self._start_time
                frame_latency = (time.time() - frame_start) * 1000
                self._stats["frames_processed"] = self._frame_count
                self._stats["detections_total"] += len(tracks)
                self._stats["tracks_active"] = self.tracker.total_active
                self._stats["avg_fps"] = self._frame_count / elapsed if elapsed > 0 else 0
                self._stats["avg_latency_ms"] = frame_latency

                # --- Display ---
                if show_display:
                    try:
                        cv2.imshow("IBVAP Edge Pipeline", overlay)
                        key = cv2.waitKey(1) & 0xFF
                        if key == ord("q"):
                            logger.info("Quit key pressed")
                            break
                    except Exception:
                        pass

                # Uplink sync runs decoupled in background thread (no frame stall)

                # Periodic zone refresh handled in background _bg_sync thread

                # Log periodically
                if self._frame_count % 100 == 0:
                    logger.info(
                        f"Frame {self._frame_count:>6d} | "
                        f"FPS: {self._stats['avg_fps']:5.1f} | "
                        f"Latency: {frame_latency:6.1f}ms | "
                        f"Tracks: {self.tracker.total_active:3d} | "
                        f"Breaches: {self._stats['fence_breaches']}"
                    )

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.shutdown()

    def shutdown(self):
        """Clean shutdown of all components."""
        if getattr(self, "_is_shutdown", False):
            return
        self._is_shutdown = True
        self._running = False
        logger.info("Shutting down edge pipeline...")

        self.camera.release()
        try:
            # Sync remaining events to Core API
            asyncio.run(self.sync_agent.sync_batch(self.local_store))
        except Exception as e:
            logger.debug(f"Final sync failed: {e}")
        self.sync_agent.stop()
        self.local_store.close()

        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

        elapsed = time.time() - self._start_time
        logger.info("=" * 60)
        logger.info("IBVAP Edge Pipeline — Shutdown Complete")
        logger.info(f"  Runtime: {elapsed:.1f}s")
        logger.info(f"  Frames: {self._frame_count}")
        logger.info(f"  Avg FPS: {self._stats['avg_fps']:.1f}")
        logger.info(f"  Breaches: {self._stats['fence_breaches']}")
        logger.info(f"  Alerts: {self._stats['alerts_generated']}")
        logger.info("=" * 60)

    @property
    def stats(self) -> dict:
        return self._stats.copy()


def main():
    """Entry point for running the edge pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description="IBVAP Edge Inference Pipeline")
    parser.add_argument("--source", type=str, default=None, help="Video source (file, RTSP URL, or webcam index)")
    parser.add_argument("--gui", action="store_true", default=False, help="Open local desktop OpenCV window (default: False, web view only)")
    parser.add_argument("--fps", type=int, default=15, help="Target FPS")
    parser.add_argument("--confidence", type=float, default=0.6, help="Detection confidence threshold")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames (0=unlimited)")
    args = parser.parse_args()

    config = EdgeConfig()
    if args.source:
        config.camera_source = args.source
    if args.fps:
        config.camera_fps = args.fps
    if args.confidence:
        config.detection_confidence = args.confidence

    pipeline = EdgePipeline(config=config)

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        logger.info("Signal received, shutting down...")
        pipeline.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    pipeline.run(
        show_display=args.gui,
        max_frames=args.max_frames,
    )


if __name__ == "__main__":
    main()
