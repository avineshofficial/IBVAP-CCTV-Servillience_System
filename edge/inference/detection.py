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
    Uses Ultralytics YOLO26n with RTX 3050 CUDA / FP16 acceleration.
    """

    def __init__(
        self,
        model_name: str = "yolo26n.pt",
        confidence_threshold: float = 0.4,
        target_classes: list[int] = None,
        device: str = "cuda:0",
        half: Optional[bool] = None,
        imgsz: int = 640,
    ):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.target_classes = target_classes or [0, 1, 2, 3, 5, 7]
        self.imgsz = imgsz

        # Explicit hardware resolution: prioritize NVIDIA discrete GPU (cuda:0)
        self._device, self._half = self._resolve_device(device, half)
        self._model = None
        self._initialized = False

    @staticmethod
    def _resolve_device(requested_device: str, requested_half: Optional[bool]) -> tuple[str, bool]:
        """Resolve inference device and half precision, falling back to CPU if CUDA is unavailable."""
        try:
            import torch
            cuda_avail = torch.cuda.is_available()
        except ImportError:
            cuda_avail = False

        dev_str = str(requested_device).strip().lower()

        if dev_str.startswith("cuda") or dev_str in ("auto", "gpu"):
            if cuda_avail:
                resolved_dev = "cuda:0"
                try:
                    import torch
                    gpu_name = torch.cuda.get_device_name(0)
                    logger.info(f"YOLO26 Detector binding to NVIDIA discrete GPU: {resolved_dev} ({gpu_name})")
                except Exception:
                    logger.info(f"YOLO26 Detector binding to GPU: {resolved_dev}")
                use_half = True if requested_half is None else requested_half
                return resolved_dev, use_half
            else:
                logger.info("CUDA requested but torch.cuda.is_available() is False; gracefully falling back to CPU.")
                return "cpu", False
        else:
            use_half = False if dev_str == "cpu" else (True if requested_half is None else requested_half)
            return dev_str, use_half

    def initialize(self):
        """Load the YOLO26 model. Called lazily on first detect() call."""
        if self._initialized:
            return

        try:
            import os
            from pathlib import Path
            if "YOLO_CONFIG_DIR" not in os.environ:
                cfg_dir = Path(__file__).resolve().parent.parent.parent / ".ultralytics"
                cfg_dir.mkdir(parents=True, exist_ok=True)
                os.environ["YOLO_CONFIG_DIR"] = str(cfg_dir)

            from ultralytics import YOLO

            logger.info(f"Loading YOLO26 model: {self.model_name} on {self._device} (FP16={self._half})...")
            self._model = YOLO(self.model_name)

            # Bind model to target hardware
            try:
                self._model.to(self._device)
            except Exception as e:
                logger.warning(f"Could not explicitly bind YOLO model to {self._device}: {e}")

            # Warm up with a dummy inference using YOLO26 NMS-free predict signature
            dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            warmup_kwargs = {
                "conf": self.confidence_threshold,
                "imgsz": self.imgsz,
                "device": self._device,
                "verbose": False,
            }
            if self._device.startswith("cuda"):
                warmup_kwargs["half"] = self._half
            self._model.predict(dummy, **warmup_kwargs)

            self._initialized = True
            logger.info(f"YOLO26 model loaded and warmed up successfully: {self.model_name}")

        except Exception as e:
            logger.error(f"Failed to load YOLO26 model: {e}")
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
            # Prepare kwargs for YOLO26 NMS-free predict
            predict_kwargs = {
                "conf": self.confidence_threshold,
                "classes": self.target_classes,
                "imgsz": self.imgsz,
                "device": self._device,
                "verbose": False,
            }
            if self._device.startswith("cuda"):
                predict_kwargs["half"] = self._half

            results = self._model.predict(frame, **predict_kwargs)

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
    def active_device_str(self) -> str:
        """Return human-readable active device description."""
        if self._device.startswith("cuda"):
            gpu_name = "NVIDIA GeForce RTX 3050 Laptop GPU"
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_name = torch.cuda.get_device_name(0)
            except Exception:
                pass
            fp16_str = "FP16" if self._half else "FP32"
            return f"GPU: CUDA:0 {fp16_str} ({gpu_name})"
        return "CPU: Intel Core i5-13420H"

    @property
    def is_cuda(self) -> bool:
        return self._device.startswith("cuda")

    @property
    def model_info(self) -> dict:
        """Return model metadata."""
        return {
            "model_name": self.model_name,
            "device": self._device,
            "half_precision": self._half,
            "device_description": self.active_device_str,
            "confidence_threshold": self.confidence_threshold,
            "target_classes": {cid: COCO_CLASSES.get(cid, "unknown") for cid in self.target_classes},
            "initialized": self._initialized,
        }
