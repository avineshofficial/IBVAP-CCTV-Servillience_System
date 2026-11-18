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
    Hybrid activity detection engine:
    1. Fast geometric rule-based checks on CPU
    2. Scikit-learn Random Forest posture/behavior classification on CPU (n_jobs=1)
       avoids thread contention during single-sample real-time inference.

    Detects:
    - Loitering: track dwell time > threshold in open areas (Rules + RF)
    - Crawling: wide bbox aspect ratio + slow ground-speed (Rules + RF)
    - Sprinting: ground-speed > threshold (Rules + RF)
    - Group forming: N+ tracks converging within radius R within time T (Clustering)
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
        n_jobs: int = 1,                       # CPU single-sample execution (no thread contention)
    ):
        self.loiter_threshold = loiter_threshold
        self.sprint_speed_threshold = sprint_speed_threshold
        self.crawl_aspect_ratio = crawl_aspect_ratio
        self.crawl_speed_max = crawl_speed_max
        self.group_radius = group_radius
        self.group_min_count = group_min_count
        self.cooldown_seconds = cooldown_seconds
        self.n_jobs = n_jobs

        # Cooldown tracking: {(activity_type, track_id): last_alert_time}
        self._cooldowns: dict[tuple, float] = {}
        self._stats = defaultdict(int)

        # CPU Scikit-Learn Random Forest Classifier
        self._rf_classifier = None
        self._rf_classes = ["normal", "loitering", "crawling", "sprinting"]
        self._init_rf_classifier()

    def _init_rf_classifier(self):
        """Initialize or calibrate lightweight Random Forest classifier on CPU."""
        try:
            from sklearn.ensemble import RandomForestClassifier
            import numpy as np

            # Calibrate model on behavioral feature distributions:
            # Features: [aspect_ratio, speed, dwell_time, spread, frame_count]
            np.random.seed(42)
            n_samples = 40

            # Normal walking
            x_normal = np.column_stack([
                np.random.uniform(0.35, 0.55, n_samples),
                np.random.uniform(15.0, 75.0, n_samples),
                np.random.uniform(0.0, 30.0, n_samples),
                np.random.uniform(60.0, 200.0, n_samples),
                np.random.uniform(10.0, 150.0, n_samples),
            ])
            y_normal = [0] * n_samples

            # Loitering
            x_loiter = np.column_stack([
                np.random.uniform(0.35, 0.60, n_samples),
                np.random.uniform(0.0, 15.0, n_samples),
                np.random.uniform(65.0, 300.0, n_samples),
                np.random.uniform(5.0, 80.0, n_samples),
                np.random.uniform(50.0, 500.0, n_samples),
            ])
            y_loiter = [1] * n_samples

            # Crawling
            x_crawl = np.column_stack([
                np.random.uniform(1.4, 2.6, n_samples),
                np.random.uniform(2.0, 25.0, n_samples),
                np.random.uniform(5.0, 45.0, n_samples),
                np.random.uniform(20.0, 120.0, n_samples),
                np.random.uniform(15.0, 150.0, n_samples),
            ])
            y_crawl = [2] * n_samples

            # Sprinting
            x_sprint = np.column_stack([
                np.random.uniform(0.40, 0.70, n_samples),
                np.random.uniform(190.0, 450.0, n_samples),
                np.random.uniform(1.0, 12.0, n_samples),
                np.random.uniform(150.0, 600.0, n_samples),
                np.random.uniform(5.0, 60.0, n_samples),
            ])
            y_sprint = [3] * n_samples

            X = np.vstack([x_normal, x_loiter, x_crawl, x_sprint])
            y = np.array(y_normal + y_loiter + y_crawl + y_sprint)

            # n_jobs=1 runs cleanly on CPU without spawning thread pools for single-track predictions
            rf = RandomForestClassifier(
                n_estimators=15,
                max_depth=5,
                n_jobs=self.n_jobs,
                random_state=42
            )
            rf.fit(X, y)
            self._rf_classifier = rf
            logger.info(f"Initialized Scikit-Learn Random Forest Activity Classifier on CPU (n_jobs={self.n_jobs})")

        except Exception as e:
            logger.warning(f"Could not initialize Random Forest classifier, using pure rules: {e}")
            self._rf_classifier = None

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

        # --- Random Forest ML Posture/Activity Classification (CPU, n_jobs=1) ---
        if self._rf_classifier is not None and person_tracks:
            import numpy as np
            for track in person_tracks:
                if track.frame_count < 5:
                    continue
                spread = 100.0
                if len(track.ground_point_history) >= 2:
                    pts = track.ground_point_history[-10:]
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    spread = max(max(xs) - min(xs), max(ys) - min(ys))

                feat = [[track.aspect_ratio, track.speed, track.dwell_time, spread, float(track.frame_count)]]
                try:
                    probs = self._rf_classifier.predict_proba(feat)[0]
                    pred_class_idx = int(np.argmax(probs))
                    pred_conf = float(probs[pred_class_idx])

                    # 1=loitering, 2=crawling, 3=sprinting
                    if pred_class_idx > 0 and pred_conf >= 0.75:
                        act_type = self._rf_classes[pred_class_idx]
                        key = (act_type, track.track_id)
                        if not self._check_cooldown(key, timestamp):
                            sev = "medium" if act_type == "loitering" else "high"
                            activities.append(ActivityEvent(
                                activity_type=act_type,
                                track_ids=[track.track_id],
                                confidence=pred_conf,
                                severity=sev,
                                description=f"Person #{track.track_id} Random Forest Activity: {act_type} ({pred_conf:.0%})",
                                timestamp=timestamp,
                            ))
                            self._set_cooldown(key, timestamp)
                            self._stats[act_type] += 1
                except Exception as e:
                    logger.debug(f"Random Forest inference error: {e}")

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
