"""
IBVAP — Face Detection & Recognition Module
==============================================
SCRFD face detection + ArcFace embedding via InsightFace.
Runs on person crops, not full frames, for efficiency.
"""

import logging
from dataclasses import dataclass
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FaceResult:
    """A detected face with embedding."""
    bbox: list  # [x1, y1, x2, y2] relative to crop
    confidence: float
    embedding: Optional[np.ndarray]  # 512-dim ArcFace embedding
    landmarks: Optional[np.ndarray]
    track_id: int
    age: Optional[int] = None
    gender: Optional[str] = None


class FaceDetector:
    """
    Face detection and recognition using InsightFace.
    Uses SCRFD for detection and ArcFace for embedding extraction.
    """

    def __init__(
        self,
        model_pack: str = "buffalo_l",
        det_size: tuple = (640, 640),
        det_threshold: float = 0.5,
    ):
        self.model_pack = model_pack
        self.det_size = det_size
        self.det_threshold = det_threshold
        self._app = None
        self._initialized = False

    def initialize(self):
        """Load InsightFace models."""
        if self._initialized:
            return

        try:
            from insightface.app import FaceAnalysis

            logger.info(f"Loading face analysis models ({self.model_pack})...")
            self._app = FaceAnalysis(
                name=self.model_pack,
                providers=["CPUExecutionProvider"],
            )
            self._app.prepare(ctx_id=-1, det_size=self.det_size)
            self._initialized = True
            logger.info("Face detector initialized successfully")

        except ImportError:
            logger.warning(
                "InsightFace not installed. Face detection disabled. "
                "Install with: pip install insightface onnxruntime"
            )
            self._initialized = True  # Don't warn again
        except Exception as e:
            logger.warning(f"Face detector initialization failed: {e}")

    def detect(self, person_crop: np.ndarray, track_id: int = 0) -> list[FaceResult]:
        """
        Detect faces in a person crop.

        Args:
            person_crop: BGR image crop of a detected person
            track_id: Associated track ID

        Returns:
            List of FaceResult objects
        """
        if not self._initialized:
            self.initialize()

        if self._app is None or person_crop.size == 0:
            return []

        try:
            # Minimum crop size check
            h, w = person_crop.shape[:2]
            if h < 30 or w < 20:
                return []

            faces = self._app.get(person_crop)

            results = []
            for face in faces:
                if face.det_score < self.det_threshold:
                    continue

                result = FaceResult(
                    bbox=face.bbox.tolist(),
                    confidence=float(face.det_score),
                    embedding=face.embedding if hasattr(face, 'embedding') else None,
                    landmarks=face.landmark_2d_106 if hasattr(face, 'landmark_2d_106') else None,
                    track_id=track_id,
                    age=int(face.age) if hasattr(face, 'age') and face.age else None,
                    gender="M" if hasattr(face, 'gender') and face.gender == 1 else "F" if hasattr(face, 'gender') and face.gender == 0 else None,
                )
                results.append(result)

            return results

        except Exception as e:
            logger.debug(f"Face detection error: {e}")
            return []

    def get_embedding(self, person_crop: np.ndarray) -> Optional[np.ndarray]:
        """Extract face embedding from a person crop (first face found)."""
        faces = self.detect(person_crop)
        if faces and faces[0].embedding is not None:
            return faces[0].embedding
        return None

    @staticmethod
    def blur_face(frame: np.ndarray, bbox: list, blur_factor: int = 50) -> np.ndarray:
        """
        Apply privacy-preserving blur to a face region.
        Used for dashboard display when privacy mode is enabled.
        """
        try:
            import cv2
            x1, y1, x2, y2 = [int(c) for c in bbox]
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            face_roi = frame[y1:y2, x1:x2]
            if face_roi.size == 0:
                return frame

            blurred = cv2.GaussianBlur(face_roi, (blur_factor | 1, blur_factor | 1), 0)
            frame[y1:y2, x1:x2] = blurred
            return frame
        except Exception:
            return frame

    @property
    def is_available(self) -> bool:
        return self._initialized and self._app is not None
