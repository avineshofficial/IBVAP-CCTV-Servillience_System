"""
IBVAP — Dataset Collection Tool
=================================
Records labeled video clips for tuning activity detection thresholds.

Usage:
    python -m ml.datasets.collect_dataset [--source 0|rtsp://...]

Controls:
    1 = normal_walk    2 = loiter     3 = crawl
    4 = run            5 = group      6 = fence_cross
    SPACE = stop current clip
    q = quit
"""

import cv2
import sys
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Reuse the existing camera connection logic
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from edge.ingestion.camera import CameraStream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("IBVAP.DatasetCollector")

# Label mapping: key code → label name
LABEL_KEYS = {
    ord("1"): "normal_walk",
    ord("2"): "loiter",
    ord("3"): "crawl",
    ord("4"): "run",
    ord("5"): "group",
    ord("6"): "fence_cross",
}


def main():
    parser = argparse.ArgumentParser(description="IBVAP Dataset Collection Tool")
    parser.add_argument(
        "--source", default="0",
        help="Camera source: webcam index (0), RTSP URL, or video file path",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for clips (default: ml/datasets/raw/)",
    )
    parser.add_argument("--fps", type=int, default=15, help="Target FPS for recording")
    parser.add_argument("--width", type=int, default=1280, help="Frame width")
    parser.add_argument("--height", type=int, default=720, help="Frame height")
    args = parser.parse_args()

    # Resolve source
    source = int(args.source) if args.source.isdigit() else args.source

    # Output directory
    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")

    # Initialize camera using existing CameraStream
    camera = CameraStream(
        source=source,
        camera_id="collector",
        target_fps=args.fps,
        width=args.width,
        height=args.height,
    )

    # Recording state
    recording = False
    current_label = None
    writer = None
    clip_start = 0.0
    clip_frame_count = 0
    total_clips = 0

    # Count existing clips per label
    clip_counts = {}
    for label in LABEL_KEYS.values():
        existing = list(output_dir.glob(f"{label}_*.mp4"))
        clip_counts[label] = len(existing)

    logger.info("=" * 60)
    logger.info("IBVAP Dataset Collection Tool")
    logger.info("=" * 60)
    logger.info("Controls:")
    for key_code, label in LABEL_KEYS.items():
        count = clip_counts.get(label, 0)
        logger.info(f"  {chr(key_code)} = {label:<15s} ({count} existing clips)")
    logger.info("  SPACE = stop current clip")
    logger.info("  q     = quit")
    logger.info("=" * 60)

    try:
        for packet in camera.frames():
            frame = packet.frame.copy()

            # Draw overlay
            h, w = frame.shape[:2]

            # Status bar at top
            bar_color = (0, 0, 200) if recording else (80, 80, 80)
            cv2.rectangle(frame, (0, 0), (w, 50), bar_color, -1)

            if recording:
                elapsed = time.time() - clip_start
                status = f"REC [{current_label}] {elapsed:.1f}s | {clip_frame_count} frames"
                # Blinking dot
                if int(time.time() * 2) % 2:
                    cv2.circle(frame, (25, 25), 10, (0, 0, 255), -1)
            else:
                status = "READY — Press 1-6 to start recording"

            cv2.putText(frame, status, (45, 35), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (255, 255, 255), 2)

            # Label guide at bottom
            guide_y = h - 10
            guide = "  ".join(f"{chr(k)}:{v}" for k, v in LABEL_KEYS.items())
            cv2.rectangle(frame, (0, h - 35), (w, h), (40, 40, 40), -1)
            cv2.putText(frame, guide, (10, guide_y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (200, 200, 200), 1)

            # Clip counts on the right
            y_offset = 80
            for label in LABEL_KEYS.values():
                count = clip_counts.get(label, 0)
                color = (0, 255, 0) if count >= 8 else (0, 200, 255) if count >= 4 else (100, 100, 100)
                cv2.putText(frame, f"{label}: {count}", (w - 200, y_offset),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                y_offset += 25

            cv2.imshow("IBVAP Dataset Collector", frame)

            # Write frame if recording
            if recording and writer is not None:
                writer.write(packet.frame)  # Write the clean frame, not the overlay
                clip_frame_count += 1

            # Handle key presses
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                if recording and writer is not None:
                    writer.release()
                    elapsed = time.time() - clip_start
                    logger.info(
                        f"Saved: {current_label} clip — {clip_frame_count} frames, "
                        f"{elapsed:.1f}s"
                    )
                    total_clips += 1
                break

            elif key == ord(" "):  # SPACE — stop recording
                if recording and writer is not None:
                    writer.release()
                    writer = None
                    elapsed = time.time() - clip_start
                    logger.info(
                        f"Saved: {current_label} clip — {clip_frame_count} frames, "
                        f"{elapsed:.1f}s"
                    )
                    clip_counts[current_label] = clip_counts.get(current_label, 0) + 1
                    total_clips += 1
                    recording = False
                    current_label = None

            elif key in LABEL_KEYS:
                # Stop current recording if any
                if recording and writer is not None:
                    writer.release()
                    elapsed = time.time() - clip_start
                    logger.info(
                        f"Saved: {current_label} clip — {clip_frame_count} frames, "
                        f"{elapsed:.1f}s"
                    )
                    clip_counts[current_label] = clip_counts.get(current_label, 0) + 1
                    total_clips += 1

                # Start new recording
                current_label = LABEL_KEYS[key]
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = output_dir / f"{current_label}_{timestamp}.mp4"

                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(
                    str(filename), fourcc, args.fps,
                    (packet.width, packet.height),
                )
                recording = True
                clip_start = time.time()
                clip_frame_count = 0
                logger.info(f"Recording: {current_label} → {filename.name}")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        if writer is not None:
            writer.release()

        logger.info("=" * 60)
        logger.info(f"Session complete — {total_clips} clips recorded")
        logger.info(f"Clips saved to: {output_dir}")
        for label in LABEL_KEYS.values():
            count = clip_counts.get(label, 0)
            status = "✓" if count >= 8 else "…"
            logger.info(f"  {status} {label}: {count} clips")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
