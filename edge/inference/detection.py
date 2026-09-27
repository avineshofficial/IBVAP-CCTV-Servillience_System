"""
IBVAP — YOLO26 Detection Module
=================================
Human + vehicle detection using Ultralytics YOLO26n.
Runs inference on frames and returns structured detection results.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

# COCO class names for our target classes
COCO_CLASSES = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

# Severity mapping for different object types in border context
OBJECT_SEVERITY = {
    "person": "high",
    "bicycle": "medium",
    "car": "medium",
    "motorcycle": "medium",
    "bus": "low",
    "truck": "medium",
}


@dataclass
class Detection:
    """A single detection result."""
    bbox: list  # [x1, y1, x2, y2]
    class_id: int
    class_name: str
    confidence: float
    ground_point: tuple  # (x, y) bottom-center of bbox
    frame_id: int
    camera_id: str
    timestamp: float

    @property
    def center(self) -> tuple:
        """Center point of the bounding box."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def area(self) -> float:
        """Area of the bounding box in pixels."""
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)

    @property
    def aspect_ratio(self) -> float:
        """Width / Height ratio of the bounding box."""
        x1, y1, x2, y2 = self.bbox
        w = x2 - x1
        h = y2 - y1
        return w / h if h > 0 else 0

    def crop_from(self, frame: np.ndarray) -> np.ndarray:
        """Extract the detected region from a frame."""
        x1, y1, x2, y2 = [int(c) for c in self.bbox]
        h, w = frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        return frame[y1:y2, x1:x2]


class Detector:
    """
    YOLO26-based object detector for humans and vehicles.
    Uses Ultralytics library for inference.
    """

    def __init__(
        self,
        model_name: str = "yolo11n.pt",
        confidence_threshold: float = 0.4,
        target_classes: list[int] = None,
        device: str = "auto",
    ):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.target_classes = target_classes or [0, 1, 2, 3, 5, 7]
        self._device = device
        self._model = None
        self._initialized = False

    def initialize(self):
        """Load the YOLO model. Called lazily on first detect() call."""
        if self._initialized:
            return

        try:
            from ultralytics import YOLO

            logger.info(f"Loading YOLO model: {self.model_name}...")
            self._model = YOLO(self.model_name)

            # Warm up with a dummy inference
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self._model.predict(dummy, verbose=False)

            self._initialized = True
            logger.info(f"YOLO model loaded successfully: {self.model_name}")

        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            raise

    def detect(
        self,
        frame: np.ndarray,
        frame_id: int = 0,
        camera_id: str = "cam_01",
        timestamp: float = 0.0,
    ) -> list[Detection]:
        """
        Run detection on a single frame.

        Returns:
            List of Detection objects for humans and vehicles found.
        """
        if not self._initialized:
            self.initialize()

        try:
            results = self._model.predict(
                frame,
                conf=self.confidence_threshold,
                classes=self.target_classes,
                verbose=False,
                imgsz=640,
            )

            detections = []
            for result in results:
                if result.boxes is None:
                    continue

                boxes = result.boxes
                for i in range(len(boxes)):
                    bbox = boxes.xyxy[i].cpu().numpy().tolist()
                    class_id = int(boxes.cls[i].cpu().numpy())
                    confidence = float(boxes.conf[i].cpu().numpy())
                    class_name = COCO_CLASSES.get(class_id, f"class_{class_id}")

                    # Ground point = bottom-center of bounding box
                    # This is the estimated contact point with the ground
                    x1, y1, x2, y2 = bbox
                    ground_point = ((x1 + x2) / 2, y2)

                    detections.append(Detection(
                        bbox=bbox,
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                        ground_point=ground_point,
                        frame_id=frame_id,
                        camera_id=camera_id,
                        timestamp=timestamp,
                    ))

            return detections

        except Exception as e:
            logger.error(f"Detection error on frame {frame_id}: {e}")
            return []

    def detect_batch(
        self,
        frames: list[np.ndarray],
        frame_ids: list[int],
        camera_id: str = "cam_01",
        timestamps: list[float] = None,
    ) -> list[list[Detection]]:
        """Run detection on a batch of frames."""
        if timestamps is None:
            timestamps = [0.0] * len(frames)

        return [
            self.detect(frame, fid, camera_id, ts)
            for frame, fid, ts in zip(frames, frame_ids, timestamps)
        ]

    @property
    def model_info(self) -> dict:
        """Return model metadata."""
        return {
            "model_name": self.model_name,
            "confidence_threshold": self.confidence_threshold,
            "target_classes": {cid: COCO_CLASSES.get(cid, "unknown") for cid in self.target_classes},
            "initialized": self._initialized,
        }
