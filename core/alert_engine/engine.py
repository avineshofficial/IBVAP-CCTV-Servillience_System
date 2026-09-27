"""
IBVAP — Alert Engine
======================
Confidence gating, deduplication, and severity assignment.
Filters raw events into actionable alerts.
"""

import time
import logging
from typing import Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class AlertEngine:
    """
    Alert engine with confidence gating, dedup, and severity assignment.
    Prevents alert fatigue by filtering low-confidence and duplicate alerts.
    """

    def __init__(self):
        # Confidence thresholds per alert type
        self._confidence_gates = {
            "fence_breach": 0.35,
            "face_match": 0.70,
            "plate_match": 0.60,
            "suspicious_activity": 0.50,
            "night_motion": 0.30,
            "default": 0.40,
        }

        # Severity escalation rules
        self._severity_rules = {
            "fence_breach": {
                "entered_exclusion": "critical",
                "crossed_entered": "high",
                "crossed_exited": "medium",
                "dwelling": "medium",
                "wrong_direction": "high",
                "default": "medium",
            },
            "face_match": {"default": "critical"},
            "plate_match": {"default": "high"},
            "suspicious_activity": {
                "loitering": "medium",
                "crawling": "high",
                "sprinting": "high",
                "group_forming": "high",
                "default": "medium",
            },
            "night_motion": {"default": "low"},
        }

        # Dedup window: (alert_type, key) -> last_alert_time
        self._dedup_window: dict[tuple, float] = {}
        self._dedup_seconds = 10.0

        # Stats
        self._stats = {
            "total_evaluated": 0,
            "total_passed": 0,
            "total_deduplicated": 0,
            "total_low_confidence": 0,
        }

    def evaluate(
        self,
        alert_type: str,
        severity: str,
        data: dict,
        confidence: float = None,
        timestamp: float = None,
    ) -> Tuple[bool, str]:
        """
        Evaluate whether an alert should be generated.

        Returns:
            (should_alert, final_severity)
        """
        if timestamp is None:
            timestamp = time.time()

        self._stats["total_evaluated"] += 1

        # Confidence gating
        if confidence is not None:
            threshold = self._confidence_gates.get(
                alert_type, self._confidence_gates["default"]
            )
            if confidence < threshold:
                self._stats["total_low_confidence"] += 1
                return (False, severity)

        # Dedup check
        dedup_key = self._build_dedup_key(alert_type, data)
        last_time = self._dedup_window.get(dedup_key, 0)
        if timestamp - last_time < self._dedup_seconds:
            self._stats["total_deduplicated"] += 1
            return (False, severity)

        # Update dedup window
        self._dedup_window[dedup_key] = timestamp

        # Severity assignment
        final_severity = self._assign_severity(alert_type, data, severity)

        self._stats["total_passed"] += 1
        return (True, final_severity)

    def _build_dedup_key(self, alert_type: str, data: dict) -> tuple:
        """Build a key for deduplication."""
        track_id = data.get("track_id", "none")
        zone_id = data.get("zone_id", "none")
        breach_type = data.get("breach_type", "none")
        return (alert_type, str(track_id), str(zone_id), str(breach_type))

    def _assign_severity(self, alert_type: str, data: dict, default: str) -> str:
        """Assign severity based on rules."""
        rules = self._severity_rules.get(alert_type)
        if rules is None:
            return default

        # Check for specific sub-type severity
        breach_type = data.get("breach_type", "")
        activity_type = data.get("activity_type", "")
        sub_type = breach_type or activity_type

        severity = rules.get(sub_type, rules.get("default", default))

        # Escalation: person at night in exclusion zone → critical
        object_class = data.get("object_class", "")
        is_night = data.get("enhanced", False)
        if object_class == "person" and is_night and alert_type == "fence_breach":
            severity = "critical"

        return severity

    def cleanup_dedup_window(self, older_than: float = 60.0):
        """Remove old dedup entries."""
        cutoff = time.time() - older_than
        self._dedup_window = {
            k: v for k, v in self._dedup_window.items() if v > cutoff
        }

    @property
    def stats(self) -> dict:
        return self._stats.copy()
