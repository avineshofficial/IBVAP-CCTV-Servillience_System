"""
IBVAP — Telegram Bot API Notification Service
================================================
Sends rich-media mobile notifications on security alerts:
- 8-second MP4 incident video clip (H.264 / streaming playable)
- Formatted HTML incident details with activity classification, target tracking, and timestamps
- Interactive Live GPS Location pin (sendLocation) with Google Maps navigation link
- Automatic chat_id discovery from getUpdates if not yet specified in .env
"""

import os
import time
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import httpx

from core.config import CoreConfig

logger = logging.getLogger(__name__)

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


class TelegramNotifier:
    """
    Non-blocking, fault-tolerant Telegram Bot API notification client.
    Dispatches 8s incident video clips, alert captions, and GPS location pins.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        default_lat: Optional[float] = None,
        default_lng: Optional[float] = None,
    ):
        self.bot_token = (bot_token or CoreConfig.TELEGRAM_BOT_TOKEN or "").strip()
        self.chat_id = (chat_id or CoreConfig.TELEGRAM_CHAT_ID or "").strip()
        self.enabled = CoreConfig.TELEGRAM_ENABLED if enabled is None else enabled
        self.default_lat = CoreConfig.DEFAULT_CAMERA_LAT if default_lat is None else default_lat
        self.default_lng = CoreConfig.DEFAULT_CAMERA_LNG if default_lng is None else default_lng
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

        # Dedup cooldown tracking to avoid spamming the user's phone
        self._last_sent_time: dict[str, float] = {}

    async def resolve_chat_id(self) -> Optional[str]:
        """
        Return the active chat_id.
        If empty, dynamically queries getUpdates to discover the chat_id
        from the most recent user message/start command to the bot.
        """
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
                        # Pick the latest message's chat ID
                        latest = results[-1]
                        msg = latest.get("message") or latest.get("channel_post") or latest.get("edited_message")
                        if msg and "chat" in msg:
                            discovered_id = str(msg["chat"]["id"])
                            self.chat_id = discovered_id
                            logger.info(f"[Telegram] Auto-discovered TELEGRAM_CHAT_ID={discovered_id} from bot updates.")
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
    ) -> Tuple[str, float, float]:
        """
        Build structured HTML incident text and extract coordinates.
        """
        ts = timestamp or alert_data.get("timestamp") or time.time()
        dt_ist = datetime.fromtimestamp(ts, tz=IST)
        time_str = dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")

        zone_name = alert_data.get("zone_name") or alert_data.get("zone_id") or "Perimeter Floor Zone"
        alert_type = alert_data.get("alert_type") or alert_data.get("breach_type") or "fence_breach"
        camera_id = alert_data.get("camera_id") or alert_data.get("camera_uid") or "CAM-01"
        track_id = alert_data.get("track_id")
        track_str = f"#{track_id}" if track_id is not None else "N/A"
        obj_class = alert_data.get("object_class") or alert_data.get("class") or "person"

        # Classification / Activity
        activity = alert_data.get("activity") or alert_data.get("activity_type") or alert_data.get("breach_type") or "Perimeter Intrusion"

        # Confidence
        conf_val = alert_data.get("confidence")
        if conf_val is not None:
            try:
                conf_str = f"{float(conf_val):.1%}"
            except Exception:
                conf_str = str(conf_val)
        else:
            conf_str = "89.0%"

        # Coordinates
        lat = float(alert_data.get("latitude") or alert_data.get("lat") or self.default_lat)
        lng = float(alert_data.get("longitude") or alert_data.get("lng") or self.default_lng)

        sector = alert_data.get("bop_id") or "Border Sector Alpha"

        caption = (
            f"🚨 <b>[IBVAP ALERT] — PERIMETER INCIDENT DETECTED</b>\n\n"
            f"📍 <b>Zone / Type:</b> {zone_name} ({alert_type})\n"
            f"🏃 <b>Activity:</b> <code>{activity}</code>\n"
            f"⚠️ <b>Severity:</b> <b>{severity.upper()}</b> ({conf_str})\n"
            f"📹 <b>Camera:</b> <code>{camera_id}</code> ({sector})\n"
            f"🎯 <b>Target:</b> Track {track_str} ({obj_class})\n"
            f"🕒 <b>Time:</b> {time_str}\n"
            f"🌐 <b>GPS Coordinates:</b> <code>{lat:.6f}, {lng:.6f}</code>\n\n"
            f'📍 <a href="https://www.google.com/maps?q={lat:.6f},{lng:.6f}">Open Live Location in Google Maps</a>'
        )

        return caption, lat, lng

    def _resolve_clip_path(self, clip_ref: Optional[str]) -> Optional[Path]:
        """Locate the MP4 incident video clip on disk."""
        if not clip_ref:
            return None

        p = Path(clip_ref)
        if p.is_file() and p.exists() and p.suffix.lower() == ".mp4":
            return p

        clean_name = p.name
        candidates = [
            CoreConfig.MEDIA_DIR / "clips" / clean_name,
            CoreConfig.MEDIA_DIR / clean_name,
            Path("core/media/clips") / clean_name,
            Path("core/media") / clean_name,
        ]
        for candidate in candidates:
            if candidate.is_file() and candidate.exists() and candidate.suffix.lower() == ".mp4":
                return candidate

        return None

    def _resolve_thumbnail_path(self, thumb_ref: Optional[str]) -> Optional[Path]:
        """Locate thumbnail image on disk."""
        if not thumb_ref:
            return None

        p = Path(thumb_ref)
        if p.is_file() and p.exists():
            return p

        clean_name = p.name
        candidates = [
            CoreConfig.MEDIA_DIR / "thumbnails" / clean_name,
            CoreConfig.MEDIA_DIR / clean_name,
            Path("core/media/thumbnails") / clean_name,
            Path("core/media") / clean_name,
        ]
        for candidate in candidates:
            if candidate.is_file() and candidate.exists():
                return candidate

        return None

    async def send_incident_alert(
        self,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        clip_path: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        wait_for_clip_seconds: float = 6.0,
    ) -> dict:
        """
        Send a complete rich mobile incident notification:
        1. 8-second MP4 video clip + structured HTML caption
        2. Live GPS location pin (sendLocation)

        Non-blocking, graceful fallback to photo/message if video is unavailable.
        """
        if not self.enabled:
            return {"status": "disabled", "message": "Telegram notifications disabled in config."}

        if not self.bot_token:
            logger.warning("[Telegram] Bot token not configured. Set TELEGRAM_BOT_TOKEN in .env.")
            return {"status": "error", "message": "Missing TELEGRAM_BOT_TOKEN"}

        chat_id = await self.resolve_chat_id()
        if not chat_id:
            logger.warning(
                "[Telegram] ⚠️ TELEGRAM_CHAT_ID is not configured and no messages received yet. "
                "👉 Please open t.me/SecureZone_Alert_NotifyBot on your phone, send /start, "
                "or set TELEGRAM_CHAT_ID in .env."
            )
            return {"status": "error", "message": "Missing TELEGRAM_CHAT_ID"}

        caption, lat, lng = self.format_caption(alert_data, severity, message)

        # Locate clip file, waiting briefly if still encoding in background
        resolved_clip = self._resolve_clip_path(clip_path or alert_data.get("clip_url") or alert_data.get("clip_path"))
        if not resolved_clip and wait_for_clip_seconds > 0:
            target_name = Path(clip_path or alert_data.get("clip_url") or "").name
            if target_name:
                wait_deadline = time.time() + wait_for_clip_seconds
                while time.time() < wait_deadline:
                    await asyncio.sleep(0.5)
                    c = self._resolve_clip_path(target_name)
                    if c and c.stat().st_size > 10000:
                        resolved_clip = c
                        break

        # Fallback thumbnail
        resolved_thumb = self._resolve_thumbnail_path(thumbnail_path or alert_data.get("thumbnail_path"))

        result = {
            "status": "pending",
            "chat_id": chat_id,
            "video_sent": False,
            "location_sent": False,
        }

        upload_timeout = httpx.Timeout(connect=20.0, read=90.0, write=90.0, pool=20.0)
        async with httpx.AsyncClient(timeout=upload_timeout) as client:
            media_sent = False

            # ── 1. Try sending 8-Second Incident Video Clip via sendVideo ──
            if resolved_clip and resolved_clip.exists() and resolved_clip.stat().st_size > 1000:
                try:
                    logger.info(f"[Telegram] Sending 8-second incident clip: {resolved_clip.name} ({resolved_clip.stat().st_size / 1024:.0f} KB)")
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
                            logger.info(f"[Telegram] ✅ 8s incident video clip sent successfully to chat_id={chat_id}")
                            media_sent = True
                            result["video_sent"] = True
                        else:
                            logger.warning(f"[Telegram] sendVideo returned HTTP {resp.status_code}: {resp.text}")
                except Exception as e_vid:
                    logger.warning(f"[Telegram] sendVideo exception: {e_vid}")

            # ── 2. Fallback to sendPhoto (Thumbnail) if Video Failed/Unavailable ──
            if not media_sent and resolved_thumb and resolved_thumb.exists():
                try:
                    logger.info(f"[Telegram] Falling back to incident thumbnail: {resolved_thumb.name}")
                    with open(resolved_thumb, "rb") as photo_file:
                        files = {"photo": (resolved_thumb.name, photo_file, "image/jpeg")}
                        data = {
                            "chat_id": chat_id,
                            "caption": caption,
                            "parse_mode": "HTML",
                        }
                        resp = await client.post(f"{self.api_base}/sendPhoto", data=data, files=files)
                        if resp.status_code == 200:
                            logger.info(f"[Telegram] ✅ Incident photo sent successfully to chat_id={chat_id}")
                            media_sent = True
                        else:
                            logger.warning(f"[Telegram] sendPhoto returned HTTP {resp.status_code}: {resp.text}")
                except Exception as e_photo:
                    logger.warning(f"[Telegram] sendPhoto exception: {e_photo}")

            # ── 3. Fallback to sendMessage (Text Caption) if No Media Available ──
            if not media_sent:
                try:
                    data = {
                        "chat_id": chat_id,
                        "text": caption,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": "false",
                    }
                    resp = await client.post(f"{self.api_base}/sendMessage", data=data)
                    if resp.status_code == 200:
                        logger.info(f"[Telegram] ✅ Incident text alert sent successfully to chat_id={chat_id}")
                        media_sent = True
                    else:
                        logger.warning(f"[Telegram] sendMessage returned HTTP {resp.status_code}: {resp.text}")
                except Exception as e_msg:
                    logger.error(f"[Telegram] sendMessage failed: {e_msg}")

            # ── 4. Send Interactive Live Location Map Pin via sendLocation ──
            try:
                loc_data = {
                    "chat_id": chat_id,
                    "latitude": lat,
                    "longitude": lng,
                }
                resp_loc = await client.post(f"{self.api_base}/sendLocation", data=loc_data)
                if resp_loc.status_code == 200:
                    logger.info(f"[Telegram] ✅ Interactive GPS Location pin ({lat:.4f}, {lng:.4f}) sent successfully.")
                    result["location_sent"] = True
                else:
                    logger.warning(f"[Telegram] sendLocation returned HTTP {resp_loc.status_code}: {resp_loc.text}")
            except Exception as e_loc:
                logger.warning(f"[Telegram] sendLocation exception: {e_loc}")

            result["status"] = "ok" if media_sent else "failed"
            return result

    def send_incident_alert_sync(
        self,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        clip_path: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        wait_for_clip_seconds: float = 15.0,
    ) -> dict:
        """Synchronous wrapper for execution on Edge node ThreadPoolExecutor."""
        try:
            return asyncio.run(self.send_incident_alert(
                alert_data=alert_data,
                severity=severity,
                message=message,
                clip_path=clip_path,
                thumbnail_path=thumbnail_path,
                wait_for_clip_seconds=wait_for_clip_seconds,
            ))
        except Exception as e:
            logger.error(f"[Telegram] Synchronous alert dispatch error: {e}")
            return {"status": "error", "error": str(e)}

    async def send_instant_alert(
        self,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        thumbnail_path: Optional[str] = None,
    ) -> dict:
        """
        Send an immediate real-time mobile alert notification (zero latency):
        1. Instant photo snapshot with formatted incident details
        2. Live GPS location pin (sendLocation)
        """
        if not self.enabled:
            return {"status": "disabled", "message": "Telegram notifications disabled in config."}

        if not self.bot_token:
            logger.warning("[Telegram] Bot token not configured. Set TELEGRAM_BOT_TOKEN in .env.")
            return {"status": "error", "message": "Missing TELEGRAM_BOT_TOKEN"}

        chat_id = await self.resolve_chat_id()
        if not chat_id:
            logger.warning("[Telegram] Cannot send alert: chat_id could not be resolved.")
            return {"status": "error", "message": "Missing TELEGRAM_CHAT_ID"}

        caption, lat, lng = self.format_caption(alert_data, severity, message)

        # Fast non-blocking thumbnail check (no sleep waiting)
        resolved_thumb = None
        target_thumb = thumbnail_path or alert_data.get("thumbnail_path")
        if target_thumb:
            resolved_thumb = self._resolve_thumbnail_path(target_thumb)
            if resolved_thumb and not (resolved_thumb.exists() and resolved_thumb.stat().st_size > 500):
                resolved_thumb = None

        result = {
            "status": "pending",
            "chat_id": chat_id,
            "photo_sent": False,
            "location_sent": False,
        }

        upload_timeout = httpx.Timeout(connect=10.0, read=15.0, write=15.0, pool=10.0)
        async with httpx.AsyncClient(timeout=upload_timeout) as client:
            media_sent = False
            # 1. Send snapshot photo if already written to disk
            if resolved_thumb and resolved_thumb.exists():
                try:
                    with open(resolved_thumb, "rb") as photo_file:
                        files = {"photo": (resolved_thumb.name, photo_file, "image/jpeg")}
                        data = {
                            "chat_id": chat_id,
                            "caption": caption,
                            "parse_mode": "HTML",
                        }
                        resp = await client.post(f"{self.api_base}/sendPhoto", data=data, files=files)
                        if resp.status_code == 200:
                            logger.info(f"[Telegram] ✅ Instant incident photo sent to chat_id={chat_id}")
                            media_sent = True
                            result["photo_sent"] = True
                        else:
                            logger.warning(f"[Telegram] sendPhoto returned HTTP {resp.status_code}: {resp.text}")
                except Exception as e_photo:
                    logger.warning(f"[Telegram] sendPhoto exception: {e_photo}")

            # 2. Fast parallel dispatch: Incident Details Text Alert + Interactive GPS pin in parallel!
            loc_data = {"chat_id": chat_id, "latitude": lat, "longitude": lng}
            if not media_sent:
                try:
                    msg_data = {
                        "chat_id": chat_id,
                        "text": caption,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": "false",
                    }
                    req_msg = client.post(f"{self.api_base}/sendMessage", data=msg_data)
                    req_loc = client.post(f"{self.api_base}/sendLocation", data=loc_data)
                    resp_msg, resp_loc = await asyncio.gather(req_msg, req_loc, return_exceptions=True)

                    if not isinstance(resp_msg, Exception) and resp_msg.status_code == 200:
                        logger.info(f"[Telegram] ✅ Instant incident details sent to chat_id={chat_id}")
                        media_sent = True
                    if not isinstance(resp_loc, Exception) and resp_loc.status_code == 200:
                        logger.info(f"[Telegram] ✅ Interactive GPS pin ({lat:.4f}, {lng:.4f}) sent successfully.")
                        result["location_sent"] = True
                except Exception as e_fast:
                    logger.error(f"[Telegram] Fast dispatch error: {e_fast}")
            else:
                # Photo was sent, send location pin
                try:
                    resp_loc = await client.post(f"{self.api_base}/sendLocation", data=loc_data)
                    if resp_loc.status_code == 200:
                        logger.info(f"[Telegram] ✅ Interactive GPS pin ({lat:.4f}, {lng:.4f}) sent successfully.")
                        result["location_sent"] = True
                except Exception as e_loc:
                    logger.warning(f"[Telegram] sendLocation exception: {e_loc}")

            result["status"] = "ok" if media_sent else "failed"
            return result

    def send_instant_alert_sync(
        self,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
        thumbnail_path: Optional[str] = None,
    ) -> dict:
        """Synchronous wrapper for instant alert dispatch on ThreadPoolExecutor."""
        try:
            return asyncio.run(self.send_instant_alert(
                alert_data=alert_data,
                severity=severity,
                message=message,
                thumbnail_path=thumbnail_path,
            ))
        except Exception as e:
            logger.error(f"[Telegram] Instant alert dispatch error: {e}")
            return {"status": "error", "error": str(e)}

    async def send_video_evidence(
        self,
        video_path: str,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
    ) -> dict:
        """
        Send finalized 8-second MP4 incident video clip to Telegram.
        """
        if not self.enabled:
            return {"status": "disabled", "message": "Telegram notifications disabled in config."}

        chat_id = await self.resolve_chat_id()
        if not chat_id:
            return {"status": "error", "message": "Missing TELEGRAM_CHAT_ID"}

        resolved_clip = self._resolve_clip_path(video_path)
        if not resolved_clip or not resolved_clip.exists():
            logger.warning(f"[Telegram] Cannot send video: file not found at {video_path}")
            return {"status": "error", "message": f"Clip not found: {video_path}"}

        caption, lat, lng = self.format_caption(alert_data, severity, message)
        video_caption = caption

        upload_timeout = httpx.Timeout(connect=20.0, read=90.0, write=90.0, pool=20.0)
        async with httpx.AsyncClient(timeout=upload_timeout) as client:
            try:
                logger.info(f"[Telegram] Uploading 8s video evidence: {resolved_clip.name} ({resolved_clip.stat().st_size / 1024:.0f} KB)")
                with open(resolved_clip, "rb") as video_file:
                    files = {"video": (resolved_clip.name, video_file, "video/mp4")}
                    data = {
                        "chat_id": chat_id,
                        "caption": video_caption,
                        "parse_mode": "HTML",
                        "supports_streaming": "true",
                    }
                    resp = await client.post(f"{self.api_base}/sendVideo", data=data, files=files)
                    if resp.status_code == 200:
                        logger.info(f"[Telegram] ✅ 8s incident video clip sent successfully to chat_id={chat_id}")
                        result = {"status": "ok", "video_sent": True, "location_sent": False}

                        # ── Send Real-Time Live Location Map Pin via sendLocation ──
                        try:
                            loc_data = {
                                "chat_id": chat_id,
                                "latitude": lat,
                                "longitude": lng,
                            }
                            resp_loc = await client.post(f"{self.api_base}/sendLocation", data=loc_data)
                            if resp_loc.status_code == 200:
                                logger.info(f"[Telegram] ✅ Real-time GPS Location pin ({lat:.4f}, {lng:.4f}) sent successfully.")
                                result["location_sent"] = True
                            else:
                                logger.warning(f"[Telegram] sendLocation returned HTTP {resp_loc.status_code}: {resp_loc.text}")
                        except Exception as e_loc:
                            logger.warning(f"[Telegram] sendLocation exception: {e_loc}")

                        return result
                    else:
                        logger.warning(f"[Telegram] sendVideo returned HTTP {resp.status_code}: {resp.text}")
                        return {"status": "failed", "http_status": resp.status_code, "error": resp.text}
            except Exception as e:
                logger.error(f"[Telegram] sendVideo error: {e}")
                return {"status": "error", "error": str(e)}

    def send_video_evidence_sync(
        self,
        video_path: str,
        alert_data: dict,
        severity: str = "critical",
        message: str = "",
    ) -> dict:
        """Synchronous wrapper for video evidence upload on ThreadPoolExecutor."""
        try:
            return asyncio.run(self.send_video_evidence(
                video_path=video_path,
                alert_data=alert_data,
                severity=severity,
                message=message,
            ))
        except Exception as e:
            logger.error(f"[Telegram] Video evidence dispatch error: {e}")
            return {"status": "error", "error": str(e)}


# Singleton instance
_telegram_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> TelegramNotifier:
    """Get or instantiate global TelegramNotifier singleton."""
    global _telegram_notifier
    if _telegram_notifier is None:
        _telegram_notifier = TelegramNotifier()
    return _telegram_notifier
