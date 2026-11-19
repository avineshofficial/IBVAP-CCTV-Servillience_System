"""
IBVAP — Telegram Notification Test Script
===========================================
Tests Telegram Bot API mobile alert notifications:
1. Validates bot credentials via /getMe
2. Checks /getUpdates to auto-discover user chat_id
3. Sends formatted incident details + 8s MP4 video clip + interactive GPS map pin
"""

import os
import sys
import time
import argparse
import asyncio
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import httpx
from core.config import CoreConfig
from core.alert_engine.telegram_notifier import TelegramNotifier


def main():
    parser = argparse.ArgumentParser(description="Test IBVAP Telegram Bot API mobile notifications.")
    parser.add_argument("--token", default="", help="Telegram Bot Token (default from .env)")
    parser.add_argument("--chat-id", default="", help="Target Telegram Chat ID (default from .env or auto-discovered)")
    parser.add_argument("--clip", default="", help="Path to sample MP4 clip file")
    args = parser.parse_args()

    token = args.token or os.getenv("TELEGRAM_BOT_TOKEN") or CoreConfig.TELEGRAM_BOT_TOKEN
    chat_id = args.chat_id or os.getenv("TELEGRAM_CHAT_ID") or CoreConfig.TELEGRAM_CHAT_ID

    print("=" * 65)
    print("📡 IBVAP Telegram Alert Notification Verification")
    print("=" * 65)

    if not token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN is not configured in .env or passed via --token.")
        print("   Please set TELEGRAM_BOT_TOKEN in .env and try again.")
        sys.exit(1)

    print(f"🔑 Bot Token: {token[:10]}...{token[-5:]}")

    # 1. Test /getMe
    print("\n[Step 1/3] Verifying Bot API connection (/getMe)...")
    try:
        resp = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10.0)
        if resp.status_code == 200:
            data = resp.json().get("result", {})
            bot_name = data.get("first_name", "IBVAP Bot")
            username = data.get("username", "SecureZone_Alert_NotifyBot")
            print(f"✅ Bot Connected: '{bot_name}' (@{username})")
        else:
            print(f"❌ /getMe failed (HTTP {resp.status_code}): {resp.text}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Connection error: {e}")
        sys.exit(1)

    # 2. Check /getUpdates to discover or verify chat_id
    print("\n[Step 2/3] Checking active chat ID (/getUpdates)...")
    discovered_chat_id = None
    sender_name = "User"
    try:
        resp = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10.0)
        if resp.status_code == 200:
            updates = resp.json().get("result", [])
            if updates:
                latest = updates[-1]
                msg = latest.get("message") or latest.get("channel_post") or latest.get("edited_message")
                if msg and "chat" in msg:
                    discovered_chat_id = str(msg["chat"]["id"])
                    sender_name = msg["chat"].get("first_name") or msg["chat"].get("title") or "User"
                    print(f"ℹ️ Found message in bot inbox from '{sender_name}' (chat_id: {discovered_chat_id})")
            else:
                print("ℹ️ Inbox currently empty (no /start or text messages sent to bot yet).")
    except Exception as e:
        print(f"⚠️ getUpdates check warning: {e}")

    active_chat_id = chat_id or discovered_chat_id

    if not active_chat_id:
        print("\n⚠️ TELEGRAM_CHAT_ID is not configured!")
        print("👉 How to link your mobile phone:")
        print("   1. Open Telegram on your phone.")
        print("   2. Search for: @SecureZone_Alert_NotifyBot (or visit https://t.me/SecureZone_Alert_NotifyBot)")
        print("   3. Press 'START' or send any text message (e.g. 'Hello').")
        print("   4. Re-run this script to automatically detect your Chat ID!")
        sys.exit(0)

    print(f"🎯 Target Chat ID: {active_chat_id} ({sender_name})")

    # 3. Locate Sample Clip
    clips_dir = CoreConfig.MEDIA_DIR / "clips"
    sample_clip = args.clip
    if not sample_clip and clips_dir.exists():
        mp4_files = sorted(list(clips_dir.glob("*.mp4")), key=lambda p: p.stat().st_mtime, reverse=True)
        if mp4_files:
            sample_clip = str(mp4_files[0])

    if sample_clip and Path(sample_clip).exists():
        print(f"🎥 Incident Clip: {Path(sample_clip).name} ({Path(sample_clip).stat().st_size / 1024:.0f} KB)")
    else:
        print("ℹ️ No MP4 clip found in core/media/clips/. Will test fallback text alert.")

    # 4. Dispatch Alert Notification
    print("\n[Step 3/3] Sending mobile alert (Video + HTML Details + Live GPS Location Pin)...")
    notifier = TelegramNotifier(bot_token=token, chat_id=active_chat_id, enabled=True)

    sample_alert_data = {
        "zone_name": "Restricted Border Perimeter",
        "zone_id": "zone_restricted_area",
        "alert_type": "fence_breach",
        "breach_type": "entered_exclusion",
        "activity": "fence_cross / suspicious_intrusion",
        "confidence": 0.942,
        "camera_id": "CAM-01",
        "bop_id": "Border Sector Alpha",
        "track_id": 14,
        "object_class": "person",
        "latitude": notifier.default_lat,
        "longitude": notifier.default_lng,
        "timestamp": time.time(),
        "clip_url": sample_clip,
    }

    result = asyncio.run(notifier.send_incident_alert(
        alert_data=sample_alert_data,
        severity="critical",
        message="entered_exclusion by person in Restricted Border Perimeter (Track #14)",
        clip_path=sample_clip,
        wait_for_clip_seconds=0.0,
    ))

    print("\n--- Dispatch Result ---")
    print(f"Status: {result.get('status')}")
    print(f"Chat ID: {result.get('chat_id')}")
    print(f"8s Video Sent: {result.get('video_sent')}")
    print(f"Live Location Map Pin Sent: {result.get('location_sent')}")

    if result.get("video_sent") and result.get("location_sent"):
        print("\n🎉 SUCCESS! Full mobile incident package delivered to Telegram.")
    elif result.get("status") == "ok":
        print("\n✅ Notification delivered successfully to Telegram.")
    else:
        print(f"\n⚠️ Result detail: {result}")


if __name__ == "__main__":
    main()
