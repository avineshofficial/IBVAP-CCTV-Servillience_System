"""
IBVAP — Dataset Frame Extractor
================================
Extracts clean, evenly-spaced image frames from captured video clips
in ml/datasets/raw/ for annotation in CVAT/Roboflow and Google Colab training.

Usage:
    python -m ml.datasets.extract_dataset_frames [--fps 1] [--output-dir ml/datasets/frames]
"""

import cv2
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s │ %(levelname)-7s │ %(message)s")
logger = logging.getLogger("IBVAP.FrameExtractor")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "ml" / "datasets" / "raw"
DEFAULT_OUT_DIR = PROJECT_ROOT / "ml" / "datasets" / "frames"


def extract_frames(raw_dir: Path, out_dir: Path, target_fps: float = 1.0):
    raw_clips = sorted(raw_dir.glob("*.mp4"))
    if not raw_clips:
        logger.warning(f"No .mp4 clips found in {raw_dir}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    total_saved = 0

    logger.info(f"Extracting frames from {len(raw_clips)} video clips at {target_fps} FPS...")

    for clip in raw_clips:
        cap = cv2.VideoCapture(str(clip))
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        frame_interval = max(1, int(round(video_fps / target_fps)))

        clip_name = clip.stem
        frame_idx = 0
        saved_from_clip = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            if frame_idx % frame_interval == 0:
                frame_filename = out_dir / f"{clip_name}_f{frame_idx:05d}.jpg"
                cv2.imwrite(str(frame_filename), frame)
                saved_from_clip += 1
                total_saved += 1

            frame_idx += 1

        cap.release()
        logger.info(f"  ✓ {clip.name:<35s} → {saved_from_clip} frames extracted")

    logger.info("=" * 60)
    logger.info(f"Done! Extracted {total_saved} images into: {out_dir}")
    logger.info("=" * 60)
    return total_saved


def main():
    parser = argparse.ArgumentParser(description="Extract frames from raw dataset clips")
    parser.add_argument("--raw-dir", type=str, default=str(RAW_DIR), help="Directory of raw MP4 clips")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUT_DIR), help="Output directory for JPEG images")
    parser.add_argument("--fps", type=float, default=1.0, help="Frames to extract per second of video (default: 1.0)")
    args = parser.parse_args()

    extract_frames(Path(args.raw_dir), Path(args.output_dir), args.fps)


if __name__ == "__main__":
    main()

