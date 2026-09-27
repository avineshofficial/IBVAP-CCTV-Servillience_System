"""
IBVAP — Local Buffer Module
=============================
SQLite-based local event storage and video ring buffer for offline resilience.
"""

import json
import time
import sqlite3
import logging
from pathlib import Path
from typing import Optional
from dataclasses import asdict

logger = logging.getLogger(__name__)


class LocalStore:
    """
    Local SQLite buffer for edge events.
    Ensures all events are persisted locally before sync attempts.
    Implements store-and-forward pattern for offline resilience.
    """

    def __init__(self, db_path: str = "edge_buffer.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize()

    def _initialize(self):
        """Create database and tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                track_id INTEGER,
                confidence REAL,
                timestamp REAL NOT NULL,
                data TEXT NOT NULL,
                thumbnail_path TEXT,
                clip_path TEXT,
                synced INTEGER DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                severity TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT,
                data TEXT NOT NULL,
                synced INTEGER DEFAULT 0,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (event_id) REFERENCES events(id)
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_size INTEGER,
                status TEXT,
                error_message TEXT,
                synced_at REAL DEFAULT (strftime('%s', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_events_synced ON events(synced);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_alerts_synced ON alerts(synced);
        """)
        self._conn.commit()
        logger.info(f"Local store initialized at {self.db_path}")

    def store_event(
        self,
        event_type: str,
        camera_id: str,
        data: dict,
        track_id: int = None,
        confidence: float = None,
        timestamp: float = None,
        thumbnail_path: str = None,
        clip_path: str = None,
    ) -> int:
        """Store a detection/fence/activity event locally."""
        if timestamp is None:
            timestamp = time.time()

        cursor = self._conn.execute(
            """INSERT INTO events (event_type, camera_id, track_id, confidence,
               timestamp, data, thumbnail_path, clip_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_type, camera_id, track_id, confidence, timestamp,
             json.dumps(data, default=str), thumbnail_path, clip_path),
        )
        self._conn.commit()
        return cursor.lastrowid

    def store_alert(
        self,
        event_id: int,
        severity: str,
        alert_type: str,
        message: str,
        data: dict,
    ) -> int:
        """Store an alert linked to an event."""
        cursor = self._conn.execute(
            """INSERT INTO alerts (event_id, severity, alert_type, message, data)
               VALUES (?, ?, ?, ?, ?)""",
            (event_id, severity, alert_type, message, json.dumps(data, default=str)),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_unsynced_events(self, limit: int = 50) -> list[dict]:
        """Get events that haven't been synced to core yet."""
        if not self._conn:
            return []
        cursor = self._conn.execute(
            "SELECT * FROM events WHERE synced = 0 ORDER BY timestamp ASC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_unsynced_alerts(self, limit: int = 50) -> list[dict]:
        """Get alerts that haven't been synced to core yet."""
        if not self._conn:
            return []
        cursor = self._conn.execute(
            "SELECT * FROM alerts WHERE synced = 0 ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def mark_synced(self, event_ids: list[int] = None, alert_ids: list[int] = None):
        """Mark events/alerts as synced."""
        if not self._conn:
            return
        if event_ids:
            placeholders = ",".join("?" * len(event_ids))
            self._conn.execute(
                f"UPDATE events SET synced = 1 WHERE id IN ({placeholders})",
                event_ids,
            )
        if alert_ids:
            placeholders = ",".join("?" * len(alert_ids))
            self._conn.execute(
                f"UPDATE alerts SET synced = 1 WHERE id IN ({placeholders})",
                alert_ids,
            )
        self._conn.commit()

    def get_recent_events(self, camera_id: str = None, limit: int = 100) -> list[dict]:
        """Get recent events, optionally filtered by camera."""
        if camera_id:
            cursor = self._conn.execute(
                "SELECT * FROM events WHERE camera_id = ? ORDER BY timestamp DESC LIMIT ?",
                (camera_id, limit),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get buffer statistics."""
        total = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        unsynced = self._conn.execute("SELECT COUNT(*) FROM events WHERE synced = 0").fetchone()[0]
        total_alerts = self._conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        return {
            "total_events": total,
            "unsynced_events": unsynced,
            "total_alerts": total_alerts,
            "db_path": self.db_path,
        }

    def cleanup_old(self, hours: int = 72):
        """Delete events older than the specified hours."""
        cutoff = time.time() - (hours * 3600)
        self._conn.execute(
            "DELETE FROM events WHERE timestamp < ? AND synced = 1", (cutoff,)
        )
        self._conn.commit()
        logger.info(f"Cleaned up events older than {hours} hours")

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
