"""
IBVAP — Virtual Fence Module
==============================
Homography-calibrated polygon/line-crossing + dwell rules.
Projects ground points from pixel space to geo-referenced coordinates.
"""

import time
import logging
import math
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

logger = logging.getLogger(__name__)


class FenceRuleType(str, Enum):
    LINE_CROSS = "line_cross"
    DWELL = "dwell"
    DIRECTION = "direction"
    EXCLUSION = "exclusion"


class BreachSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FenceZone:
    """A virtual fence zone definition."""
    zone_id: str
    name: str
    camera_id: str
    polygon_points_pixel: list[tuple[float, float]]
    rule_type: FenceRuleType
    severity: BreachSeverity = BreachSeverity.HIGH
    dwell_threshold: float = 30.0  # seconds for dwell rules
    direction_vector: Optional[tuple[float, float]] = None  # for direction rules
    polygon_points_geo: Optional[list[tuple[float, float]]] = None
    is_active: bool = True


@dataclass
class FenceBreach:
    """A detected fence breach event."""
    zone_id: str
    zone_name: str
    track_id: int
    object_class: str
    breach_type: str  # "entered", "crossed", "dwelling", "wrong_direction"
    severity: str
    ground_point_pixel: tuple[float, float]
    ground_point_geo: Optional[tuple[float, float]]
    dwell_time: Optional[float]
    timestamp: float
    camera_id: str
    confidence: float


class VirtualFenceEngine:
    """
    Virtual fence engine with homography calibration.

    Supports:
    - Polygon exclusion zones (point-in-polygon test)
    - Line crossing detection (using track history)
    - Dwell time monitoring
    - Direction-of-travel validation
    """

    def __init__(self):
        self._zones: dict[str, FenceZone] = {}
        self._homography_matrix: Optional[np.ndarray] = None
        self._inverse_homography: Optional[np.ndarray] = None

        # Track dwell state: {(track_id, zone_id): first_entry_time}
        self._dwell_tracker: dict[tuple[int, str], float] = {}
        # Track crossing state: {(track_id, zone_id): was_inside}
        self._crossing_state: dict[tuple[int, str], bool] = {}
        # Breach cooldown: {(track_id, zone_id): last_breach_time}
        self._breach_cooldown: dict[tuple[int, str], float] = {}
        self._cooldown_seconds = 10.0

    def calibrate(
        self,
        pixel_points: list[tuple[float, float]],
        geo_points: list[tuple[float, float]],
    ) -> bool:
        """
        Compute homography matrix from 4+ reference point pairs.

        Args:
            pixel_points: Points in pixel coordinates [(x,y), ...]
            geo_points: Corresponding points in geo/world coordinates [(lat,lng), ...]
        """
        if cv2 is None:
            logger.warning("OpenCV not available for homography computation")
            return False

        if len(pixel_points) < 4 or len(geo_points) < 4:
            logger.error("Need at least 4 point pairs for homography")
            return False

        src = np.array(pixel_points, dtype=np.float32)
        dst = np.array(geo_points, dtype=np.float32)

        try:
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
            if H is None:
                logger.error("Homography computation failed")
                return False

            self._homography_matrix = H
            self._inverse_homography = np.linalg.inv(H)
            logger.info("Homography calibration successful")
            return True

        except Exception as e:
            logger.error(f"Homography calibration error: {e}")
            return False

    def pixel_to_geo(self, pixel_point: tuple[float, float]) -> Optional[tuple[float, float]]:
        """Project a pixel point to geo coordinates using homography."""
        if self._homography_matrix is None:
            return None

        pt = np.array([[pixel_point[0], pixel_point[1], 1.0]], dtype=np.float64)
        transformed = self._homography_matrix @ pt.T
        if transformed[2, 0] == 0:
            return None

        x = transformed[0, 0] / transformed[2, 0]
        y = transformed[1, 0] / transformed[2, 0]
        return (float(x), float(y))

    def add_zone(self, zone: FenceZone):
        """Register a virtual fence zone."""
        self._zones[zone.zone_id] = zone
        logger.info(f"Added fence zone: {zone.name} ({zone.rule_type.value})")

    def remove_zone(self, zone_id: str):
        """Remove a virtual fence zone."""
        self._zones.pop(zone_id, None)
        # Clean up related state
        self._dwell_tracker = {
            k: v for k, v in self._dwell_tracker.items() if k[1] != zone_id
        }
        self._crossing_state = {
            k: v for k, v in self._crossing_state.items() if k[1] != zone_id
        }

    def get_zones(self) -> list[FenceZone]:
        """Get all registered zones."""
        return list(self._zones.values())

    def _point_in_polygon(
        self, point: tuple[float, float], polygon: list[tuple[float, float]]
    ) -> bool:
        """Ray-casting algorithm for point-in-polygon test."""
        x, y = point
        n = len(polygon)
        inside = False

        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]

            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i

        return inside

    def _check_line_crossing(
        self,
        track_id: int,
        zone_id: str,
        current_point: tuple[float, float],
        polygon: list[tuple[float, float]],
    ) -> Optional[str]:
        """Check if a track has crossed a zone boundary."""
        key = (track_id, zone_id)
        is_inside = self._point_in_polygon(current_point, polygon)
        was_inside = self._crossing_state.get(key)

        self._crossing_state[key] = is_inside

        if was_inside is None:
            return None

        if not was_inside and is_inside:
            return "entered"
        elif was_inside and not is_inside:
            return "exited"

        return None

    def _check_dwell(
        self,
        track_id: int,
        zone_id: str,
        is_inside: bool,
        threshold: float,
        timestamp: float,
    ) -> Optional[float]:
        """Check if a track has been dwelling in a zone beyond threshold."""
        key = (track_id, zone_id)

        if is_inside:
            if key not in self._dwell_tracker:
                self._dwell_tracker[key] = timestamp
            dwell_time = timestamp - self._dwell_tracker[key]
            if dwell_time >= threshold:
                return dwell_time
        else:
            self._dwell_tracker.pop(key, None)

        return None

    def evaluate(
        self,
        track_id: int,
        object_class: str,
        ground_point: tuple[float, float],
        confidence: float,
        camera_id: str,
        timestamp: float = None,
        track_history: list[tuple[float, float]] = None,
    ) -> list[FenceBreach]:
        """
        Evaluate all zones against a track's current position.

        Returns list of FenceBreach events.
        """
        if timestamp is None:
            timestamp = time.time()

        breaches = []

        for zone in self._zones.values():
            if not zone.is_active or zone.camera_id != camera_id:
                continue

            key = (track_id, zone.zone_id)

            # Check cooldown
            last_breach = self._breach_cooldown.get(key, 0)
            if timestamp - last_breach < self._cooldown_seconds:
                continue

            polygon = zone.polygon_points_pixel
            is_inside = self._point_in_polygon(ground_point, polygon)
            geo_point = self.pixel_to_geo(ground_point)

            breach = None

            if zone.rule_type == FenceRuleType.EXCLUSION:
                # Exclusion zone: breach if inside
                if is_inside:
                    breach = FenceBreach(
                        zone_id=zone.zone_id,
                        zone_name=zone.name,
                        track_id=track_id,
                        object_class=object_class,
                        breach_type="entered_exclusion",
                        severity=zone.severity.value,
                        ground_point_pixel=ground_point,
                        ground_point_geo=geo_point,
                        dwell_time=None,
                        timestamp=timestamp,
                        camera_id=camera_id,
                        confidence=confidence,
                    )

            elif zone.rule_type == FenceRuleType.LINE_CROSS:
                # Line crossing: breach on entry or exit
                crossing = self._check_line_crossing(
                    track_id, zone.zone_id, ground_point, polygon
                )
                if crossing:
                    breach = FenceBreach(
                        zone_id=zone.zone_id,
                        zone_name=zone.name,
                        track_id=track_id,
                        object_class=object_class,
                        breach_type=f"crossed_{crossing}",
                        severity=zone.severity.value,
                        ground_point_pixel=ground_point,
                        ground_point_geo=geo_point,
                        dwell_time=None,
                        timestamp=timestamp,
                        camera_id=camera_id,
                        confidence=confidence,
                    )

            elif zone.rule_type == FenceRuleType.DWELL:
                # Dwell rule: breach if inside for too long
                dwell_time = self._check_dwell(
                    track_id, zone.zone_id, is_inside,
                    zone.dwell_threshold, timestamp
                )
                if dwell_time is not None:
                    breach = FenceBreach(
                        zone_id=zone.zone_id,
                        zone_name=zone.name,
                        track_id=track_id,
                        object_class=object_class,
                        breach_type="dwelling",
                        severity=zone.severity.value,
                        ground_point_pixel=ground_point,
                        ground_point_geo=geo_point,
                        dwell_time=dwell_time,
                        timestamp=timestamp,
                        camera_id=camera_id,
                        confidence=confidence,
                    )

            elif zone.rule_type == FenceRuleType.DIRECTION:
                # Direction rule: breach if moving in wrong direction
                if is_inside and track_history and len(track_history) >= 2 and zone.direction_vector:
                    p1 = track_history[-2]
                    p2 = track_history[-1]
                    movement = (p2[0] - p1[0], p2[1] - p1[1])
                    mag = math.sqrt(movement[0]**2 + movement[1]**2)
                    if mag > 1.0:  # minimum movement threshold
                        # Dot product to check alignment
                        dot = (
                            movement[0] * zone.direction_vector[0]
                            + movement[1] * zone.direction_vector[1]
                        )
                        if dot < 0:  # Moving against allowed direction
                            breach = FenceBreach(
                                zone_id=zone.zone_id,
                                zone_name=zone.name,
                                track_id=track_id,
                                object_class=object_class,
                                breach_type="wrong_direction",
                                severity=zone.severity.value,
                                ground_point_pixel=ground_point,
                                ground_point_geo=geo_point,
                                dwell_time=None,
                                timestamp=timestamp,
                                camera_id=camera_id,
                                confidence=confidence,
                            )

            if breach:
                breaches.append(breach)
                self._breach_cooldown[key] = timestamp

        return breaches

    def create_demo_zones(self, frame_width: int, frame_height: int, camera_id: str = "cam_01"):
        """Create demo fence zones for testing (covers typical CCTV layout)."""
        # Zone 1: Border line (horizontal line near the middle)
        border_zone = FenceZone(
            zone_id="zone_border_line",
            name="Border Line Alpha",
            camera_id=camera_id,
            polygon_points_pixel=[
                (0, frame_height * 0.5),
                (frame_width, frame_height * 0.5),
                (frame_width, frame_height * 0.55),
                (0, frame_height * 0.55),
            ],
            rule_type=FenceRuleType.LINE_CROSS,
            severity=BreachSeverity.CRITICAL,
        )

        # Zone 2: Restricted area (right side)
        restricted_zone = FenceZone(
            zone_id="zone_restricted",
            name="Restricted Area Bravo",
            camera_id=camera_id,
            polygon_points_pixel=[
                (frame_width * 0.7, frame_height * 0.2),
                (frame_width * 0.95, frame_height * 0.2),
                (frame_width * 0.95, frame_height * 0.8),
                (frame_width * 0.7, frame_height * 0.8),
            ],
            rule_type=FenceRuleType.EXCLUSION,
            severity=BreachSeverity.HIGH,
        )

        # Zone 3: Dwell monitoring area (left side)
        dwell_zone = FenceZone(
            zone_id="zone_dwell",
            name="Dwell Monitor Charlie",
            camera_id=camera_id,
            polygon_points_pixel=[
                (frame_width * 0.05, frame_height * 0.3),
                (frame_width * 0.3, frame_height * 0.3),
                (frame_width * 0.3, frame_height * 0.7),
                (frame_width * 0.05, frame_height * 0.7),
            ],
            rule_type=FenceRuleType.DWELL,
            severity=BreachSeverity.MEDIUM,
            dwell_threshold=15.0,
        )

        self.add_zone(border_zone)
        self.add_zone(restricted_zone)
        self.add_zone(dwell_zone)

        logger.info(f"Created {len(self._zones)} demo fence zones")
