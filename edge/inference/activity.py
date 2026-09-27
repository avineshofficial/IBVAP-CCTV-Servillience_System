"""
IBVAP — Suspicious Activity Detection Module
===============================================
Rule-based behavior analysis using track geometry and history.
Detects: loitering, crawling, sprinting, group forming.
"""

import math
import time
import logging
from dataclasses import dataclass
from typing import Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ActivityEvent:
    """A detected suspicious activity."""
    activity_type: str  # loitering, crawling, sprinting, group_forming
    track_ids: list[int]
    confidence: float
    severity: str
    description: str
    timestamp: float
    camera_id: str = "cam_01"


class ActivityDetector:
    """
    Rule-based suspicious activity detection engine.
    Uses track history and bounding box geometry — no additional ML model needed.

    Detects:
    - Loitering: track dwell time > threshold in open areas
    - Crawling: wide bbox aspect ratio + slow ground-speed
    - Sprinting: ground-speed > threshold
    - Group forming: N+ tracks converging within radius R within time T
    """

    def __init__(
        self,
        loiter_threshold: float = 60.0,       # seconds
        sprint_speed_threshold: float = 200.0,  # pixels/second
        crawl_aspect_ratio: float = 1.5,       # width/height > this = crawling
        crawl_speed_max: float = 30.0,         # px/s
        group_radius: float = 100.0,           # pixels
        group_min_count: int = 3,
        cooldown_seconds: float = 30.0,
    ):
        self.loiter_threshold = loiter_threshold
        self.sprint_speed_threshold = sprint_speed_threshold
        self.crawl_aspect_ratio = crawl_aspect_ratio
        self.crawl_speed_max = crawl_speed_max
        self.group_radius = group_radius
        self.group_min_count = group_min_count
        self.cooldown_seconds = cooldown_seconds

        # Cooldown tracking: {(activity_type, track_id): last_alert_time}
        self._cooldowns: dict[tuple, float] = {}
        self._stats = defaultdict(int)

    def _check_cooldown(self, key: tuple, timestamp: float) -> bool:
        """Check if we're in cooldown for this activity + track."""
        last = self._cooldowns.get(key, 0)
        if timestamp - last < self.cooldown_seconds:
            return True
        return False

    def _set_cooldown(self, key: tuple, timestamp: float):
        self._cooldowns[key] = timestamp

    def analyze(self, tracks: list, timestamp: float = None) -> list[ActivityEvent]:
        """
        Analyze all active tracks for suspicious activity.

        Args:
            tracks: List of TrackState objects from the tracker
            timestamp: Current timestamp

        Returns:
            List of ActivityEvent detections
        """
        if timestamp is None:
            timestamp = time.time()

        activities = []
        person_tracks = [t for t in tracks if t.class_name == "person" and t.is_active]

        # --- Loitering Detection ---
        for track in person_tracks:
            key = ("loitering", track.track_id)
            if self._check_cooldown(key, timestamp):
                continue

            if track.dwell_time >= self.loiter_threshold:
                # Check if they're staying in roughly the same area
                if len(track.ground_point_history) >= 10:
                    points = track.ground_point_history[-10:]
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    spread = max(max(xs) - min(xs), max(ys) - min(ys))

                    if spread < 150:  # Not moving much
                        activities.append(ActivityEvent(
                            activity_type="loitering",
                            track_ids=[track.track_id],
                            confidence=min(0.9, track.dwell_time / (self.loiter_threshold * 2)),
                            severity="medium",
                            description=f"Person #{track.track_id} loitering for {track.dwell_time:.0f}s",
                            timestamp=timestamp,
                        ))
                        self._set_cooldown(key, timestamp)
                        self._stats["loitering"] += 1

        # --- Crawling Detection ---
        for track in person_tracks:
            key = ("crawling", track.track_id)
            if self._check_cooldown(key, timestamp):
                continue

            # Crawling: bbox is wider than tall + slow speed
            if (track.aspect_ratio > self.crawl_aspect_ratio and
                    track.speed < self.crawl_speed_max and
                    track.speed > 2.0 and  # Must be moving at least a little
                    track.frame_count > 10):

                activities.append(ActivityEvent(
                    activity_type="crawling",
                    track_ids=[track.track_id],
                    confidence=0.7,
                    severity="high",
                    description=f"Person #{track.track_id} appears to be crawling (AR:{track.aspect_ratio:.1f})",
                    timestamp=timestamp,
                ))
                self._set_cooldown(key, timestamp)
                self._stats["crawling"] += 1

        # --- Sprinting Detection ---
        for track in person_tracks:
            key = ("sprinting", track.track_id)
            if self._check_cooldown(key, timestamp):
                continue

            if (track.speed > self.sprint_speed_threshold and
                    track.frame_count > 5):
                activities.append(ActivityEvent(
                    activity_type="sprinting",
                    track_ids=[track.track_id],
                    confidence=0.8,
                    severity="high",
                    description=f"Person #{track.track_id} sprinting at {track.speed:.0f} px/s",
                    timestamp=timestamp,
                ))
                self._set_cooldown(key, timestamp)
                self._stats["sprinting"] += 1

        # --- Group Forming Detection ---
        if len(person_tracks) >= self.group_min_count:
            key = ("group_forming", 0)
            if not self._check_cooldown(key, timestamp):
                clusters = self._find_clusters(person_tracks)
                for cluster_ids in clusters:
                    if len(cluster_ids) >= self.group_min_count:
                        activities.append(ActivityEvent(
                            activity_type="group_forming",
                            track_ids=cluster_ids,
                            confidence=0.75,
                            severity="high",
                            description=f"{len(cluster_ids)} persons converging within {self.group_radius:.0f}px radius",
                            timestamp=timestamp,
                        ))
                        self._set_cooldown(key, timestamp)
                        self._stats["group_forming"] += 1

        return activities

    def _find_clusters(self, tracks: list) -> list[list[int]]:
        """Simple distance-based clustering of track positions."""
        if not tracks:
            return []

        positions = [(t.track_id, t.ground_point) for t in tracks]
        visited = set()
        clusters = []

        for i, (tid, pos) in enumerate(positions):
            if tid in visited:
                continue

            cluster = [tid]
            visited.add(tid)

            for j, (tid2, pos2) in enumerate(positions):
                if tid2 in visited:
                    continue

                dist = math.sqrt(
                    (pos[0] - pos2[0])**2 + (pos[1] - pos2[1])**2
                )
                if dist < self.group_radius:
                    cluster.append(tid2)
                    visited.add(tid2)

            if len(cluster) >= self.group_min_count:
                clusters.append(cluster)

        return clusters

    @property
    def stats(self) -> dict:
        return dict(self._stats)
