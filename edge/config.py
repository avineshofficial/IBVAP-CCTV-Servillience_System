"""
IBVAP Edge Configuration
========================
All edge-layer settings. Loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MODELS_DIR = PROJECT_ROOT / "ml" / "models"
MEDIA_DIR = PROJECT_ROOT / "core" / "media"
SAMPLE_VIDEOS_DIR = PROJECT_ROOT / "ml" / "datasets" / "sample_videos"

# Validate required security keys at startup
_edge_api_key = os.getenv("EDGE_API_KEY")
if not _edge_api_key or _edge_api_key.strip() in ("", "changeme-generate-a-secure-edge-key"):
    raise RuntimeError(
        "CRITICAL STARTUP ERROR: 'EDGE_API_KEY' is not configured in .env! "
        "Edge pipeline requires EDGE_API_KEY to authenticate with core."
    )


@dataclass
class EdgeConfig:
    """Configuration for the edge inference pipeline."""

    # --- Camera / Ingestion ---
    camera_source: str = os.getenv("CAMERA_SOURCE", "sample")
    camera_fps: int = int(os.getenv("CAMERA_FPS", "15"))
    frame_width: int = int(os.getenv("FRAME_WIDTH", "1280"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "720"))

    # --- Detection ---
    yolo_model: str = os.getenv("YOLO_MODEL", "yolo11n.pt")
    detection_confidence: float = float(os.getenv("DETECTION_CONFIDENCE", "0.4"))
    detection_classes: list = field(default_factory=lambda: [0, 1, 2, 3, 5, 7])
    # COCO classes: 0=person, 1=bicycle, 2=car, 3=motorcycle, 5=bus, 7=truck

    # --- Tracking ---
    tracker_type: str = os.getenv("TRACKER_TYPE", "bytetrack.yaml")
    track_buffer: int = int(os.getenv("TRACK_BUFFER", "30"))

    # --- Night Enhancement ---
    night_enhance_enabled: bool = os.getenv("NIGHT_ENHANCE_ENABLED", "true").lower() == "true"
    night_enhance_threshold: int = int(os.getenv("NIGHT_ENHANCE_THRESHOLD", "60"))

    # --- Face Detection ---
    face_detection_enabled: bool = os.getenv("FACE_DETECTION_ENABLED", "true").lower() == "true"
    face_model_pack: str = os.getenv("FACE_MODEL_PACK", "buffalo_l")
    face_det_size: tuple = (640, 640)

    # --- ANPR ---
    anpr_enabled: bool = os.getenv("ANPR_ENABLED", "true").lower() == "true"
    anpr_confidence: float = float(os.getenv("ANPR_CONFIDENCE", "0.5"))
    anpr_vote_frames: int = int(os.getenv("ANPR_VOTE_FRAMES", "5"))

    # --- Virtual Fence ---
    fence_enabled: bool = os.getenv("FENCE_ENABLED", "true").lower() == "true"
    dwell_time_threshold: float = float(os.getenv("DWELL_TIME_THRESHOLD", "30.0"))  # seconds

    # --- Activity Detection ---
    activity_detection_enabled: bool = os.getenv("ACTIVITY_DETECTION_ENABLED", "true").lower() == "true"
    loiter_threshold: float = float(os.getenv("LOITER_THRESHOLD", "60.0"))  # seconds
    sprint_speed_threshold: float = float(os.getenv("SPRINT_SPEED_THRESHOLD", "5.0"))  # m/s
    group_radius: float = float(os.getenv("GROUP_RADIUS", "3.0"))  # meters
    group_min_count: int = int(os.getenv("GROUP_MIN_COUNT", "3"))

    # --- Sync ---
    core_api_url: str = os.getenv("CORE_API_URL", "http://127.0.0.1:8000")
    edge_api_key: str = _edge_api_key
    sync_interval: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "5"))
    sync_batch_size: int = int(os.getenv("SYNC_BATCH_SIZE", "50"))

    # --- Local Buffer ---
    local_db_path: str = os.getenv("LOCAL_DB_PATH", str(PROJECT_ROOT / "edge" / "buffer" / "edge_buffer.db"))
    video_ring_buffer_hours: int = int(os.getenv("VIDEO_RING_BUFFER_HOURS", "72"))

    # --- Paths ---
    models_dir: Path = MODELS_DIR
    media_dir: Path = MEDIA_DIR
    sample_videos_dir: Path = SAMPLE_VIDEOS_DIR

    def get_camera_source(self) -> str | int:
        """Resolve camera source to a usable value."""
        if self.camera_source == "sample":
            # Use first sample video found
            if self.sample_videos_dir.exists():
                videos = list(self.sample_videos_dir.glob("*.mp4"))
                if videos:
                    return str(videos[0])
            # Fallback to webcam
            return 0
        elif self.camera_source.isdigit():
            return int(self.camera_source)
        return self.camera_source
