"""
IBVAP — Edge-to-Core Sync Agent
==================================
Batches and syncs events from the edge local buffer to the core API.
Bandwidth-aware: metadata + thumbnails first, clips later.
"""

import time
import json
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)


class SyncAgent:
    """
    Manages the edge-to-core sync process.
    Priorities: metadata first, thumbnails second, video clips last.
    """

    def __init__(
        self,
        core_api_url: str = "http://localhost:8000",
        sync_interval: int = 5,
        batch_size: int = 50,
        api_key: Optional[str] = None,
    ):
        import os
        self.core_api_url = core_api_url.rstrip("/")
        self.sync_interval = sync_interval
        self.batch_size = batch_size
        self.api_key = api_key or os.getenv("EDGE_API_KEY", "ibvap-edge-secret-key-2026")
        self._running = False
        self._sync_count = 0
        self._last_sync_time = 0.0
        self._last_error: Optional[str] = None

    async def sync_batch(self, local_store) -> dict:
        """
        Sync a batch of unsynced events to the core API.
        Returns sync result summary.
        """
        try:
            import httpx

            events = local_store.get_unsynced_events(limit=self.batch_size)
            alerts = local_store.get_unsynced_alerts(limit=self.batch_size)

            if not events and not alerts:
                return {"synced_events": 0, "synced_alerts": 0, "status": "nothing_to_sync"}

            payload = {
                "edge_id": "edge_01",
                "timestamp": time.time(),
                "events": [],
                "alerts": [],
            }

            # Prepare events
            for event in events:
                event_data = json.loads(event["data"]) if isinstance(event["data"], str) else event["data"]
                payload["events"].append({
                    "edge_event_id": event["id"],
                    "event_type": event["event_type"],
                    "camera_id": event["camera_id"],
                    "track_id": event.get("track_id"),
                    "confidence": event.get("confidence"),
                    "timestamp": event["timestamp"],
                    "data": event_data,
                    "thumbnail_path": event.get("thumbnail_path"),
                })

            # Prepare alerts
            for alert in alerts:
                alert_data = json.loads(alert["data"]) if isinstance(alert["data"], str) else alert["data"]
                payload["alerts"].append({
                    "edge_alert_id": alert["id"],
                    "event_id": alert.get("event_id"),
                    "severity": alert["severity"],
                    "alert_type": alert["alert_type"],
                    "message": alert.get("message"),
                    "data": alert_data,
                })

            # Send to core
            headers = {"X-Edge-API-Key": self.api_key}
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.core_api_url}/api/v1/edge/sync",
                    json=payload,
                    headers=headers,
                )

                if response.status_code == 200:
                    # Mark as synced
                    event_ids = [e["id"] for e in events]
                    alert_ids = [a["id"] for a in alerts]
                    local_store.mark_synced(event_ids=event_ids, alert_ids=alert_ids)

                    self._sync_count += 1
                    self._last_sync_time = time.time()
                    self._last_error = None

                    result = {
                        "synced_events": len(events),
                        "synced_alerts": len(alerts),
                        "status": "success",
                    }
                    logger.info(
                        f"Sync #{self._sync_count}: {result['synced_events']} events, "
                        f"{result['synced_alerts']} alerts"
                    )
                    return result
                else:
                    self._last_error = f"HTTP {response.status_code}: {response.text}"
                    logger.error(f"Sync failed: {self._last_error}")
                    return {"status": "error", "error": self._last_error}

        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"Sync error (will retry): {e}")
            return {"status": "error", "error": str(e)}

    async def run_loop(self, local_store):
        """Run the sync loop continuously."""
        self._running = True
        logger.info(
            f"Sync agent started — target: {self.core_api_url}, "
            f"interval: {self.sync_interval}s"
        )

        while self._running:
            await self.sync_batch(local_store)
            await asyncio.sleep(self.sync_interval)

    def stop(self):
        """Stop the sync loop."""
        self._running = False
        logger.info("Sync agent stopped")

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "core_api_url": self.core_api_url,
            "sync_count": self._sync_count,
            "last_sync_time": self._last_sync_time,
            "last_error": self._last_error,
        }
