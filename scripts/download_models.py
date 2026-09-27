"""
IBVAP — Model & Sample Video Download Script
==============================================
Downloads pretrained models and sample surveillance videos for the prototype.
"""

import os
import sys
import urllib.request
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "ml" / "models"
SAMPLE_DIR = PROJECT_ROOT / "ml" / "datasets" / "sample_videos"


def download_file(url: str, dest: Path, desc: str = ""):
    """Download a file with progress indication."""
    if dest.exists():
        logger.info(f"  ✓ Already exists: {dest.name}")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"  ↓ Downloading {desc or dest.name}...")

    try:
        urllib.request.urlretrieve(url, str(dest))
        size_mb = dest.stat().st_size / (1024 * 1024)
        logger.info(f"  ✓ Downloaded: {dest.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        logger.error(f"  ✗ Failed to download {desc}: {e}")
        return False


def create_sample_video(overwrite: bool = True):
    """Create a synthetic sample video for testing with realistic background and clear targets."""
    try:
        import cv2
        import numpy as np

        sample_path = SAMPLE_DIR / "sample_surveillance.mp4"
        if sample_path.exists() and not overwrite:
            logger.info("  ✓ Sample video already exists")
            return

        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("  🎬 Creating synthetic sample surveillance video...")

        width, height, fps, duration = 1280, 720, 15, 30  # 30 seconds
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(sample_path), fourcc, fps, (width, height))

        np.random.seed(42)
        # Moving entities in ground coordinate paths
        objects = [
            # Target 1: Person walking across border line (Y: 450 -> 250 -> 450)
            {"id": 1, "x": 300, "y": 480, "vx": 1.5, "vy": -2.2, "w": 44, "h": 90, "type": "person"},
            # Target 2: Person walking along perimeter
            {"id": 2, "x": 750, "y": 520, "vx": -1.2, "vy": -0.8, "w": 40, "h": 85, "type": "person"},
            # Target 3: Vehicle driving horizontally
            {"id": 3, "x": 100, "y": 580, "vx": 4.5, "vy": 0.0, "w": 130, "h": 65, "type": "car"},
            # Target 4: Person near restricted zone
            {"id": 4, "x": 1050, "y": 420, "vx": -1.0, "vy": -1.5, "w": 42, "h": 88, "type": "person"},
        ]

        for f in range(fps * duration):
            # Base dark surveillance background scene
            frame = np.zeros((height, width, 3), dtype=np.uint8)

            # Sky / Horizon gradient
            for y in range(350):
                val = int(25 + 30 * (y / 350))
                frame[y, :] = (val + 10, val + 15, val + 5)

            # Terrain ground
            frame[350:, :] = (35, 45, 30)

            # Road path across scene
            cv2.fillPoly(frame, [np.array([[0, 680], [1280, 600], [1280, 520], [0, 560]])], (50, 55, 45))
            cv2.polylines(frame, [np.array([[0, 620], [1280, 560]])], False, (80, 85, 75), 2)

            # Grid ground texture / distance marks
            for y_line in range(360, 720, 40):
                cv2.line(frame, (0, y_line), (1280, y_line), (42, 52, 38), 1)

            # Border Post / Watchtower graphic on horizon
            cv2.rectangle(frame, (1120, 260), (1160, 350), (60, 70, 60), -1)
            cv2.rectangle(frame, (1110, 240), (1170, 260), (80, 90, 80), -1)

            # Render realistic subtle human/vehicle silhouettes
            for obj in objects:
                obj["x"] += obj["vx"]
                obj["y"] += obj["vy"]

                # Bounce inside frame boundaries
                if obj["x"] < 50 or obj["x"] > width - obj["w"] - 50:
                    obj["vx"] *= -1
                if obj["y"] < 200 or obj["y"] > height - obj["h"] - 30:
                    obj["vy"] *= -1

                x, y, w, h = int(obj["x"]), int(obj["y"]), obj["w"], obj["h"]

                if obj["type"] == "person":
                    # Draw realistic human silhouette figure
                    head_center = (x + w // 2, y + 15)
                    cv2.circle(frame, head_center, 10, (160, 170, 160), -1)
                    # Body torso
                    cv2.ellipse(frame, (x + w // 2, y + 45), (14, 22), 0, 0, 360, (140, 150, 140), -1)
                    # Legs
                    cv2.line(frame, (x + w // 2 - 6, y + 65), (x + w // 2 - 10, y + h), (130, 140, 130), 4)
                    cv2.line(frame, (x + w // 2 + 6, y + 65), (x + w // 2 + 10, y + h), (130, 140, 130), 4)
                else:
                    # Draw realistic vehicle silhouette
                    cv2.rectangle(frame, (x, y + 20), (x + w, y + h), (140, 150, 160), -1)
                    cv2.rectangle(frame, (x + 20, y), (x + w - 20, y + 25), (110, 120, 130), -1)
                    # Wheels
                    cv2.circle(frame, (x + 25, y + h), 10, (30, 30, 30), -1)
                    cv2.circle(frame, (x + w - 25, y + h), 10, (30, 30, 30), -1)

            # Timestamp overlay (CCTV style)
            ts = f"2026-09-11 10:00:{f // fps:02d}"
            cv2.putText(frame, ts, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 200), 2)
            cv2.putText(frame, "CAM-01 | BOP ALPHA PERIMETER", (width - 340, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 200), 2)

            out.write(frame)

        out.release()
        logger.info(f"  ✓ Created clean sample video: {sample_path}")

    except Exception as e:
        logger.warning(f"  ⚠ Failed to create sample video: {e}")


def main():
    logger.info("=" * 50)
    logger.info("IBVAP — Model & Sample Setup")
    logger.info("=" * 50)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    # YOLO model will be auto-downloaded by ultralytics on first run
    logger.info("\n📦 YOLO Model:")
    logger.info("  ℹ YOLO model auto-downloads on first inference run")

    # InsightFace models also auto-download
    logger.info("\n📦 InsightFace Models:")
    logger.info("  ℹ InsightFace models auto-download on first use")

    # Create sample video
    logger.info("\n🎬 Sample Video:")
    create_sample_video()

    logger.info("\n" + "=" * 50)
    logger.info("Setup complete!")
    logger.info("=" * 50)
    logger.info("\nTo run the prototype:")
    logger.info("  1. Start core:  cd ibvap && python -m core.main")
    logger.info("  2. Start edge:  cd ibvap && python -m edge.main")
    logger.info("  3. Start web:   cd ibvap/web/dashboard && npm run dev")


if __name__ == "__main__":
    main()
