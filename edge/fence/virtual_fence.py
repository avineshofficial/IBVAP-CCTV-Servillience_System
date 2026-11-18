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
        # Zone-level incident cooldown (prevents nonstop alerts queue spam)
        self._zone_breach_cooldown: dict[str, float] = {}
        self._cooldown_seconds = 5.0
        self._zone_cooldown_seconds = 5.0

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
        # Block deprecated screen-splitting horizontal line
        if zone.zone_id == "zone_border_line":
            logger.info("Ignoring legacy screen-splitting line zone 'zone_border_line'")
            return
        if zone.rule_type == FenceRuleType.LINE_CROSS and len(zone.polygon_points_pixel) == 2:
            p1, p2 = zone.polygon_points_pixel
            if abs(p1[1] - p2[1]) < 10.0 and abs(p2[0] - p1[0]) >= 800:
                logger.info(f"Ignoring legacy full-width horizontal dividing line '{zone.zone_id}'")
                return
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

    def _check_straight_line_crossing(
        self,
        track_id: int,
        zone_id: str,
        current_point: tuple[float, float],
        line_pts: list[tuple[float, float]],
        prev_point: tuple[float, float] = None,
        bbox: tuple = None,
    ) -> Optional[str]:
        """
        Check if a tracked object crossed a straight line boundary (in or out).
        line_pts: [ (x1, y1), (x2, y2) ]
        Returns:
            "crossed_in": crossed into restricted side
            "crossed_out": crossed into secure side
            None: no crossing
        """
        if len(line_pts) < 2:
            return None

        p1, p2 = line_pts[0], line_pts[1]
        x1, y1 = p1
        x2, y2 = p2

        key = (track_id, zone_id)

        # 2D cross-product to determine which side of directed line (p1 -> p2) point is on:
        def side_of_line(pt):
            return (x2 - x1) * (pt[1] - y1) - (y2 - y1) * (pt[0] - x1)

        curr_side = side_of_line(current_point)
        was_side = self._crossing_state.get(key)

        # Check bbox bottom and center
        side_bottom = curr_side
        side_center = curr_side
        touches_line = False
        if bbox is not None and len(bbox) == 4:
            bx1, by1, bx2, by2 = bbox
            side_bottom = side_of_line(((bx1 + bx2) / 2.0, by2))
            side_center = side_of_line(((bx1 + bx2) / 2.0, (by1 + by2) / 2.0))
            
            # Touch detection: check if human body / bounding box touches or intersects the line
            line_y = (y1 + y2) / 2.0
            min_lx, max_lx = min(x1, x2), max(x1, x2)
            if (by1 - 6 <= line_y <= by2 + 6) and (bx2 >= min_lx and bx1 <= max_lx):
                touches_line = True

        touch_key = (track_id, f"{zone_id}_touch")
        was_touching = self._crossing_state.get(touch_key, False)

        if was_side is None and prev_point is not None:
            was_side = side_of_line(prev_point)

        result = None
        # 1. Trigger if human touches the border line
        if touches_line and not was_touching:
            result = "touched_border_line"

        self._crossing_state[touch_key] = touches_line

        # 2. Trigger if crossing between zones (IN / OUT) or first seen on restricted side
        if result is None:
            if was_side is not None:
                # Crossed IN (into restricted area below line)
                if was_side < 0 and (curr_side >= 0 or side_bottom >= 0 or side_center >= 0):
                    result = "crossed_in"
                # Crossed OUT (back to secure area above line)
                elif was_side > 0 and (curr_side <= 0 or side_bottom <= 0 or side_center <= 0):
                    result = "crossed_out"
            elif curr_side >= 0 or side_bottom >= 0 or touches_line:
                # First seen already on restricted side below line
                result = "crossed_in"

        # Update stored side
        self._crossing_state[key] = 1 if (curr_side >= 0 or side_bottom >= 0) else -1
        return result

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
        bbox: tuple = None,
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
            if zone.zone_id == "zone_border_line":
                continue

            key = (track_id, zone.zone_id)

            # Check track-specific cooldown: ensures the same person doesn't re-trigger duplicate alerts every frame,
            # while allowing EVERY OTHER PERSON to be evaluated and alerted independently.
            last_breach = self._breach_cooldown.get(key, 0)
            if timestamp - last_breach < self._cooldown_seconds:
                continue

            # Use bottom-center point of bounding box as the ground-contact point
            if bbox is not None and len(bbox) == 4:
                bx1, by1, bx2, by2 = bbox
                ground_contact_pt = ((bx1 + bx2) / 2.0, float(by2))
            else:
                ground_contact_pt = ground_point

            polygon = zone.polygon_points_pixel

            # High-precision point-in-polygon test via cv2.pointPolygonTest
            if cv2 is not None and len(polygon) >= 3:
                contour = np.array([(int(p[0]), int(p[1])) for p in polygon], dtype=np.int32)
                # Returns >= 0 if inside polygon or on boundary
                is_inside = cv2.pointPolygonTest(contour, (float(ground_contact_pt[0]), float(ground_contact_pt[1])), False) >= 0
            else:
                is_inside = self._point_in_polygon(ground_contact_pt, polygon)

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
                if len(polygon) == 2:
                    prev_pt = track_history[-2] if (track_history and len(track_history) >= 2) else None
                    crossing = self._check_straight_line_crossing(
                        track_id=track_id,
                        zone_id=zone.zone_id,
                        current_point=ground_point,
                        line_pts=polygon,
                        prev_point=prev_pt,
                        bbox=bbox,
                    )
                else:
                    crossing = self._check_line_crossing(
                        track_id, zone.zone_id, ground_point, polygon
                    )
                if crossing:
                    breach = FenceBreach(
                        zone_id=zone.zone_id,
                        zone_name=zone.name,
                        track_id=track_id,
                        object_class=object_class,
                        breach_type=crossing,
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
                self._zone_breach_cooldown[zone.zone_id] = timestamp

        return breaches

    def create_perspective_restricted_zone(
        self,
        polygon_points: list[tuple[float, float]],
        camera_id: str = "cam_01",
        frame_width: int = 1280,
        frame_height: int = 720,
        base_width: int = 1280,
        base_height: int = 720,
    ):
        """
        Create a perspective-based restricted zone following the camera's floor perspective.

        The polygon should be a trapezoid (or any convex/concave polygon) that follows
        the visible floor area in the camera view. The far edge (top of zone) should be
        narrower, and the near edge (bottom of frame) should be wider — matching real
        perspective foreshortening.

        Coordinates scale automatically:
        - If normalized (0.0 to 1.0), scaled by (frame_width, frame_height).
        - If in pixel space, scaled from (base_width, base_height) to (frame_width, frame_height).

        Args:
            polygon_points: List of (x, y) tuples defining the restricted floor polygon.
            camera_id: Camera identifier.
            frame_width: Current frame width.
            frame_height: Current frame height.
            base_width: Reference width the coordinates were authored at (default: 1280).
            base_height: Reference height the coordinates were authored at (default: 720).
        """
        # Clear any old straight-line and rectangular zones
        for old_id in ("zone_border_line", "zone_restricted_area"):
            if old_id in self._zones:
                self.remove_zone(old_id)

        zone_id = "zone_restricted_area"

        # Scale coordinates correctly with video resolution
        scaled_polygon = []
        scale_x = frame_width / float(base_width) if base_width > 0 else 1.0
        scale_y = frame_height / float(base_height) if base_height > 0 else 1.0

        for x, y in polygon_points:
            # Check if normalized [0.0 - 1.0]
            if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and max(p[0] for p in polygon_points) <= 1.0:
                sx = float(x * frame_width)
                sy = float(y * frame_height)
            else:
                sx = float(x * scale_x)
                sy = float(y * scale_y)
            scaled_polygon.append((round(sx, 1), round(sy, 1)))

        restricted_zone = FenceZone(
            zone_id=zone_id,
            name="Restricted Floor Zone",
            camera_id=camera_id,
            polygon_points_pixel=scaled_polygon,
            rule_type=FenceRuleType.EXCLUSION,
            severity=BreachSeverity.CRITICAL,
        )
        self.add_zone(restricted_zone)
        logger.info(
            f"Initialized perspective restricted zone with {len(scaled_polygon)} vertices "
            f"for {camera_id} at {frame_width}x{frame_height}: {scaled_polygon}"
        )

    # ── Legacy aliases (kept for backward compatibility) ──

    def create_straight_border_line(
        self,
        frame_width: int = 1280,
        frame_height: int = 720,
        camera_id: str = "cam_01",
        line_y_ratio: float = 0.52,
    ):
        """Legacy: Create a straight border line. Now redirects to perspective zone."""
        logger.info("create_straight_border_line() called — redirecting to perspective zone")
        # Default 6-point perspective polygon lowered to floor level
        default_polygon = [
            (0.0, frame_height * 0.76),
            (frame_width * 0.19, frame_height * 0.72),
            (frame_width * 0.81, frame_height * 0.72),
            (float(frame_width), frame_height * 0.76),
            (float(frame_width), float(frame_height)),
            (0.0, float(frame_height)),
        ]
        self.create_perspective_restricted_zone(default_polygon, camera_id, frame_width, frame_height)

    def create_restricted_border_zone(self, frame_width: int, frame_height: int, camera_id: str = "cam_01"):
        """Legacy alias."""
        self.create_straight_border_line(frame_width, frame_height, camera_id)

    def create_demo_zones(self, frame_width: int, frame_height: int, camera_id: str = "cam_01"):
        """Backward-compatible alias."""
        self.create_straight_border_line(frame_width, frame_height, camera_id)

    def create_restricted_area_zone(
        self,
        frame_width: int = 1280,
        frame_height: int = 720,
        camera_id: str = "cam_01",
        line_y_ratio: float = 0.52,
    ):
        """Legacy: now a no-op since perspective zone is created by create_perspective_restricted_zone."""
        # The perspective zone already covers the restricted area
        if "zone_restricted_area" in self._zones:
            return
        # Fallback: create default perspective zone
        self.create_straight_border_line(frame_width, frame_height, camera_id)
