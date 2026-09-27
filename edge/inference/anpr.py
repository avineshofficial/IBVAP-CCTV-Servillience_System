"""
IBVAP — ANPR (Automatic Number Plate Recognition) Module
==========================================================
YOLO plate detection + PaddleOCR + Indian plate format validation + multi-frame voting.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict, Counter
import numpy as np

logger = logging.getLogger(__name__)

# Indian license plate format patterns
INDIAN_PLATE_PATTERNS = [
    r'^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$',      # Standard: MH12AB1234
    r'^[A-Z]{2}\d{2}[A-Z]{1,3}\d{1,4}$',     # Flexible: MH12A1234
    r'^[A-Z]{2}\d{2}\d{4}$',                   # Old format: MH121234
    r'^\d{2}BH\d{4}[A-Z]{1,2}$',              # BH series: 22BH1234AA
]


@dataclass
class PlateResult:
    """A recognized license plate."""
    plate_text: str
    confidence: float
    bbox: list  # [x1, y1, x2, y2] relative to vehicle crop
    track_id: int
    is_valid_format: bool
    format_type: str  # "indian_standard", "indian_old", "unknown"
    vote_count: int = 1


class ANPREngine:
    """
    Automatic Number Plate Recognition pipeline:
    1. Detect plate region (using OCR directly on vehicle crop)
    2. OCR text extraction via PaddleOCR
    3. Indian plate format validation
    4. Multi-frame voting for accuracy
    """

    def __init__(
        self,
        confidence: float = 0.5,
        vote_frames: int = 5,
    ):
        self.confidence = confidence
        self.vote_frames = vote_frames
        self._ocr = None
        self._initialized = False

        # Multi-frame voting: {track_id: [plate_text, ...]}
        self._vote_buffer: dict[int, list[str]] = defaultdict(list)
        self._finalized: dict[int, str] = {}

    def initialize(self):
        """Load PaddleOCR model."""
        if self._initialized:
            return

        try:
            from paddleocr import PaddleOCR

            logger.info("Loading PaddleOCR for ANPR...")
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                show_log=False,
                use_gpu=False,
            )
            self._initialized = True
            logger.info("ANPR engine initialized")

        except ImportError:
            logger.warning(
                "PaddleOCR not installed. ANPR disabled. "
                "Install with: pip install paddlepaddle paddleocr"
            )
            self._initialized = True  # Don't warn again
        except Exception as e:
            logger.warning(f"ANPR initialization failed: {e}")

    def _extract_text(self, crop: np.ndarray) -> list[tuple[str, float]]:
        """Extract text from a vehicle/plate crop using OCR."""
        if not self._initialized:
            self.initialize()

        if self._ocr is None or crop.size == 0:
            return []

        try:
            h, w = crop.shape[:2]
            if h < 15 or w < 30:
                return []

            result = self._ocr.ocr(crop, cls=True)

            texts = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        text = line[1][0]
                        conf = line[1][1]
                        # Clean up: remove spaces, convert to uppercase
                        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
                        if len(cleaned) >= 4 and conf >= self.confidence:
                            texts.append((cleaned, conf))

            return texts

        except Exception as e:
            logger.debug(f"OCR error: {e}")
            return []

    @staticmethod
    def validate_indian_plate(text: str) -> tuple[bool, str]:
        """
        Validate against Indian license plate formats.
        Returns (is_valid, format_type).
        """
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())

        for i, pattern in enumerate(INDIAN_PLATE_PATTERNS):
            if re.match(pattern, cleaned):
                types = ["indian_standard", "indian_flexible", "indian_old", "indian_bh"]
                return True, types[i]

        # Partial match: at least state code + district code pattern
        if re.match(r'^[A-Z]{2}\d{2}', cleaned) and len(cleaned) >= 6:
            return True, "indian_partial"

        return False, "unknown"

    def read_plate(self, vehicle_crop: np.ndarray, track_id: int) -> Optional[PlateResult]:
        """
        Read license plate from a vehicle crop.
        Uses multi-frame voting for accuracy.
        """
        texts = self._extract_text(vehicle_crop)

        if not texts:
            return None

        # Get best OCR result
        best_text, best_conf = max(texts, key=lambda x: x[1])

        # Validate format
        is_valid, format_type = self.validate_indian_plate(best_text)

        # Multi-frame voting
        self._vote_buffer[track_id].append(best_text)

        # Keep buffer manageable
        if len(self._vote_buffer[track_id]) > self.vote_frames * 2:
            self._vote_buffer[track_id] = self._vote_buffer[track_id][-self.vote_frames:]

        # Check if we have enough votes
        votes = self._vote_buffer[track_id]
        if len(votes) >= self.vote_frames:
            # Majority vote
            counter = Counter(votes[-self.vote_frames:])
            final_text, vote_count = counter.most_common(1)[0]

            if vote_count >= self.vote_frames // 2:
                self._finalized[track_id] = final_text
                is_valid, format_type = self.validate_indian_plate(final_text)

                return PlateResult(
                    plate_text=final_text,
                    confidence=best_conf,
                    bbox=[0, 0, vehicle_crop.shape[1], vehicle_crop.shape[0]],
                    track_id=track_id,
                    is_valid_format=is_valid,
                    format_type=format_type,
                    vote_count=vote_count,
                )

        # Return interim result if valid
        if is_valid:
            return PlateResult(
                plate_text=best_text,
                confidence=best_conf,
                bbox=[0, 0, vehicle_crop.shape[1], vehicle_crop.shape[0]],
                track_id=track_id,
                is_valid_format=is_valid,
                format_type=format_type,
                vote_count=1,
            )

        return None

    def get_finalized_plate(self, track_id: int) -> Optional[str]:
        """Get the final voted plate text for a track."""
        return self._finalized.get(track_id)

    def cleanup_track(self, track_id: int):
        """Clean up voting buffer for a completed track."""
        self._vote_buffer.pop(track_id, None)
        self._finalized.pop(track_id, None)

    @property
    def is_available(self) -> bool:
        return self._initialized and self._ocr is not None
