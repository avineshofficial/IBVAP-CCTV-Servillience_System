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
from typing import Optional, Tuple, Dict, List, Any

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

        # ── Incident Clip Recording (Strict 8s: 4s Pre + 4s Post) ──
        # Pre-event ring buffer: stores (monotonic_timestamp, frame) tuples.
        # Continuously pruned to hold exactly the last PRE_ALERT_BUFFER_SECONDS (4.0s)
        # of annotated frames at full inference FPS (every frame, not subsampled).
        self._pre_event_buffer: collections.deque = collections.deque()
        # Active clip recorder state (at most ONE active capture at a time)
        self._clip_recorder = None  # dict or None
        self._clip_lock = False     # True while an 8s capture window is in progress

        # ── 10-Second Zone-Level Alert Cooldown ──
        # State machine: ARMED (ready) → COOLDOWN (10s timer active)
        # Key: zone_id → monotonic timestamp when cooldown expires
        self._zone_cooldown_until: dict[str, float] = {}
        self._breached_track_ids = set()
        self._active_breach_until = 0.0

        # State flags for smooth live streaming and low-latency processing
        self._live_frame_writing = False
        self._zone_contours: dict[str, np.ndarray] = {}
        self._breach_face_scanned: set[int] = set()
        self._breach_anpr_scanned: set[int] = set()
        self._sync_in_progress = False

        # Background CPU ThreadPoolExecutor for asynchronous non-blocking I/O
        # (clip encoding, disk thumbnail writing, live frame streaming, core uplink sync, and Telegram alerts)
        from concurrent.futures import ThreadPoolExecutor
        self._io_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ibvap_cpu_io")

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

        # Tracker (YOLO26 detection + ByteTrack with RTX 3050 CUDA / FP16 acceleration & Stride Optimization)
        self.tracker = Tracker(
            model_name=self.config.get_yolo_model_path(),
            tracker_config=self.config.tracker_type,
            confidence_threshold=self.config.detection_confidence,
            target_classes=self.config.detection_classes,
            device=self.config.get_yolo_device(),
            half=self.config.is_half_precision(),
            imgsz=self.config.yolo_imgsz,
            stride=self.config.get_inference_stride(),
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
        """Lazy-load face detection module with GPU acceleration."""
        if self._face_detector is None and self.config.face_detection_enabled:
            try:
                from edge.inference.face import FaceDetector
                self._face_detector = FaceDetector(
                    model_pack=self.config.face_model_pack,
                    device=self.config.get_yolo_device(),
                )
                logger.info("Face detector loaded")
            except Exception as e:
                logger.warning(f"Face detector unavailable: {e}")
        return self._face_detector

    def _get_anpr_engine(self):
        """Lazy-load ANPR module with GPU acceleration."""
        if self._anpr_engine is None and self.config.anpr_enabled:
            try:
                from edge.inference.anpr import ANPREngine
                self._anpr_engine = ANPREngine(
                    confidence=self.config.anpr_confidence,
                    vote_frames=self.config.anpr_vote_frames,
                    device=self.config.get_yolo_device(),
                )
                logger.info("ANPR engine loaded")
            except Exception as e:
                logger.warning(f"ANPR engine unavailable: {e}")
        return self._anpr_engine

    def _get_activity_detector(self):
        """Lazy-load activity detection (CPU ML with n_jobs=1 for real-time inference without contention)."""
        if self._activity_detector is None and self.config.activity_detection_enabled:
            try:
                from edge.inference.activity import ActivityDetector
                self._activity_detector = ActivityDetector(
                    loiter_threshold=self.config.loiter_threshold,
                    sprint_speed_threshold=self.config.sprint_speed_threshold,
                    group_radius=self.config.group_radius,
                    group_min_count=self.config.group_min_count,
                    n_jobs=1,
                )
                logger.info("Activity detector loaded (CPU Random Forest + Rules)")
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
            resp = httpx.get(f"{base_url}/api/v1/zones", headers=headers, timeout=2.0)
            if resp.status_code == 200:
                self._core_reachable = True
                core_zones = resp.json()
                for z in core_zones:
                    # Ignore legacy screen-splitting line-cross zone
                    if z.get("zone_uid") == "zone_border_line":
                        continue
                    if not z.get("is_active", True):
                        continue
                    if z.get("camera_uid") == self.camera.camera_id or not z.get("camera_uid"):
                        rule_str = z.get("rule_type", "exclusion")
                        try:
                            rule_type = FenceRuleType(rule_str)
                        except Exception:
                            rule_type = FenceRuleType.EXCLUSION
                        
                        pts = [tuple(p) for p in z.get("polygon_points_pixel", [])]
                        if len(pts) >= 3:
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
            self._core_reachable = False

    def _prune_pre_event_buffer(self):
        """Remove frames older than PRE_ALERT_BUFFER_SECONDS from the pre-event ring buffer."""
        cutoff = time.monotonic() - self.config.pre_alert_buffer_seconds
        while self._pre_event_buffer and self._pre_event_buffer[0][0] < cutoff:
            self._pre_event_buffer.popleft()

    def _start_clip_capture(
        self,
        camera_id: str,
        track_id: int,
        alert_data: Optional[dict] = None,
        severity: str = "critical",
        message: str = "",
    ) -> str:
        """
        Start a strict 8-second incident clip capture (4s pre + 4s post, with dynamic compensation).

        Returns the clip URL path, or "" on failure.
        """
        try:
            if self._clip_lock:
                # Capture already in progress — return existing clip URL
                if self._clip_recorder:
                    return self._clip_recorder["clip_url"]
                return ""

            now_mono = time.monotonic()
            now_wall = time.time()

            clips_dir = self.config.media_dir / "clips"
            clips_dir.mkdir(parents=True, exist_ok=True)
            ts = int(now_wall)
            filename = f"incident_{camera_id}_trk{track_id}_{ts}.mp4"
            out_path = clips_dir / filename
            clip_url = f"/media/clips/{filename}"

            # 1. Snapshot the pre-event buffer (up to 4.0s of recent frames)
            pre_frames = [(t, f.copy()) for t, f in self._pre_event_buffer]
            if pre_frames:
                actual_pre_duration = now_mono - pre_frames[0][0]
            else:
                actual_pre_duration = 0.0

            # 2. Dynamic window compensation: if pre-buffer is short, extend post capture
            total_target = self.config.clip_duration_seconds  # 8.0
            post_duration = max(
                self.config.post_alert_buffer_seconds,
                total_target - actual_pre_duration,
            )

            self._clip_lock = True
            self._clip_recorder = {
                "camera_id": camera_id,
                "track_id": track_id,
                "filename": filename,
                "out_path": out_path,
                "clip_url": clip_url,
                "pre_frames": pre_frames,
                "post_frames": [],
                "trigger_mono": now_mono,
                "stop_mono": now_mono + post_duration,
                "total_target": total_target,
                "actual_pre_duration": actual_pre_duration,
                "alert_data": alert_data or {},
                "severity": severity,
                "message": message,
            }
            logger.info(
                f"[INCIDENT CAPTURE STARTED] Pre-buffer: {len(pre_frames)} frames ({actual_pre_duration:.1f}s). "
                f"Post capture: {post_duration:.1f}s. Total target: {total_target:.1f}s. "
                f"Track #{track_id} → {filename}"
            )
            return clip_url
        except Exception as e:
            logger.warning(f"Failed to start incident clip capture: {e}")
            self._clip_lock = False
            self._clip_recorder = None
            return ""

    def _feed_clip_recorder(self, frame: np.ndarray):
        """Append the current annotated frame to the active clip recorder if one is running."""
        if not self._clip_recorder:
            return

        now_mono = time.monotonic()
        self._clip_recorder["post_frames"].append((now_mono, frame.copy()))

        # Check if post-capture window has elapsed
        if now_mono >= self._clip_recorder["stop_mono"]:
            self._finalize_clip()

    def _finalize_clip(self):
        """Finalize the current clip recorder: merge pre + post frames and encode to MP4."""
        rec = self._clip_recorder
        if rec is None:
            return

        # Merge pre + post frames
        all_frames_ts = rec["pre_frames"] + rec["post_frames"]
        all_frames = [f for _, f in all_frames_ts]

        out_path = rec["out_path"]
        total_target = rec["total_target"]
        clip_target_fps = self.config.clip_target_fps
        alert_data = rec.get("alert_data")
        severity = rec.get("severity", "critical")
        message = rec.get("message", "")
        telegram_enabled = self.config.telegram_enabled

        self._clip_recorder = None
        self._clip_lock = False

        logger.info(
            f"[INCIDENT CAPTURE COMPLETE] Collected {len(all_frames)} raw frames. "
            f"Encoding {total_target:.1f}s MP4 at {clip_target_fps} FPS → {rec['filename']}"
        )

        # Offload encoding to background CPU thread
        self._io_executor.submit(
            self._encode_strict_8s_clip,
            out_path,
            all_frames,
            total_target,
            clip_target_fps,
            alert_data,
            severity,
            message,
            telegram_enabled,
        )

    @staticmethod
    def _encode_strict_8s_clip(
        out_path: Path,
        raw_frames: list,
        target_duration: float,
        target_fps: float,
        alert_data: Optional[dict] = None,
        severity: str = "critical",
        message: str = "",
        telegram_enabled: bool = False,
    ):
        """
        Encode raw_frames into standard HTML5 browser-playable video files (both H.264 MP4 and VP8 WebM)
        with strictly target_duration seconds of playback.

        Resamples raw_frames to exactly (target_fps * target_duration) output frames
        by nearest-neighbor index mapping across the input timeline.
        Outputs:
          1. .mp4: Standard H.264 (yuv420p) via PyAV (plays natively in Chrome, Edge, Safari, Firefox)
          2. .webm: Standard VP8 via PyAV / OpenCV (preferred HTML5 web format)
        Result: exactly 8.0s playback in any browser player.

        Automatically dispatches 8s video evidence to Telegram when encoding completes.
        """
        try:
            if not raw_frames:
                logger.warning("No frames to encode for incident clip")
                return

            out_path.parent.mkdir(parents=True, exist_ok=True)

            h, w = raw_frames[0].shape[:2]
            # Fast mobile resolution for rapid encoding and transfer (max 960px width, even dimensions)
            if w > 960:
                target_w = 960
                target_h = int(h * (960 / w))
            else:
                target_w = w
                target_h = h
            target_w = target_w - (target_w % 2)
            target_h = target_h - (target_h % 2)

            total_output_frames = int(target_fps * target_duration)  # e.g. 20 * 8 = 160
            n_input = len(raw_frames)

            # Resample: map each output frame index to the nearest input frame index
            indices = [int(i * n_input / total_output_frames) for i in range(total_output_frames)]
            indices = [min(idx, n_input - 1) for idx in indices]

            # Prepare resampled frames, guaranteeing consistent dimensions
            resampled_frames = []
            for idx in indices:
                f = raw_frames[idx]
                if f.shape[:2] != (target_h, target_w):
                    f = cv2.resize(f, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
                resampled_frames.append(f)

            mp4_path = out_path.with_suffix(".mp4")
            tmp_mp4_path = mp4_path.with_name(f"{mp4_path.stem}.tmp.mp4")

            # ── 1. Fast Encode Browser-Native H.264 MP4 (Universal HTML5/Telegram playback) ──
            mp4_success = False
            try:
                import av
                container_mp4 = av.open(str(tmp_mp4_path), mode="w", options={"movflags": "+faststart"})
                stream_mp4 = container_mp4.add_stream("libx264", rate=int(target_fps))
                stream_mp4.width = target_w
                stream_mp4.height = target_h
                stream_mp4.pix_fmt = "yuv420p"
                stream_mp4.options = {
                    "crf": "28",
                    "preset": "ultrafast",
                    "tune": "zerolatency",
                    "threads": "2",
                }
                for f in resampled_frames:
                    av_frame = av.VideoFrame.from_ndarray(f, format="bgr24")
                    for packet in stream_mp4.encode(av_frame):
                        container_mp4.mux(packet)
                for packet in stream_mp4.encode():
                    container_mp4.mux(packet)
                container_mp4.close()
                os.replace(tmp_mp4_path, mp4_path)
                mp4_success = True
            except Exception as e_av:
                logger.warning(f"PyAV H.264 encode unavailable ({e_av}), falling back to OpenCV mp4v")
                try:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(str(tmp_mp4_path), fourcc, target_fps, (target_w, target_h))
                    for f in resampled_frames:
                        writer.write(f)
                    writer.release()
                    os.replace(tmp_mp4_path, mp4_path)
                    mp4_success = True
                except Exception as e_cv:
                    logger.warning(f"OpenCV MP4 fallback failed: {e_cv}")
                    if tmp_mp4_path.exists():
                        try:
                            tmp_mp4_path.unlink()
                        except Exception:
                            pass

            actual_duration = total_output_frames / target_fps
            logger.info(
                f"[EVIDENCE SAVED] {mp4_path.name} (H.264: {mp4_success}): "
                f"{total_output_frames} frames @ {target_fps} FPS = {actual_duration:.1f}s playback ({mp4_path.stat().st_size / 1024:.0f} KB)"
            )

            # ── 2. TELEGRAM: Single sendVideo with incident caption (NO separate location/text) ──
            if telegram_enabled and mp4_success and mp4_path.exists() and mp4_path.stat().st_size > 10000 and alert_data:
                try:
                    from core.alert_engine.telegram_notifier import get_telegram_notifier
                    notifier = get_telegram_notifier()
                    if notifier.enabled:
                        alert_id = f"breach_{alert_data.get('camera_id', 'cam')}_{alert_data.get('track_id', 0)}_{int(time.time())}"
                        logger.info(f"[Telegram] Sending finalized 8s clip as single message: {mp4_path.name}")
                        notifier.send_alert_with_video_sync(
                            alert_id=alert_id,
                            alert_data=alert_data,
                            severity=severity,
                            message=message,
                            clip_path=str(mp4_path),
                        )
                except Exception as e_tg:
                    logger.warning(f"[Telegram] Video evidence upload error: {e_tg}")

        except Exception as e:
            logger.warning(f"Failed to encode incident clip: {e}")

    def _save_incident_clip(
        self,
        camera_id: str,
        track_id: int,
        alert_data: Optional[dict] = None,
        severity: str = "critical",
        message: str = "",
    ) -> str:
        """Convenience alias used by the alert handler."""
        return self._start_clip_capture(camera_id, track_id, alert_data, severity, message)

    def _save_thumbnail(self, frame, track_id: int, frame_id: int) -> str:
        """Save a detection thumbnail to disk asynchronously via ThreadPoolExecutor."""
        thumb_dir = self.config.media_dir / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        filename = f"thumb_{frame_id}_{track_id}.jpg"
        path = thumb_dir / filename
        frame_copy = frame.copy()

        def _write():
            try:
                cv2.imwrite(str(path), frame_copy, [cv2.IMWRITE_JPEG_QUALITY, 80])
            except Exception as e:
                logger.debug(f"Thumbnail write error: {e}")

        self._io_executor.submit(_write)
        return str(path)

    def _write_live_frame_async(self, jpeg_buf, camera_id: str):
        """Asynchronously write live stream frame to disk on CPU executor."""
        try:
            live_path = self.config.media_dir / f"live_{camera_id}.jpg"
            tmp_path = self.config.media_dir / f"live_{camera_id}.tmp.jpg"
            with open(tmp_path, "wb") as f:
                f.write(jpeg_buf)
            os.replace(tmp_path, live_path)
        except Exception:
            pass
        finally:
            self._live_frame_writing = False

    def _sync_alerts_async(self):
        """Asynchronously trigger uplink sync batch to Core API on CPU executor."""
        if getattr(self, "_sync_in_progress", False):
            return
        self._sync_in_progress = True
        try:
            self.sync_agent.sync_batch_sync(self.local_store)
        except Exception as e:
            logger.debug(f"Async alert sync error: {e}")
        finally:
            self._sync_in_progress = False

    def _draw_overlays(self, frame, tracks, fence_zones, breaches):
        """Draw modern high-precision surveillance overlays with breach alerts.
        Performance-optimized: draws directly on frame to avoid full-frame copies.
        """
        overlay = frame  # Draw directly on frame — no copy (caller handles copy if needed)
        h, w = overlay.shape[:2]

        # Identify active exclusion zones (floor restricted polygons)
        exclusion_zones = [z for z in fence_zones if z.rule_type.value == "exclusion" and z.is_active and len(z.polygon_points_pixel) >= 3]

        # Real-time check: evaluate EVERY track's ground-contact point (bottom-center of bbox)
        # against the calibrated perspective restricted floor polygon
        breached_track_ids = set()
        for track in tracks:
            bx1, by1, bx2, by2 = [int(c) for c in track.bbox] if track.bbox and len(track.bbox) == 4 else (0, 0, 0, 0)
            bottom_center = ((bx1 + bx2) / 2.0, float(by2))

            is_intruder = False
            for ez in exclusion_zones:
                if ez.zone_id not in self._zone_contours:
                    self._zone_contours[ez.zone_id] = np.array([(int(p[0]), int(p[1])) for p in ez.polygon_points_pixel], dtype=np.int32)
                contour = self._zone_contours[ez.zone_id]
                # Point-in-polygon test: >= 0 means on edge or inside the restricted floor polygon
                if cv2.pointPolygonTest(contour, bottom_center, False) >= 0:
                    is_intruder = True
                    break

            if is_intruder:
                breached_track_ids.add(track.track_id)

        # Update persistent set and determine active breach state
        self._breached_track_ids = set(breached_track_ids)
        has_active_breach = len(breached_track_ids) > 0

        # ──────────────────────────────────────────────────────────
        # 1. Draw Virtual Fence Zones (Perspective Ground-Attached)
        # ──────────────────────────────────────────────────────────
        for zone in fence_zones:
            if zone.zone_id not in self._zone_contours:
                self._zone_contours[zone.zone_id] = np.array([(int(p[0]), int(p[1])) for p in zone.polygon_points_pixel], dtype=np.int32)
            pts = self._zone_contours[zone.zone_id]
            if len(pts) < 3:
                continue  # Need at least 3 points for a polygon

            zone_breached = any(b.zone_id == zone.zone_id for b in breaches) or (has_active_breach and (zone.zone_id == "zone_restricted_area" or zone.rule_type.value == "exclusion"))

            if zone.rule_type.value == "exclusion":
                # ── PERSPECTIVE GROUND-ATTACHED RESTRICTED ZONE ──
                # Subtle transparent red shadow on the floor polygon with fast ROI blending (<0.7ms)
                bx, by, bw, bh = cv2.boundingRect(pts)
                bx2r, by2r = min(bx + bw, w), min(by + bh, h)
                bx, by = max(bx, 0), max(by, 0)
                if bw > 0 and bh > 0:
                    roi = overlay[by:by2r, bx:bx2r]
                    tint = roi.copy()
                    pts_shifted = pts - np.array([bx, by])
                    tint_color = (0, 0, 240) if zone_breached else (0, 0, 160)
                    cv2.fillPoly(tint, [pts_shifted], tint_color)
                    alpha = 0.18 if zone_breached else 0.10
                    cv2.addWeighted(tint, alpha, roi, 1.0 - alpha, 0, dst=roi)

                border_color = (0, 0, 255) if zone_breached else (0, 0, 180)
                border_th = 2 if zone_breached else 1

                # Draw thin perspective boundary polyline (the "floor perimeter")
                cv2.polylines(overlay, [pts], True, border_color, border_th, cv2.LINE_AA)

                # Small corner markers at each polygon vertex (subtle ground anchors)
                for pt in pts:
                    cv2.circle(overlay, tuple(pt), 3, border_color, -1, cv2.LINE_AA)

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
        now_mono = time.monotonic()
        cd_rem = max([0.0] + [until - now_mono for until in self._zone_cooldown_until.values()])

        if has_active_breach:
            pulse = int(time.time() * 5) % 2 == 0
            banner_bg = (0, 0, 230) if pulse else (0, 0, 160)
            cv2.rectangle(overlay, (0, 0), (w, 42), banner_bg, -1)
            cv2.line(overlay, (0, 42), (w, 42), (255, 255, 255), 2)
            if cd_rem > 0:
                breach_msg = f"[ALERT SIGNAL] RESTRICTED BORDER BREACHED! INTRUSION DETECTED | COOLDOWN: {cd_rem:.1f}s"
            else:
                breach_msg = "[ALERT SIGNAL] RESTRICTED BORDER PERIMETER BREACHED! INTRUSION DETECTED"
            (tw, th), _ = cv2.getTextSize(breach_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            tx = max(10, (w - tw) // 2)
            cv2.putText(overlay, breach_msg, (tx, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
            pass

        # ──────────────────────────────────────────────────────────
        # 4. Systems Status Overlay (Sleek Compact Top-Left Pill)
        # ──────────────────────────────────────────────────────────
        fps_val = self._stats['avg_fps']
        active_cnt = self._stats['tracks_active']
        stats_text = f"CAM-01 | {fps_val:.1f} FPS | {active_cnt} TARGET{'S' if active_cnt != 1 else ''}"
        (tw, th), _ = cv2.getTextSize(stats_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        pill_right = 24 + tw
        cv2.rectangle(overlay, (12, 12), (pill_right, 20 + th + 6), (15, 20, 25), -1)
        cv2.rectangle(overlay, (12, 12), (pill_right, 20 + th + 6), (0, 255, 200), 1)
        cv2.putText(overlay, stats_text, (18, 18 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 200), 1, cv2.LINE_AA)

        # Cooldown Pill (if cooldown active but not currently breached)
        if not has_active_breach and cd_rem > 0:
            cd_text = f"COOLDOWN: {cd_rem:.1f}s"
            (cw, ch), _ = cv2.getTextSize(cd_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(overlay, (pill_right + 8, 12), (pill_right + 20 + cw, 20 + ch + 6), (25, 20, 10), -1)
            cv2.rectangle(overlay, (pill_right + 8, 12), (pill_right + 20 + cw, 20 + ch + 6), (0, 180, 255), 1)
            cv2.putText(overlay, cd_text, (pill_right + 14, 18 + ch), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 180, 255), 1, cv2.LINE_AA)

        # Recording Indicator (top-right REC badge when active capture in progress)
        if getattr(self, "_clip_lock", False):
            rec_pulse = int(time.time() * 2) % 2 == 0
            if rec_pulse:
                cv2.circle(overlay, (w - 70, 22), 6, (0, 0, 255), -1)
            cv2.putText(overlay, "REC [8s]", (w - 58, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 0, 255), 1, cv2.LINE_AA)

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

        # Always initialize/refresh the calibrated perspective restricted zone from config
        self.fence_engine.create_perspective_restricted_zone(
            polygon_points=self.config.restricted_zone_polygon,
            camera_id=self.camera.camera_id,
            frame_width=self.config.frame_width,
            frame_height=self.config.frame_height,
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
                    self.sync_agent.sync_batch_sync(self.local_store)
                except Exception:
                    pass
        import threading
        t_sync = threading.Thread(target=_bg_sync, daemon=True)
        t_sync.start()

        # Determine active execution device string
        active_device = self.config.get_device_description()

        logger.info("=" * 65)
        logger.info("IBVAP Edge Pipeline — Running (Hybrid CPU + GPU Architecture)")
        logger.info(f"  Active Execution Device: {active_device}")
        logger.info(f"  Inference Engine: YOLO26n ({self.config.yolo_model})")
        logger.info(f"  GPU Vision Workloads: YOLO26 Detection ({'FP16' if self.config.is_half_precision() else 'FP32'}), Gated Face/ANPR ROIs")
        logger.info(f"  CPU Workloads: Video Grabber, ByteTrack, Virtual Fence, Random Forest Activity (n_jobs=1), Async I/O")
        logger.info(f"  Camera Source: {self.config.get_camera_source()}")
        logger.info(f"  Target FPS: {self.config.camera_fps} | Resolution: {self.config.frame_width}x{self.config.frame_height}")
        logger.info(f"  Show display: {show_display}")
        logger.info("=" * 65)

        try:
            for packet in self.camera.frames():
                if not self._running:
                    break

                if max_frames > 0 and self._frame_count >= max_frames:
                    break

                frame_start = time.time()
                frame = packet.frame
                self._frame_count += 1

                # --- Night Enhancement (CPU CLAHE/Gamma only when luminance drops) ---
                enhanced = False
                night_enhancer = self._get_night_enhancer()
                if night_enhancer:
                    frame, enhanced = night_enhancer.enhance_if_needed(frame)

                # --- Detection + Tracking (GPU YOLO26 FP16 + CPU ByteTrack) ---
                tracks = self.tracker.update(
                    frame,
                    frame_id=packet.frame_id,
                    camera_id=packet.camera_id,
                    timestamp=packet.timestamp,
                )

                # --- Virtual Fence Evaluation (CPU Geometry) ---
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

                # --- Face Detection (Gated execution on cropped person ROIs) ---
                face_detector = self._get_face_detector()
                face_results = []
                if face_detector:
                    person_tracks = [t for t in tracks if t.class_name == "person" and t.is_active]
                    for track in person_tracks[:3]:  # Limit to 3 persons per frame
                        is_breached_target = track.track_id in self._breached_track_ids
                        is_new_breach = is_breached_target and (track.track_id not in self._breach_face_scanned)
                        # Gate execution: run on first breach, new track (frame 1), or sampled every 30 frames
                        should_run_face = is_new_breach or (track.frame_count == 1) or (track.frame_count % 30 == 0)
                        if is_breached_target:
                            self._breach_face_scanned.add(track.track_id)
                        if should_run_face:
                            x1, y1, x2, y2 = [int(c) for c in track.bbox]
                            h, w = frame.shape[:2]
                            crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                            if crop.size > 0:
                                faces = face_detector.detect(crop, track.track_id)
                                face_results.extend(faces)

                # --- ANPR (Gated execution on cropped vehicle ROIs) ---
                anpr_engine = self._get_anpr_engine()
                plate_results = []
                if anpr_engine:
                    vehicle_tracks = [
                        t for t in tracks
                        if t.class_name in ("car", "truck", "bus", "motorcycle") and t.is_active
                    ]
                    for track in vehicle_tracks[:3]:
                        is_breached_target = track.track_id in self._breached_track_ids
                        is_new_breach_anpr = is_breached_target and (track.track_id not in self._breach_anpr_scanned)
                        # Gate execution: run on first breach, new track (frame 1), or sampled every 30 frames
                        should_run_anpr = is_new_breach_anpr or (track.frame_count == 1) or (track.frame_count % 30 == 0)
                        if is_breached_target:
                            self._breach_anpr_scanned.add(track.track_id)
                        if should_run_anpr:
                            x1, y1, x2, y2 = [int(c) for c in track.bbox]
                            h, w = frame.shape[:2]
                            crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
                            if crop.size > 0:
                                plate = anpr_engine.read_plate(crop, track.track_id)
                                if plate:
                                    plate_results.append(plate)

                # --- Activity Detection (CPU Random Forest ML + Rules, n_jobs=1) ---
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

                # ── Pre-Event Ring Buffer (continuous, every frame, pruned to 4.0s) ──
                self._pre_event_buffer.append((time.monotonic(), overlay.copy()))
                self._prune_pre_event_buffer()

                # ── Feed Active Clip Recorder (if capture in progress) ──
                if self._clip_lock:
                    self._feed_clip_recorder(overlay)

                # Save live frame for real-time frontend streaming (non-blocking CPU worker thread)
                if not self._live_frame_writing:
                    try:
                        ret, jpeg_buf = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 65])
                        if ret:
                            self._live_frame_writing = True
                            self._io_executor.submit(self._write_live_frame_async, jpeg_buf, packet.camera_id)
                    except Exception:
                        pass

                # ══════════════════════════════════════════════════════════
                # ALERT STATE MACHINE (10s Zone Cooldown + Occupancy Re-Trigger)
                # ══════════════════════════════════════════════════════════
                now_mono = time.monotonic()

                if all_breaches:
                    self._active_breach_until = time.time() + 5.0
                    for b in all_breaches:
                        self._breached_track_ids.add(b.track_id)

                    # Group breaches by zone so each zone is evaluated independently
                    breaches_by_zone: dict[str, list] = {}
                    for b in all_breaches:
                        breaches_by_zone.setdefault(b.zone_id, []).append(b)

                    new_alerts_created = False
                    for zone_id, zone_breaches in breaches_by_zone.items():
                        cooldown_until = self._zone_cooldown_until.get(zone_id, 0.0)
                        if now_mono < cooldown_until:
                            # Cooldown active — suppress alert for this zone
                            continue

                        # Cooldown expired (or first alert) — TRIGGER!
                        # Pick the highest-confidence breach in this zone as the representative
                        breach = max(zone_breaches, key=lambda b: b.confidence)

                        # Start 10-second cooldown
                        self._zone_cooldown_until[zone_id] = now_mono + self.config.alert_cooldown_seconds

                        # 1. Save instant high-resolution snapshot thumbnail
                        thumb_path = self._save_thumbnail(overlay, breach.track_id, packet.frame_id)
                        alert_msg = f"{breach.breach_type} by {breach.object_class} in {breach.zone_name} (Track #{breach.track_id})"

                        breach_data = {
                            "zone_id": breach.zone_id,
                            "zone_name": breach.zone_name,
                            "breach_type": breach.breach_type,
                            "track_id": breach.track_id,
                            "object_class": breach.object_class,
                            "ground_point": breach.ground_point_pixel,
                            "dwell_time": breach.dwell_time,
                            "thumbnail_path": thumb_path,
                            "camera_id": packet.camera_id,
                            "latitude": self.config.default_camera_lat,
                            "longitude": self.config.default_camera_lng,
                            "telegram_dispatched": True,
                        }

                        # 2. Start strict 8-second clip capture (with alert metadata so encoder can auto-dispatch video)
                        clip_url = self._save_incident_clip(
                            packet.camera_id,
                            breach.track_id,
                            alert_data=breach_data,
                            severity=breach.severity,
                            message=alert_msg,
                        )
                        breach_data["clip_url"] = clip_url

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
                            message=alert_msg,
                            data=breach_data,
                        )
                        self._stats["fence_breaches"] += 1
                        self._stats["alerts_generated"] += 1
                        new_alerts_created = True
                        logger.info(
                            f"[ALERT #{self._stats['alerts_generated']}] Zone '{breach.zone_name}' — "
                            f"Track #{breach.track_id} ({breach.object_class}). "
                            f"Next alert eligible at +{self.config.alert_cooldown_seconds:.0f}s"
                        )

                    if new_alerts_created:
                        # Offload to CPU ThreadPoolExecutor so GPU detection loop never pauses on network I/O
                        self._io_executor.submit(self._sync_alerts_async)
                        # Telegram alert is dispatched ONLY after 8s clip encoding completes
                        # (inside _encode_strict_8s_clip) — no instant text/photo dispatch here
                elif time.time() > self._active_breach_until:
                    self._breached_track_ids.clear()
                    self._breach_face_scanned.clear()
                    self._breach_anpr_scanned.clear()

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

        # Finalize and encode any in-flight clip capture before releasing resources
        if getattr(self, "_clip_recorder", None):
            try:
                self._finalize_clip()
            except Exception as e:
                logger.warning(f"Error finalizing in-flight clip during shutdown: {e}")

        self.camera.release()
        if hasattr(self, "_io_executor"):
            try:
                self._io_executor.shutdown(wait=True, cancel_futures=False)
            except Exception:
                pass
        if getattr(self, "_core_reachable", False):
            try:
                # Sync remaining events to Core API if core was online
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
