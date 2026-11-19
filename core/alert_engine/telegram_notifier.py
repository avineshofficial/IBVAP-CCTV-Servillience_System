"""
IBVAP — Telegram Bot API Notification Service
================================================
Sends EXACTLY ONE Telegram message per incident:
- Single sendVideo call with 8s H.264 MP4 clip + HTML caption
- NO separate sendLocation, sendMessage, or sendPhoto calls
- Thread-safe deduplication and 10s per-camera cooldown
"""

import os
import time
import logging
import asyncio
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx

from core.config import CoreConfig

logger = logging.getLogger(__name__)

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


class TelegramNotifier:
    """
    Non-blocking, fault-tolerant Telegram Bot API notification client.
    Sends EXACTLY ONE sendVideo per incident — no fallbacks.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        self.bot_token = (bot_token or CoreConfig.TELEGRAM_BOT_TOKEN or "").strip()
        self.chat_id = (chat_id or CoreConfig.TELEGRAM_CHAT_ID or "").strip()
        self.enabled = CoreConfig.TELEGRAM_ENABLED if enabled is None else enabled
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

        # Thread-safe deduplication
        self._lock = threading.Lock()
        self._sent_alert_ids: set = set()
        self._last_sent_by_camera: dict = {}
        self._cooldown_seconds = 10.0

    async def resolve_chat_id(self) -> Optional[str]:
        """Return the active chat_id, auto-discovering from getUpdates if needed."""
        if self.chat_id:
            return self.chat_id

        if not self.bot_token:
            logger.warning("[Telegram] Cannot resolve chat_id: TELEGRAM_BOT_TOKEN is not configured.")
            return None

        try:
            url = f"{self.api_base}/getUpdates"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("result", [])
                    if results:
                        latest = results[-1]
                        msg = latest.get("message") or latest.get("channel_post") or latest.get("edited_message")
                        if msg and "chat" in msg:
                            discovered_id = str(msg["chat"]["id"])
                            self.chat_id = discovered_id
                            logger.info(f"[Telegram] Auto-discovered TELEGRAM_CHAT_ID={discovered_id}")
                            return self.chat_id
        except Exception as e:
            logger.debug(f"[Telegram] getUpdates check error: {e}")

        return None

    def format_caption(
        self,
        alert_data: dict,
        severity: str,
        message: str = "",
        timestamp: Optional[float] = None,
    ) -> str:
        """Build structured HTML incident caption with GPS coordinates."""
        ts = timestamp or alert_data.get("timestamp") or time.time()
        dt_ist = datetime.fromtimestamp(ts, tz=IST)
        time_str = dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")

        zone_name = alert_data.get("zone_name") or alert_data.get("zone_id") or "Perimeter Floor Zone"
        alert_type = alert_data.get("alert_type") or alert_data.get("breach_type") or "fence_breach"
        camera_id = alert_data.get("camera_id") or alert_data.get("camera_uid") or "CAM-01"
        track_id = alert_data.get("track_id")
        track_str = f"#{track_id}" if track_id is not None else "N/A"
        obj_class = alert_data.get("object_class") or alert_data.get("class") or "person"
        activity = alert_data.get("activity") or alert_data.get("activity_type") or alert_data.get("breach_type") or "Perimeter Intrusion"

        conf_val = alert_data.get("confidence")
        if conf_val is not None:
            try:
                conf_str = f"{float(conf_val):.1%}"
            except Exception:
                conf_str = str(conf_val)
        else:
            conf_str = "89.0%"

        # GPS coordinates from alert data or config defaults
        lat = float(alert_data.get("latitude") or alert_data.get("lat") or getattr(CoreConfig, "DEFAULT_CAMERA_LAT", 9.9252))
        lng = float(alert_data.get("longitude") or alert_data.get("lng") or getattr(CoreConfig, "DEFAULT_CAMERA_LNG", 78.1198))
        sector = alert_data.get("bop_id") or "Border Sector Alpha"

        caption = (
            "\U0001f6a8 <b>[IBVAP ALERT] \u2014 PERIMETER INCIDENT DETECTED</b>\n\n"
            f"\U0001f4cd <b>Zone / Type:</b> {zone_name} ({alert_type})\n"
            f"\U0001f3c3 <b>Activity:</b> <code>{activity}</code>\n"
            f"\u26a0\ufe0f <b>Severity:</b> <b>{severity.upper()}</b> ({conf_str})\n"
            f"\U0001f4f9 <b>Camera:</b> <code>{camera_id}</code> ({sector})\n"
            f"\U0001f3af <b>Target:</b> Track {track_str} ({obj_class})\n"
            f"\U0001f552 <b>Time:</b> {time_str}\n"
            f"\U0001f310 <b>GPS:</b> <code>{lat:.6f}, {lng:.6f}</code>\n\n"
            f'\U0001f4cd <a href="https://www.google.com/maps?q={lat:.6f},{lng:.6f}">Open Live Location in Google Maps</a>'
        )

        return caption

    def _check_dedup(self, alert_id: str, camera_id: str) -> bool:
        """Thread-safe check: returns True if this alert should be sent."""
        with self._lock:
            if alert_id in self._sent_alert_ids:
                logger.debug(f"[Telegram] Dedup: alert_id={alert_id} already sent, skipping.")
                return False
            now = time.monotonic()
            last_sent = self._last_sent_by_camera.get(camera_id, 0.0)
            if now - last_sent < self._cooldown_seconds:
                logger.debug(f"[Telegram] Cooldown: camera={camera_id} sent {now - last_sent:.1f}s ago, skipping.")
                return False
            return True

    def _mark_sent(self, alert_id: str, camera_id: str):
        """Mark this alert as sent for dedup tracking."""
        with self._lock:
            self._sent_alert_ids.add(alert_id)
            self._last_sent_by_camera[camera_id] = time.monotonic()
            # Prune old alert IDs to prevent unbounded memory growth
            if len(self._sent_alert_ids) > 500:
                self._sent_alert_ids = set(list(self._sent_alert_ids)[-250:])

    async def send_alert_with_video(
        self,
        alert_id: str,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        clip_path: Optional[str] = None,
    ) -> dict:
        """
        Send EXACTLY ONE Telegram message: sendVideo with incident caption.
        NO fallbacks to sendMessage/sendPhoto/sendLocation.
        Only sends if the finalized MP4 clip exists and is valid.
        """
        if not self.enabled:
            return {"status": "disabled"}

        if not self.bot_token:
            logger.warning("[Telegram] Bot token not configured.")
            return {"status": "error", "message": "Missing TELEGRAM_BOT_TOKEN"}

        chat_id = await self.resolve_chat_id()
        if not chat_id:
            logger.warning("[Telegram] No chat_id configured. Send /start to your bot.")
            return {"status": "error", "message": "Missing TELEGRAM_CHAT_ID"}

        camera_id = alert_data.get("camera_id") or alert_data.get("camera_uid") or "unknown"

        # Thread-safe dedup + cooldown check
        if not self._check_dedup(alert_id, camera_id):
            return {"status": "skipped", "reason": "dedup_or_cooldown"}

        # Resolve and validate clip file
        resolved_clip = self._resolve_clip_path(clip_path)
        if not resolved_clip or not resolved_clip.exists():
            logger.warning(f"[Telegram] ABORT: clip not found at {clip_path}")
            return {"status": "error", "message": "Clip file not found"}

        file_size = resolved_clip.stat().st_size
        if file_size < 10_000:
            logger.warning(f"[Telegram] ABORT: clip too small ({file_size} bytes): {resolved_clip.name}")
            return {"status": "error", "message": f"Clip too small: {file_size} bytes"}

        caption = self.format_caption(alert_data, severity, message)

        # Send EXACTLY ONE sendVideo call
        upload_timeout = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)
        try:
            async with httpx.AsyncClient(timeout=upload_timeout) as client:
                logger.info(f"[Telegram] Sending 8s incident clip: {resolved_clip.name} ({file_size / 1024:.0f} KB)")
                with open(resolved_clip, "rb") as video_file:
                    files = {"video": (resolved_clip.name, video_file, "video/mp4")}
                    data = {
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "supports_streaming": "true",
                    }
                    resp = await client.post(f"{self.api_base}/sendVideo", data=data, files=files)

                    if resp.status_code == 200:
                        self._mark_sent(alert_id, camera_id)
                        logger.info(f"[Telegram] \u2705 Incident video sent: alert_id={alert_id} chat_id={chat_id}")
                        return {"status": "ok", "video_sent": True, "alert_id": alert_id}
                    else:
                        logger.warning(f"[Telegram] sendVideo HTTP {resp.status_code}: {resp.text[:200]}")
                        return {"status": "failed", "http_status": resp.status_code}
        except Exception as e:
            logger.error(f"[Telegram] sendVideo exception: {e}")
            return {"status": "error", "error": str(e)}

    def send_alert_with_video_sync(
        self,
        alert_id: str,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        clip_path: Optional[str] = None,
    ) -> dict:
        """Synchronous wrapper for ThreadPoolExecutor dispatch."""
        try:
            return asyncio.run(self.send_alert_with_video(
                alert_id=alert_id,
                alert_data=alert_data,
                severity=severity,
                message=message,
                clip_path=clip_path,
            ))
        except Exception as e:
            logger.error(f"[Telegram] Sync dispatch error: {e}")
            return {"status": "error", "error": str(e)}

    def _resolve_clip_path(self, clip_ref: Optional[str]) -> Optional[Path]:
        """Locate the MP4 incident video clip on disk."""
        if not clip_ref:
            return None

        p = Path(clip_ref)
        if p.is_file() and p.suffix.lower() == ".mp4":
            return p

        clean_name = p.name
        candidates = [
            CoreConfig.MEDIA_DIR / "clips" / clean_name,
            CoreConfig.MEDIA_DIR / clean_name,
            Path("core/media/clips") / clean_name,
            Path("core/media") / clean_name,
        ]
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() == ".mp4":
                return candidate

        return None


# Singleton instance
_telegram_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> TelegramNotifier:
    """Get or instantiate global TelegramNotifier singleton."""
    global _telegram_notifier
    if _telegram_notifier is None:
        _telegram_notifier = TelegramNotifier()
    return _telegram_notifier
