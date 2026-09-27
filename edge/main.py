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

    def _save_thumbnail(self, frame, track_id: int, frame_id: int) -> str:
        """Save a detection thumbnail to disk."""
        thumb_dir = self.config.media_dir / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        filename = f"thumb_{frame_id}_{track_id}.jpg"
        path = thumb_dir / filename
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return str(path)

    def _draw_overlays(self, frame, tracks, fence_zones, breaches):
        """Draw modern high-precision surveillance overlays with breach alerts."""
        overlay = frame.copy()
        h, w = overlay.shape[:2]

        breached_track_ids = {b.track_id: b for b in breaches}
        has_active_breach = len(breaches) > 0

        # ──────────────────────────────────────────────────────────
        # 1. Draw Virtual Fence Zones & Border Lines
        # ──────────────────────────────────────────────────────────
        for zone in fence_zones:
            pts = np.array([(int(p[0]), int(p[1])) for p in zone.polygon_points_pixel], np.int32)
            if len(pts) < 2:
                continue

            zone_breached = any(b.zone_id == zone.zone_id for b in breaches)
            
            if zone.rule_type.value == "line_cross":
                # Border Line: Draw double high-contrast border line
                color = (0, 0, 255) if zone_breached else (0, 255, 255)
                # Outer line
                cv2.polylines(overlay, [pts], True, color, 3 if zone_breached else 2)
                # Inner line highlight
                cv2.polylines(overlay, [pts], True, (255, 255, 255), 1)

                # Line Label Tag
                lx, ly = pts[0][0] + 10, pts[0][1] - 8
                lbl = f"=== {zone.name.upper()} (BORDER FENCE) ==="
                (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(overlay, (lx - 4, ly - th - 4), (lx + tw + 4, ly + 4), color, -1)
                cv2.putText(overlay, lbl, (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

            elif zone.rule_type.value == "exclusion":
                # Restricted Exclusion Zone
                color = (0, 0, 255)
                # Semi-transparent red fill
                sub = overlay.copy()
                cv2.fillPoly(sub, [pts], (0, 0, 180))
                cv2.addWeighted(sub, 0.25, overlay, 0.75, 0, overlay)
                cv2.polylines(overlay, [pts], True, color, 3 if zone_breached else 2)

                # Label
                lx, ly = pts[0][0] + 8, pts[0][1] + 20
                lbl = f"[RESTRICTED] {zone.name.upper()} [NO ENTRY]"
                cv2.putText(overlay, lbl, (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)

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
                label_text = f"#{track.track_id} {track.class_name.upper()} {track.confidence:.2f} ({track.speed:.1f}m/s)"
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
            breach_msg = f"[ALERT] {len(breaches)} BORDER BREACH(ES) DETECTED ON CAM-01!"
            cv2.rectangle(overlay, (0, 0), (w, 40), (0, 0, 220), -1)
            cv2.putText(overlay, breach_msg, (w // 2 - 280, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

        # ──────────────────────────────────────────────────────────
        # 4. Systems Status Overlay (Top Left)
        # ──────────────────────────────────────────────────────────
        stats_bg = overlay.copy()
        cv2.rectangle(stats_bg, (10, 45), (240, 140), (20, 25, 20), -1)
        cv2.addWeighted(stats_bg, 0.6, overlay, 0.4, 0, overlay)
        cv2.rectangle(overlay, (10, 45), (240, 140), (0, 255, 200), 1)

        stats_lines = [
            f"FPS: {self._stats['avg_fps']:.1f}",
            f"Active Tracks: {self._stats['tracks_active']}",
            f"Total Detections: {self._stats['detections_total']}",
            f"Fence Breaches: {self._stats['fence_breaches']}",
        ]
        for i, text in enumerate(stats_lines):
            color = (0, 0, 255) if ("Breaches" in text and self._stats['fence_breaches'] > 0) else (0, 255, 200)
            cv2.putText(overlay, text, (18, 65 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

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

        # Create demo fence zones
        self.fence_engine.create_demo_zones(
            self.config.frame_width, self.config.frame_height, "cam_01"
        )

        # Push zones to core so dashboard can see them
        self._sync_zones_to_core()

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

                # --- Store Events Locally ---
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

                # Store fence breach alerts
                for breach in all_breaches:
                    breach_data = {
                        "zone_id": breach.zone_id,
                        "zone_name": breach.zone_name,
                        "breach_type": breach.breach_type,
                        "track_id": breach.track_id,
                        "object_class": breach.object_class,
                        "ground_point": breach.ground_point_pixel,
                        "dwell_time": breach.dwell_time,
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
                        message=f"{breach.breach_type} by {breach.object_class} in {breach.zone_name}",
                        data=breach_data,
                    )
                    self._stats["fence_breaches"] += 1
                    self._stats["alerts_generated"] += 1

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
                    overlay = self._draw_overlays(
                        frame, tracks, self.fence_engine.get_zones(), all_breaches
                    )
                    cv2.imshow("IBVAP Edge Pipeline", overlay)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        logger.info("Quit key pressed")
                        break

                # Periodic uplink sync to core platform
                if self._frame_count % 30 == 0:
                    try:
                        asyncio.run(self.sync_agent.sync_batch(self.local_store))
                    except Exception:
                        pass

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
    parser.add_argument("--no-display", action="store_true", help="Run without display window")
    parser.add_argument("--fps", type=int, default=15, help="Target FPS")
    parser.add_argument("--confidence", type=float, default=0.4, help="Detection confidence threshold")
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
        show_display=not args.no_display,
        max_frames=args.max_frames,
    )


if __name__ == "__main__":
    main()
