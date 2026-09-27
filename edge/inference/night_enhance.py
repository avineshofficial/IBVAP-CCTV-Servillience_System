"""
IBVAP — Night Enhancement Module
===================================
Low-light frame enhancement using CLAHE and Zero-DCE-inspired processing.
Luminance-gated: only enhances frames below brightness threshold.
"""

import logging
from typing import Tuple
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger(__name__)


class NightEnhancer:
    """
    Night-time frame enhancement for low-light CCTV footage.

    Strategy (from §9):
    1. Compute mean frame luminance
    2. If below threshold, apply enhancement
    3. If still too dark, flag for motion-diff fallback

    Uses CLAHE (Contrast Limited Adaptive Histogram Equalization)
    as a fast, reliable enhancement. Zero-DCE noted as production upgrade.
    """

    def __init__(
        self,
        threshold: int = 60,
        clahe_clip_limit: float = 3.0,
        clahe_grid_size: tuple = (8, 8),
    ):
        self.threshold = threshold
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_grid_size = clahe_grid_size
        self._clahe = None
        self._enhanced_count = 0
        self._total_checked = 0

        if cv2 is not None:
            self._clahe = cv2.createCLAHE(
                clipLimit=clahe_clip_limit,
                tileGridSize=clahe_grid_size,
            )

    def compute_luminance(self, frame: np.ndarray) -> float:
        """Compute mean luminance of a frame (0-255)."""
        if cv2 is None:
            return 128.0

        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        return float(np.mean(gray))

    def is_low_light(self, frame: np.ndarray) -> bool:
        """Check if frame is below the low-light threshold."""
        luminance = self.compute_luminance(frame)
        return luminance < self.threshold

    def enhance(self, frame: np.ndarray) -> np.ndarray:
        """
        Enhance a low-light frame using multi-stage processing:
        1. CLAHE on luminance channel
        2. Gamma correction
        3. Noise reduction
        """
        if cv2 is None:
            return frame

        try:
            # Convert to LAB color space
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l_channel, a_channel, b_channel = cv2.split(lab)

            # Apply CLAHE to luminance channel
            if self._clahe is not None:
                l_enhanced = self._clahe.apply(l_channel)
            else:
                l_enhanced = l_channel

            # Gamma correction for further brightening
            gamma = 0.7  # < 1 brightens
            inv_gamma = 1.0 / gamma
            table = np.array(
                [((i / 255.0) ** inv_gamma) * 255 for i in range(256)]
            ).astype("uint8")
            l_enhanced = cv2.LUT(l_enhanced, table)

            # Recombine channels
            enhanced_lab = cv2.merge([l_enhanced, a_channel, b_channel])
            enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

            # Light denoising
            enhanced = cv2.fastNlMeansDenoisingColored(
                enhanced, None, h=6, hColor=6,
                templateWindowSize=7, searchWindowSize=21,
            )

            return enhanced

        except Exception as e:
            logger.warning(f"Enhancement failed, returning original: {e}")
            return frame

    def enhance_if_needed(self, frame: np.ndarray) -> Tuple[np.ndarray, bool]:
        """
        Check luminance and enhance only if needed.

        Returns:
            (enhanced_frame, was_enhanced)
        """
        self._total_checked += 1
        luminance = self.compute_luminance(frame)

        if luminance < self.threshold:
            enhanced = self.enhance(frame)
            self._enhanced_count += 1

            # Check if enhancement helped enough
            new_luminance = self.compute_luminance(enhanced)
            if new_luminance < self.threshold * 0.5:
                logger.debug(
                    f"Frame still very dark after enhancement "
                    f"(lum: {luminance:.0f} → {new_luminance:.0f}). "
                    f"Motion-diff fallback recommended."
                )

            return enhanced, True

        return frame, False

    def create_comparison(self, frame: np.ndarray) -> np.ndarray:
        """Create a side-by-side comparison for demo."""
        if cv2 is None:
            return frame

        enhanced = self.enhance(frame)
        h, w = frame.shape[:2]

        # Add labels
        original_labeled = frame.copy()
        enhanced_labeled = enhanced.copy()

        cv2.putText(original_labeled, "ORIGINAL (Low Light)",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(original_labeled, f"Luminance: {self.compute_luminance(frame):.0f}",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        cv2.putText(enhanced_labeled, "ENHANCED (Night Mode)",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(enhanced_labeled, f"Luminance: {self.compute_luminance(enhanced):.0f}",
                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # Side by side
        comparison = np.hstack([original_labeled, enhanced_labeled])
        return comparison

    @property
    def stats(self) -> dict:
        return {
            "total_checked": self._total_checked,
            "enhanced_count": self._enhanced_count,
            "enhancement_rate": (
                self._enhanced_count / self._total_checked
                if self._total_checked > 0 else 0
            ),
            "threshold": self.threshold,
        }
