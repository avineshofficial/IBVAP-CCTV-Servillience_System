"""
IBVAP — Post-Incident AI Face Extractor
==========================================
Extracts the clearest face crops from the finalized 8-second incident video clip
using OpenCV YuNet face detector. Never modifies the original video.

Supports extracting faces for ALL breaching persons (multiple face crops).
"""

import os
import logging
import cv2
import numpy as np
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# YuNet model path
PROJECT_ROOT = Path(__file__).parent.parent.parent
YUNET_MODEL_PATH = PROJECT_ROOT / "ml" / "models" / "face_detection_yunet_2023mar.onnx"
YUNET_DOWNLOAD_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


def _ensure_yunet_model() -> Optional[str]:
    """Download YuNet model if not present. Returns model path or None."""
    if YUNET_MODEL_PATH.exists():
        return str(YUNET_MODEL_PATH)

    YUNET_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"[FaceExtractor] Downloading YuNet model to {YUNET_MODEL_PATH}...")
    try:
        import urllib.request
        urllib.request.urlretrieve(YUNET_DOWNLOAD_URL, str(YUNET_MODEL_PATH))
        logger.info(f"[FaceExtractor] YuNet model downloaded ({YUNET_MODEL_PATH.stat().st_size / 1024:.0f} KB)")
        return str(YUNET_MODEL_PATH)
    except Exception as e:
        logger.warning(f"[FaceExtractor] Failed to download YuNet model: {e}")
        return None


def _face_clarity_score(
    score: float, sharpness: float, area: int, frontality: float
) -> float:
    """
    Compute composite Face Clarity Score.
    Higher = better quality face crop.
    """
    # Normalize components to 0-1 range
    norm_score = min(score, 1.0)
    norm_sharpness = min(sharpness / 200.0, 1.0)  # 200 = very sharp
    norm_area = min(area / 10000.0, 1.0)  # 10000 px² = large clear face
    norm_frontal = min(frontality, 1.0)

    # Weighted composite
    clarity = (
        0.30 * norm_score +
        0.30 * norm_sharpness +
        0.20 * norm_area +
        0.20 * norm_frontal
    )
    return clarity


def _compute_frontality(landmarks: np.ndarray) -> float:
    """
    Compute frontal alignment score from YuNet's 5 facial landmarks.
    landmarks: [left_eye_x, left_eye_y, right_eye_x, right_eye_y,
                nose_x, nose_y, mouth_left_x, mouth_left_y, mouth_right_x, mouth_right_y]
    Returns 0.0 (profile) to 1.0 (frontal).
    """
    if landmarks is None or len(landmarks) < 10:
        return 0.5  # Default if landmarks unavailable

    left_eye_x = landmarks[0]
    right_eye_x = landmarks[2]
    nose_x = landmarks[4]

    # Frontal: nose is centered between eyes
    eye_center_x = (left_eye_x + right_eye_x) / 2.0
    eye_span = abs(right_eye_x - left_eye_x)
    if eye_span < 1.0:
        return 0.3

    offset = abs(nose_x - eye_center_x) / eye_span
    # 0 offset = perfectly frontal, >0.5 = side profile
    frontality = max(0.0, 1.0 - offset * 2.0)
    return frontality


def extract_faces_from_clip(
    video_path: str,
    alert_id: str,
    output_dir: str,
    max_faces: int = 5,
    min_confidence: float = 0.70,
    min_face_size: int = 40,
    min_sharpness: float = 35.0,
    sample_every_n: int = 2,
) -> dict:
    """
    Extract the clearest face crops from an 8-second incident video clip.
    Opens the video READ-ONLY — never modifies the original.

    Returns dict with:
        face_count: int — number of distinct face crops saved
        faces: list[dict] — [{face_image_url, confidence, clarity_score}, ...]
        face_capture_status: "captured" | "unavailable"
    """
    result = {
        "face_count": 0,
        "faces": [],
        "face_capture_status": "unavailable",
    }

    model_path = _ensure_yunet_model()
    if not model_path:
        logger.warning("[FaceExtractor] YuNet model not available, skipping face extraction.")
        return result

    video_file = Path(video_path)
    if not video_file.exists() or video_file.stat().st_size < 10000:
        logger.warning(f"[FaceExtractor] Video not found or too small: {video_path}")
        return result

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_file))
    if not cap.isOpened():
        logger.warning(f"[FaceExtractor] Cannot open video: {video_path}")
        return result

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    try:
        detector = cv2.FaceDetectorYN.create(
            model_path, "", (frame_w, frame_h),
            score_threshold=min_confidence,
            nms_threshold=0.3,
            top_k=10,
        )
    except Exception as e:
        logger.warning(f"[FaceExtractor] Failed to create YuNet detector: {e}")
        cap.release()
        return result

    # Collect all candidate face detections across frames
    # Key: best face per unique "face slot" (we keep top N by clarity)
    all_candidates = []  # [(clarity_score, frame_copy, bbox, confidence, landmarks)]

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        # Sample every Nth frame for speed
        if frame_idx % sample_every_n != 0:
            continue

        # Run YuNet face detection
        _, faces_detected = detector.detect(frame)
        if faces_detected is None or len(faces_detected) == 0:
            continue

        for face in faces_detected:
            x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
            score = float(face[-1])

            # Quality gates
            if score < min_confidence:
                continue
            if w < min_face_size or h < min_face_size:
                continue

            # Clamp to frame boundaries with 20% margin
            margin_x = int(w * 0.2)
            margin_y = int(h * 0.2)
            x1 = max(0, x - margin_x)
            y1 = max(0, y - margin_y)
            x2 = min(frame_w, x + w + margin_x)
            y2 = min(frame_h, y + h + margin_y)

            face_crop = frame[y1:y2, x1:x2]
            if face_crop.size == 0:
                continue

            # Compute sharpness (Laplacian variance)
            gray_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            sharpness = cv2.Laplacian(gray_face, cv2.CV_64F).var()
            if sharpness < min_sharpness:
                continue

            # Compute frontality from landmarks
            landmarks = face[4:14] if len(face) >= 14 else None
            frontality = _compute_frontality(landmarks)

            # Compute area
            area = w * h

            # Composite clarity score
            clarity = _face_clarity_score(score, sharpness, area, frontality)

            all_candidates.append({
                "clarity": clarity,
                "frame": frame.copy(),
                "bbox": (x1, y1, x2, y2),
                "confidence": score,
                "sharpness": sharpness,
                "frontality": frontality,
                "area": area,
            })

    cap.release()

    if not all_candidates:
        logger.info(f"[FaceExtractor] No clear faces found in clip: {video_file.name}")
        return result

    # Sort by clarity score (best first) and take top N
    all_candidates.sort(key=lambda c: c["clarity"], reverse=True)

    # Deduplicate: keep faces that are spatially distinct (non-overlapping centers)
    selected = []
    used_centers = []
    min_center_dist = 50  # pixels

    for cand in all_candidates:
        x1, y1, x2, y2 = cand["bbox"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

        too_close = False
        for ux, uy in used_centers:
            if abs(cx - ux) < min_center_dist and abs(cy - uy) < min_center_dist:
                too_close = True
                break

        if not too_close:
            selected.append(cand)
            used_centers.append((cx, cy))
            if len(selected) >= max_faces:
                break

    # Save face crops
    saved_faces = []
    for i, cand in enumerate(selected):
        x1, y1, x2, y2 = cand["bbox"]
        face_crop = cand["frame"][y1:y2, x1:x2]

        suffix = f"_face_{i + 1}" if len(selected) > 1 else "_face"
        filename = f"{alert_id}{suffix}.jpg"
        face_path = out_dir / filename
        cv2.imwrite(str(face_path), face_crop, [cv2.IMWRITE_JPEG_QUALITY, 92])

        face_url = f"/media/faces/{filename}"
        saved_faces.append({
            "face_image_url": face_url,
            "confidence": round(cand["confidence"], 3),
            "clarity_score": round(cand["clarity"], 3),
            "sharpness": round(cand["sharpness"], 1),
        })
        logger.info(
            f"[FaceExtractor] Saved face crop: {filename} "
            f"(confidence={cand['confidence']:.2f}, clarity={cand['clarity']:.3f}, "
            f"sharpness={cand['sharpness']:.0f})"
        )

    result["face_count"] = len(saved_faces)
    result["faces"] = saved_faces
    result["face_capture_status"] = "captured" if saved_faces else "unavailable"

    return result
