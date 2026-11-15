"""
IBVAP — Webcam Diagnostic Tool
================================
Run this script to diagnose why your Lenovo 300 FHD USB webcam
is returning black frames. It tests every camera index and backend,
saves test frames to disk, and checks Windows privacy settings.

Usage:
    .\venv\Scripts\python.exe scratch/webcam_diagnostic.py
"""

import cv2
import sys
import time
import numpy as np
import winreg
from pathlib import Path

DIAG_DIR = Path("scratch/webcam_diag_frames")
DIAG_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 70)
print("  IBVAP — Webcam Diagnostic Tool")
print("=" * 70)
print()

# --- Step 1: Check Windows Camera Privacy Settings ---
print("[1/4] Checking Windows Camera Privacy Settings...")
print("-" * 50)

privacy_checks = [
    ("Global camera access (HKLM)", winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"),
]

for label, root, path in privacy_checks:
    try:
        k = winreg.OpenKey(root, path)
        val, _ = winreg.QueryValueEx(k, "Value")
        status = "✅ ALLOWED" if val == "Allow" else f"❌ BLOCKED ({val})"
        print(f"  {label}: {status}")
    except Exception as e:
        print(f"  {label}: ⚠️ Could not read ({e})")

# Check for Lenovo Vantage Camera Privacy
for reg_path in [
    r"SOFTWARE\Lenovo\Lenovo Settings\Camera\Privacy",
    r"SOFTWARE\Lenovo\SmartSettings\Camera",
]:
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
        print(f"  ⚠️ Lenovo camera privacy registry found at: HKLM\\{reg_path}")
        i = 0
        while True:
            try:
                name, val, _ = winreg.EnumValue(k, i)
                print(f"      {name} = {val}")
                i += 1
            except OSError:
                break
    except Exception:
        pass

print()

# --- Step 2: Enumerate USB camera devices ---
print("[2/4] Enumerating USB camera devices in Windows registry...")
print("-" * 50)

usb_cameras = []
base = r"SYSTEM\CurrentControlSet\Enum\USB"
try:
    usb_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    i = 0
    while True:
        try:
            vid_pid = winreg.EnumKey(usb_key, i)
            i += 1
            vid_pid_key = winreg.OpenKey(usb_key, vid_pid)
            j = 0
            while True:
                try:
                    inst = winreg.EnumKey(vid_pid_key, j)
                    j += 1
                    inst_key = winreg.OpenKey(vid_pid_key, inst)
                    try:
                        desc, _ = winreg.QueryValueEx(inst_key, "DeviceDesc")
                    except:
                        desc = ""
                    try:
                        fname, _ = winreg.QueryValueEx(inst_key, "FriendlyName")
                    except:
                        fname = ""
                    if any(kw in (desc + fname).lower() for kw in ["camera", "webcam", "video"]):
                        usb_cameras.append((vid_pid, fname or desc))
                        print(f"  📷 {fname or desc} ({vid_pid})")
                except OSError:
                    break
        except OSError:
            break
except Exception as e:
    print(f"  Error reading USB registry: {e}")

if not usb_cameras:
    print("  ⚠️ No USB camera devices found in registry!")

print()

# --- Step 3: Test each camera index and backend ---
print("[3/4] Testing all camera indices and backends...")
print("-" * 50)
print("  (Each test waits 1.5s for sensor warm-up before reading frames)")
print()

backends = [
    ("MSMF", cv2.CAP_MSMF),
    ("DirectShow", cv2.CAP_DSHOW),
    ("Default", 0),
]

results = []

for idx in range(4):
    for bname, bval in backends:
        label = f"Index {idx} ({bname})"
        try:
            cap = cv2.VideoCapture(idx, bval) if bval != 0 else cv2.VideoCapture(idx)
            if not cap or not cap.isOpened():
                print(f"  {label}: ❌ Could not open")
                results.append((idx, bname, False, None, None))
                continue

            # Allow hardware sensor to warm up
            time.sleep(1.5)

            # Discard initial frames
            for _ in range(5):
                cap.read()

            ret, frame = cap.read()
            if not ret or frame is None or frame.size == 0:
                print(f"  {label}: ❌ Opened but read() returned empty frame")
                cap.release()
                results.append((idx, bname, True, None, None))
                continue

            brightness = float(np.mean(frame))
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)

            # Save frame to disk for visual inspection
            fname = f"test_idx{idx}_{bname.lower()}.jpg"
            cv2.imwrite(str(DIAG_DIR / fname), frame)

            status = "✅ ACTIVE" if brightness > 5.0 else "⚠️ DARK"
            print(f"  {label}: {status} — {w}x{h} @ {fps:.0f}fps, mean luminance: {brightness:.1f}")
            print(f"    Saved frame → scratch/webcam_diag_frames/{fname}")

            cap.release()
            results.append((idx, bname, True, brightness, f"{w}x{h}"))

        except Exception as e:
            print(f"  {label}: ❌ Error: {e}")
            results.append((idx, bname, False, None, None))

print()

# --- Step 4: Summary and recommendations ---
print("[4/4] Diagnostic Summary")
print("=" * 70)

active_streams = [(idx, b, br) for idx, b, opened, br, _ in results if br is not None and br > 5.0]
dark_streams = [(idx, b, br) for idx, b, opened, br, _ in results if br is not None and br <= 5.0]

if active_streams:
    print()
    print("  ✅ WORKING CAMERAS FOUND:")
    for idx, b, br in active_streams:
        print(f"     Index {idx} ({b}) — mean luminance: {br:.1f}")
    best = active_streams[0]
    print()
    print(f"  👉 Recommended: Set CAMERA_SOURCE={best[0]} in your .env file")
else:
    print()
    print("  ❌ NO WORKING CAMERAS DETECTED — ALL FRAMES ARE BLACK/DARK")
    print()
    print("  This is a HARDWARE or WINDOWS PERMISSION issue, not a code issue.")
    print()
    print("  Please check the following:")
    print()
    print("  1️⃣  PHYSICAL SHUTTER: The Lenovo 300 FHD has a manual sliding")
    print("     switch on top. Slide it so the RED/ORANGE dot disappears")
    print("     and the clear glass lens is fully exposed.")
    print()
    print("  2️⃣  WINDOWS CAMERA PRIVACY:")
    print("     • Open Windows Settings (Win+I)")
    print("     • Go to: Privacy & Security → Camera")
    print("     • Turn ON: 'Camera access'")
    print("     • Turn ON: 'Let apps access your camera'")
    print("     • Scroll down → Turn ON: 'Let desktop apps access your camera'")
    print()
    print("  3️⃣  LENOVO VANTAGE PRIVACY:")
    print("     • Open Lenovo Vantage app (if installed)")
    print("     • Go to: Device → Display & Camera")
    print("     • Turn OFF: 'Camera Privacy Mode'")
    print("     • Or press F8 / Fn+F8 on your keyboard")
    print()
    print("  4️⃣  WINDOWS CAMERA TEST:")
    print("     • Press Windows key → type 'Camera' → open Camera app")
    print("     • If camera is also black here, the problem is not Python.")
    print()
    print("  5️⃣  USB PORT: Try a different USB port on your laptop.")
    print()
    print("  6️⃣  ANOTHER APP HOLDING CAMERA: Close Zoom, Teams, Meet,")
    print("     OBS Studio, or any app that may be using the webcam.")

if dark_streams:
    print()
    print(f"  Dark cameras detected ({len(dark_streams)} streams):")
    for idx, b, br in dark_streams:
        print(f"     Index {idx} ({b}) — mean luminance: {br:.1f}")

print()
print(f"  Test frames saved to: {DIAG_DIR.resolve()}")
print("  Open these .jpg files to visually inspect what each camera returns.")
print()
print("=" * 70)

