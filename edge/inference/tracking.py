"""
IBVAP — ByteTrack Multi-Object Tracking Module
================================================
Persistent multi-object tracking using ByteTrack via Ultralytics.
Maintains track IDs, histories, and ground-point trajectories.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TrackState:
    """State of a single tracked object."""
    track_id: int
    class_name: str
    class_id: int
    bbox: list  # [x1, y1, x2, y2]
    confidence: float
    ground_point: tuple  # (x, y)
    first_seen: float  # timestamp
    last_seen: float  # timestamp
    frame_count: int = 0
    ground_point_history: list = field(default_factory=list)
    speed: float = 0.0  # pixels per second
    is_active: bool = True

    @property
    def dwell_time(self) -> float:
        """Time in seconds since first seen."""
        return self.last_seen - self.first_seen

    @property
    def center(self) -> tuple:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def aspect_ratio(self) -> float:
        x1, y1, x2, y2 = self.bbox
        w = x2 - x1
        h = y2 - y1
        return w / h if h > 0 else 0


class Tracker:
    """
    Multi-object tracker using ByteTrack via Ultralytics.
    Maintains persistent track IDs and movement histories.
    """

    def __init__(
        self,
        model_name: str = "yolo11n.pt",
        tracker_config: str = "bytetrack.yaml",
        confidence_threshold: float = 0.4,
        target_classes: list[int] = None,
        max_history_length: int = 100,
    ):
        self.model_name = model_name
        self.tracker_config = tracker_config
        self.confidence_threshold = confidence_threshold
        self.target_classes = target_classes or [0, 1, 2, 3, 5, 7]
        self.max_history_length = max_history_length

        self._model = None
        self._initialized = False
        self._tracks: dict[int, TrackState] = {}
        self._lost_tracks: dict[int, TrackState] = {}

        # COCO class mapping
        self._class_names = {
            0: "person", 1: "bicycle", 2: "car",
            3: "motorcycle", 5: "bus", 7: "truck",
        }

    def initialize(self):
        """Load the YOLO model for tracking, or fall back to simulation."""
        if self._initialized:
            return

        try:
            from ultralytics import YOLO

            logger.info(f"Loading tracking model: {self.model_name}...")
            self._model = YOLO(self.model_name)
            self._initialized = True
            self._simulation_mode = False
            logger.info("Tracker initialized successfully (YOLO mode)")

        except ImportError:
            logger.warning(
                "ultralytics not installed — running in SIMULATION mode. "
                "Install with: pip install ultralytics"
            )
            self._initialized = True
            self._simulation_mode = True
            self._sim_frame_count = 0
            self._sim_objects = [
                {"id": 1, "cls": "person", "cls_id": 0, "x": 300.0, "y": 480.0, "vx": 1.5, "vy": -2.2, "w": 44, "h": 90},
                {"id": 2, "cls": "person", "cls_id": 0, "x": 750.0, "y": 520.0, "vx": -1.2, "vy": -0.8, "w": 40, "h": 85},
                {"id": 3, "cls": "car", "cls_id": 2, "x": 100.0, "y": 580.0, "vx": 4.5, "vy": 0.0, "w": 130, "h": 65},
                {"id": 4, "cls": "person", "cls_id": 0, "x": 1050.0, "y": 420.0, "vx": -1.0, "vy": -1.5, "w": 42, "h": 88},
            ]
            logger.info("Tracker initialized (SIMULATION mode — 4 synthetic objects)")

        except Exception as e:
            logger.error(f"Failed to initialize tracker: {e}")
            raise

    def update(
        self,
        frame: np.ndarray,
        frame_id: int = 0,
        camera_id: str = "cam_01",
        timestamp: float = None,
    ) -> list[TrackState]:
        """
        Run detection + tracking on a frame.
        Returns list of active TrackState objects.
        """
        if not self._initialized:
            self.initialize()

        if timestamp is None:
            timestamp = time.time()

        # Simulation mode — generate synthetic detections
        if getattr(self, '_simulation_mode', False):
            return self._simulate_update(frame, frame_id, camera_id, timestamp)

        try:
            # Run YOLO tracking with ByteTrack
            results = self._model.track(
                frame,
                conf=self.confidence_threshold,
                classes=self.target_classes,
                tracker=self.tracker_config,
                persist=True,
                verbose=False,
                imgsz=640,
            )

            current_track_ids = set()
            active_tracks = []

            for result in results:
                if result.boxes is None or result.boxes.id is None:
                    continue

                boxes = result.boxes
                for i in range(len(boxes)):
                    track_id = int(boxes.id[i].cpu().numpy())
                    bbox = boxes.xyxy[i].cpu().numpy().tolist()
                    class_id = int(boxes.cls[i].cpu().numpy())
                    confidence = float(boxes.conf[i].cpu().numpy())
                    class_name = self._class_names.get(class_id, f"class_{class_id}")

                    # Ground point (bottom-center)
                    x1, y1, x2, y2 = bbox
                    ground_point = ((x1 + x2) / 2, y2)

                    current_track_ids.add(track_id)

                    if track_id in self._tracks:
                        # Update existing track
                        track = self._tracks[track_id]
                        old_gp = track.ground_point

                        track.bbox = bbox
                        track.confidence = confidence
                        track.ground_point = ground_point
                        track.last_seen = timestamp
                        track.frame_count += 1
                        track.is_active = True

                        # Update ground point history
                        track.ground_point_history.append(ground_point)
                        if len(track.ground_point_history) > self.max_history_length:
                            track.ground_point_history.pop(0)

                        # Calculate speed in m/s (using 35.0 px/m scale factor)
                        dt = timestamp - (track.last_seen - 0.001)
                        if dt > 0:
                            dx_m = (ground_point[0] - old_gp[0]) / 35.0
                            dy_m = (ground_point[1] - old_gp[1]) / 35.0
                            calc_speed = (dx_m**2 + dy_m**2) ** 0.5 / dt
                            track.speed = 0.7 * track.speed + 0.3 * calc_speed if track.speed > 0 else calc_speed

                    else:
                        # New track or re-identified from lost
                        if track_id in self._lost_tracks:
                            track = self._lost_tracks.pop(track_id)
                            track.bbox = bbox
                            track.confidence = confidence
                            track.ground_point = ground_point
                            track.last_seen = timestamp
                            track.is_active = True
                        else:
                            track = TrackState(
                                track_id=track_id,
                                class_name=class_name,
                                class_id=class_id,
                                bbox=bbox,
                                confidence=confidence,
                                ground_point=ground_point,
                                first_seen=timestamp,
                                last_seen=timestamp,
                                frame_count=1,
                                ground_point_history=[ground_point],
                            )

                        self._tracks[track_id] = track

                    active_tracks.append(track)

            # Move tracks that weren't seen this frame to lost
            for tid in list(self._tracks.keys()):
                if tid not in current_track_ids:
                    track = self._tracks.pop(tid)
                    track.is_active = False
                    self._lost_tracks[tid] = track

            # Clean up very old lost tracks
            cutoff = timestamp - 30.0  # 30 seconds
            self._lost_tracks = {
                tid: t for tid, t in self._lost_tracks.items()
                if t.last_seen > cutoff
            }

            return active_tracks

        except Exception as e:
            logger.error(f"Tracking error on frame {frame_id}: {e}")
            return []

    def _simulate_update(
        self,
        frame: np.ndarray,
        frame_id: int,
        camera_id: str,
        timestamp: float,
    ) -> list[TrackState]:
        """Generate synthetic detections for demo mode without ML models."""
        import random

        self._sim_frame_count += 1
        h, w = frame.shape[:2]
        active_tracks = []

        for obj in self._sim_objects:
            obj["x"] += obj["vx"]
            obj["y"] += obj["vy"]

            # Bounce inside frame boundaries matching create_sample_video physics
            if obj["x"] < 50 or obj["x"] > w - obj["w"] - 50:
                obj["vx"] *= -1
                obj["x"] = max(50.0, min(w - obj["w"] - 50.0, obj["x"]))
            if obj["y"] < 200 or obj["y"] > h - obj["h"] - 30:
                obj["vy"] *= -1
                obj["y"] = max(200.0, min(h - obj["h"] - 30.0, obj["y"]))

            x1 = obj["x"]
            y1 = obj["y"]
            x2 = x1 + obj["w"]
            y2 = y1 + obj["h"]
            bbox = [x1, y1, x2, y2]
            ground_point = ((x1 + x2) / 2, y2)
            confidence = 0.88 + random.uniform(0, 0.05)

            track_id = obj["id"]
            if track_id in self._tracks:
                track = self._tracks[track_id]
                old_gp = track.ground_point
                track.bbox = bbox
                track.confidence = confidence
                track.ground_point = ground_point
                track.last_seen = timestamp
                track.frame_count += 1
                track.is_active = True
                track.ground_point_history.append(ground_point)
                if len(track.ground_point_history) > self.max_history_length:
                    track.ground_point_history.pop(0)

                # Realistic speed estimation (scaled to m/s: 1m ~= 35.0 pixels)
                dt = 1.0 / 15.0
                dx_m = (ground_point[0] - old_gp[0]) / 35.0
                dy_m = (ground_point[1] - old_gp[1]) / 35.0
                calc_speed = (dx_m**2 + dy_m**2) ** 0.5 / dt
                track.speed = 0.7 * track.speed + 0.3 * calc_speed if track.speed > 0 else calc_speed
            else:
                track = TrackState(
                    track_id=track_id,
                    class_name=obj["cls"],
                    class_id=obj["cls_id"],
                    bbox=bbox,
                    confidence=confidence,
                    ground_point=ground_point,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    frame_count=1,
                    ground_point_history=[ground_point],
                )
                self._tracks[track_id] = track

            active_tracks.append(track)

        return active_tracks

    def get_track(self, track_id: int) -> Optional[TrackState]:
        """Get a specific track by ID."""
        return self._tracks.get(track_id) or self._lost_tracks.get(track_id)

    def get_all_active_tracks(self) -> list[TrackState]:
        """Get all currently active tracks."""
        return [t for t in self._tracks.values() if t.is_active]

    def get_track_count(self) -> dict:
        """Get count of tracks by class."""
        counts = defaultdict(int)
        for track in self._tracks.values():
            counts[track.class_name] += 1
        return dict(counts)

    def reset(self):
        """Clear all tracks."""
        self._tracks.clear()
        self._lost_tracks.clear()
        if self._model is not None:
            self._model.predictor = None
        logger.info("Tracker state reset")

    @property
    def total_active(self) -> int:
        return len(self._tracks)

    @property
    def total_lost(self) -> int:
        return len(self._lost_tracks)

