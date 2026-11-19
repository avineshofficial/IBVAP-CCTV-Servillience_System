"""
IBVAP — Telegram Bot API Notification Service
================================================
Sends EXACTLY ONE Telegram alert per incident:
- If faces captured: sendMediaGroup (video + face photos as album)
- If no faces: single sendVideo with HTML caption
- ALL incident details + real-time GPS in the caption
- Thread-safe deduplication and 10s per-camera cooldown
- ZERO hardcoded coordinates — uses LiveLocationService
"""

import os
import json
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
    Sends ONE alert per incident — video + face crops as media group.
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
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api_base}/getUpdates")
                if resp.status_code == 200:
                    results = resp.json().get("result", [])
                    if results:
                        latest = results[-1]
                        msg = latest.get("message") or latest.get("channel_post") or latest.get("edited_message")
                        if msg and "chat" in msg:
                            self.chat_id = str(msg["chat"]["id"])
                            logger.info(f"[Telegram] Auto-discovered chat_id={self.chat_id}")
                            return self.chat_id
        except Exception as e:
            logger.debug(f"[Telegram] getUpdates error: {e}")
        return None

    def _get_live_location(self) -> dict:
        """Get real-time GPS coordinates from LocationService (never hardcoded)."""
        try:
            from core.alert_engine.location_service import get_location_service
            return get_location_service().get_live_location()
        except Exception as e:
            logger.debug(f"[Telegram] Location service error: {e}")
            return {"lat": None, "lng": None, "source": "unavailable", "label": "Location Unavailable"}

    def format_caption(
        self,
        alert_data: dict,
        severity: str,
        message: str = "",
        timestamp: Optional[float] = None,
        face_count: int = 0,
        face_status: str = "pending",
    ) -> str:
        """Build structured HTML incident caption with real-time data."""
        ts = timestamp or alert_data.get("timestamp") or time.time()
        dt_ist = datetime.fromtimestamp(ts, tz=IST)
        time_str = dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")

        zone_name = alert_data.get("zone_name") or alert_data.get("zone_id") or "Perimeter Zone"
        breach_type = alert_data.get("breach_type") or alert_data.get("alert_type") or "fence_breach"
        camera_id = alert_data.get("camera_id") or alert_data.get("camera_uid") or "CAM-01"

        # Person count and track IDs (real-time)
        person_count = alert_data.get("person_count", 1)
        active_track_ids = alert_data.get("active_track_ids", [])
        track_id = alert_data.get("track_id")
        if active_track_ids:
            tracks_str = ", ".join(f"#{t}" for t in active_track_ids)
        elif track_id is not None:
            tracks_str = f"#{track_id}"
        else:
            tracks_str = "N/A"
        person_label = f"{person_count} Person{'s' if person_count > 1 else ''}"

        obj_class = alert_data.get("object_class") or "person"
        activity = alert_data.get("activity") or breach_type or "Perimeter Intrusion"

        # Dynamic severity (real-time calculated)
        severity_pct = alert_data.get("severity_pct", "")
        severity_score = alert_data.get("severity_score")
        if severity_pct:
            sev_display = f"{severity.upper()} ({severity_pct})"
        elif severity_score is not None:
            sev_display = f"{severity.upper()} ({severity_score:.1f}%)"
        else:
            conf_val = alert_data.get("confidence")
            if conf_val is not None:
                try:
                    sev_display = f"{severity.upper()} ({float(conf_val):.1%})"
                except Exception:
                    sev_display = severity.upper()
            else:
                sev_display = severity.upper()

        sector = alert_data.get("bop_id") or "Border Sector Alpha"

        # Real-time GPS from location service
        location = self._get_live_location()
        lat = location.get("lat")
        lng = location.get("lng")
        loc_label = location.get("label", "")

        if lat is not None and lng is not None:
            gps_line = f"\U0001f310 <b>GPS:</b> <code>{lat:.6f}, {lng:.6f}</code> ({loc_label})"
            maps_line = f'\U0001f4cd <a href="https://www.google.com/maps?q={lat:.6f},{lng:.6f}">Open Real-Time Location in Google Maps</a>'
        else:
            gps_line = "\U0001f310 <b>GPS:</b> Real-Time Location Unavailable (Offline)"
            maps_line = ""

        # Face capture status
        if face_count > 0:
            face_line = f"\U0001f464 <b>Face Capture:</b> {face_count} Face{'s' if face_count > 1 else ''} Captured (Linked to Incident)"
        elif face_status == "unavailable":
            face_line = "\U0001f464 <b>Face Capture:</b> Unavailable"
        else:
            face_line = "\U0001f464 <b>Face Capture:</b> Processing..."

        caption = (
            "\U0001f6a8 <b>[IBVAP ALERT] \u2014 PERIMETER INCIDENT DETECTED</b>\n\n"
            f"\U0001f4cd <b>Zone / Type:</b> {zone_name} ({breach_type})\n"
            f"\U0001f3c3 <b>Activity:</b> <code>{activity}</code>\n"
            f"\u26a0\ufe0f <b>Severity:</b> <b>{sev_display}</b>\n"
            f"\U0001f4f9 <b>Camera:</b> <code>{camera_id}</code> ({sector})\n"
            f"\U0001f3af <b>Target:</b> {person_label} in Incident Area (Track{'s' if person_count > 1 else ''} {tracks_str})\n"
            f"\U0001f552 <b>Time:</b> {time_str}\n"
            f"{gps_line}\n"
            f"{face_line}\n"
        )
        if maps_line:
            caption += f"\n{maps_line}"

        return caption

    def _check_dedup(self, alert_id: str, camera_id: str) -> bool:
        """Thread-safe check: returns True if this alert should be sent."""
        with self._lock:
            if alert_id in self._sent_alert_ids:
                return False
            now = time.monotonic()
            last_sent = self._last_sent_by_camera.get(camera_id, 0.0)
            if now - last_sent < self._cooldown_seconds:
                return False
            return True

    def _mark_sent(self, alert_id: str, camera_id: str):
        """Mark this alert as sent for dedup tracking."""
        with self._lock:
            self._sent_alert_ids.add(alert_id)
            self._last_sent_by_camera[camera_id] = time.monotonic()
            if len(self._sent_alert_ids) > 500:
                self._sent_alert_ids = set(list(self._sent_alert_ids)[-250:])

    async def send_alert_with_video(
        self,
        alert_id: str,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        clip_path: Optional[str] = None,
        face_image_paths: Optional[list] = None,
    ) -> dict:
        """
        Send Telegram alert: video + face crops as media group, or single sendVideo.
        face_image_paths: list of absolute file paths to face crop JPEGs.
        """
        if not self.enabled:
            return {"status": "disabled"}
        if not self.bot_token:
            return {"status": "error", "message": "Missing TELEGRAM_BOT_TOKEN"}

        chat_id = await self.resolve_chat_id()
        if not chat_id:
            logger.warning("[Telegram] No chat_id configured.")
            return {"status": "error", "message": "Missing TELEGRAM_CHAT_ID"}

        camera_id = alert_data.get("camera_id") or alert_data.get("camera_uid") or "unknown"
        if not self._check_dedup(alert_id, camera_id):
            return {"status": "skipped", "reason": "dedup_or_cooldown"}

        # Validate clip
        resolved_clip = self._resolve_clip_path(clip_path)
        if not resolved_clip or not resolved_clip.exists() or resolved_clip.stat().st_size < 10_000:
            logger.warning(f"[Telegram] ABORT: clip invalid at {clip_path}")
            return {"status": "error", "message": "Clip file not found or too small"}

        # Resolve valid face images
        valid_faces = []
        if face_image_paths:
            for fp in face_image_paths:
                p = Path(fp)
                if p.exists() and p.stat().st_size > 500:
                    valid_faces.append(p)

        face_count = len(valid_faces)
        face_status = "captured" if face_count > 0 else "unavailable"
        caption = self.format_caption(
            alert_data, severity, message,
            face_count=face_count, face_status=face_status,
        )

        upload_timeout = httpx.Timeout(connect=15.0, read=90.0, write=90.0, pool=15.0)
        try:
            async with httpx.AsyncClient(timeout=upload_timeout) as client:
                file_size_kb = resolved_clip.stat().st_size / 1024
                logger.info(f"[Telegram] Sending alert: {resolved_clip.name} ({file_size_kb:.0f}KB) + {face_count} face(s)")

                if valid_faces:
                    # Use sendMediaGroup: video + face photos as album
                    return await self._send_media_group(
                        client, chat_id, resolved_clip, valid_faces, caption, alert_id, camera_id
                    )
                else:
                    # Single sendVideo
                    return await self._send_video_only(
                        client, chat_id, resolved_clip, caption, alert_id, camera_id
                    )
        except Exception as e:
            logger.error(f"[Telegram] Send exception: {e}")
            return {"status": "error", "error": str(e)}

    async def _send_video_only(self, client, chat_id, clip_path, caption, alert_id, camera_id):
        """Send a single sendVideo message."""
        with open(clip_path, "rb") as vf:
            files = {"video": (clip_path.name, vf, "video/mp4")}
            data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
                "supports_streaming": "true",
            }
            resp = await client.post(f"{self.api_base}/sendVideo", data=data, files=files)
            if resp.status_code == 200:
                self._mark_sent(alert_id, camera_id)
                logger.info(f"[Telegram] \u2705 Video sent: {alert_id}")
                return {"status": "ok", "video_sent": True, "alert_id": alert_id}
            else:
                logger.warning(f"[Telegram] sendVideo HTTP {resp.status_code}: {resp.text[:200]}")
                return {"status": "failed", "http_status": resp.status_code}

    async def _send_media_group(self, client, chat_id, clip_path, face_paths, caption, alert_id, camera_id):
        """Send video + face images as a Telegram media group (album)."""
        # Build multipart: video first (with caption), then face photos
        media_items = []
        files_dict = {}

        # Video entry
        video_attach_key = "video_file"
        media_items.append({
            "type": "video",
            "media": f"attach://{video_attach_key}",
            "caption": caption,
            "parse_mode": "HTML",
            "supports_streaming": True,
        })

        # Face photo entries
        for i, fp in enumerate(face_paths):
            attach_key = f"face_{i}"
            media_items.append({
                "type": "photo",
                "media": f"attach://{attach_key}",
            })

        # Open all files for multipart upload
        opened_files = []
        try:
            vf = open(clip_path, "rb")
            opened_files.append(vf)
            files_dict[video_attach_key] = (clip_path.name, vf, "video/mp4")

            for i, fp in enumerate(face_paths):
                ff = open(fp, "rb")
                opened_files.append(ff)
                files_dict[f"face_{i}"] = (fp.name, ff, "image/jpeg")

            data = {
                "chat_id": chat_id,
                "media": json.dumps(media_items),
            }
            resp = await client.post(f"{self.api_base}/sendMediaGroup", data=data, files=files_dict)

            if resp.status_code == 200:
                self._mark_sent(alert_id, camera_id)
                logger.info(f"[Telegram] \u2705 Media group sent: {alert_id} (video + {len(face_paths)} faces)")
                return {"status": "ok", "video_sent": True, "faces_sent": len(face_paths), "alert_id": alert_id}
            else:
                logger.warning(f"[Telegram] sendMediaGroup HTTP {resp.status_code}: {resp.text[:300]}")
                # Fallback to sendVideo only
                logger.info("[Telegram] Falling back to sendVideo only...")
                for f in opened_files:
                    f.close()
                opened_files.clear()
                return await self._send_video_only(client, chat_id, clip_path, caption, alert_id, camera_id)
        finally:
            for f in opened_files:
                try:
                    f.close()
                except Exception:
                    pass

    def send_alert_with_video_sync(
        self,
        alert_id: str,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        clip_path: Optional[str] = None,
        face_image_paths: Optional[list] = None,
    ) -> dict:
        """Synchronous wrapper for ThreadPoolExecutor dispatch."""
        try:
            return asyncio.run(self.send_alert_with_video(
                alert_id=alert_id,
                alert_data=alert_data,
                severity=severity,
                message=message,
                clip_path=clip_path,
                face_image_paths=face_image_paths,
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
        for candidate in [
            CoreConfig.MEDIA_DIR / "clips" / clean_name,
            CoreConfig.MEDIA_DIR / clean_name,
            Path("core/media/clips") / clean_name,
        ]:
            if candidate.is_file() and candidate.suffix.lower() == ".mp4":
                return candidate
        return None


# Singleton
_telegram_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> TelegramNotifier:
    """Get or instantiate global TelegramNotifier singleton."""
    global _telegram_notifier
    if _telegram_notifier is None:
        _telegram_notifier = TelegramNotifier()
    return _telegram_notifier
