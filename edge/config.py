"""
IBVAP Edge Configuration
========================
All edge-layer settings. Loaded from environment variables with sensible defaults.
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Ensure Ultralytics config is stored inside the project workspace
# to prevent WinError 5 access denied on AppData\Roaming in restricted/sandbox environments
_ultralytics_dir = PROJECT_ROOT / ".ultralytics"
_ultralytics_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(_ultralytics_dir))
os.environ["YOLO_CONFIG_DIR"] = str(_ultralytics_dir)

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
    camera_source: str = os.getenv("CAMERA_SOURCE", "auto")
    camera_fps: int = int(os.getenv("CAMERA_FPS", "25"))
    frame_width: int = int(os.getenv("FRAME_WIDTH", "1280"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "720"))

    # --- Detection (YOLO26 with RTX 3050 CUDA Acceleration) ---
    yolo_model: str = os.getenv("YOLO_MODEL", "yolo26n.pt")
    yolo_device: str = os.getenv("YOLO_DEVICE", "cuda:0")
    yolo_half_precision: bool = os.getenv("YOLO_HALF_PRECISION", "true").lower() == "true"
    yolo_imgsz: int = int(os.getenv("YOLO_IMGSZ", "640"))
    detection_confidence: float = float(os.getenv("DETECTION_CONFIDENCE", "0.6"))
    detection_classes: list = field(default_factory=lambda: [0, 1, 2, 3, 5, 7])
    # COCO classes: 0=person, 1=bicycle, 2=car, 3=motorcycle, 5=bus, 7=truck

    # --- Tracking & Inference Stride ---
    tracker_type: str = os.getenv("TRACKER_TYPE", "bytetrack.yaml")
    track_buffer: int = int(os.getenv("TRACK_BUFFER", "30"))
    inference_stride: int = int(os.getenv("INFERENCE_STRIDE", "0"))  # 0 = auto (1 on CUDA GPU, 2 on CPU)

    # --- Night Enhancement ---
    night_enhance_enabled: bool = os.getenv("NIGHT_ENHANCE_ENABLED", "false").lower() == "true"
    night_enhance_threshold: int = int(os.getenv("NIGHT_ENHANCE_THRESHOLD", "60"))

    # --- Face Detection ---
    face_detection_enabled: bool = os.getenv("FACE_DETECTION_ENABLED", "false").lower() == "true"
    face_model_pack: str = os.getenv("FACE_MODEL_PACK", "buffalo_l")
    face_det_size: tuple = (640, 640)

    # --- ANPR ---
    anpr_enabled: bool = os.getenv("ANPR_ENABLED", "false").lower() == "true"
    anpr_confidence: float = float(os.getenv("ANPR_CONFIDENCE", "0.5"))
    anpr_vote_frames: int = int(os.getenv("ANPR_VOTE_FRAMES", "5"))

    # --- Virtual Fence ---
    fence_enabled: bool = os.getenv("FENCE_ENABLED", "true").lower() == "true"
    dwell_time_threshold: float = float(os.getenv("DWELL_TIME_THRESHOLD", "30.0"))  # seconds

    # --- Incident Clip Recording ---
    clip_duration_seconds: float = float(os.getenv("CLIP_DURATION_SECONDS", "8.0"))
    pre_alert_buffer_seconds: float = float(os.getenv("PRE_ALERT_BUFFER_SECONDS", "4.0"))
    post_alert_buffer_seconds: float = float(os.getenv("POST_ALERT_BUFFER_SECONDS", "4.0"))
    clip_target_fps: float = float(os.getenv("CLIP_TARGET_FPS", "20.0"))

    # --- Alert Cooldown ---
    alert_cooldown_seconds: float = float(os.getenv("ALERT_COOLDOWN_SECONDS", "10.0"))

    # --- Telegram Mobile Notifications ---
    telegram_enabled: bool = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Perspective Restricted Zone (calibrated to floor perspective) ---
    # Calibrated to the floor perimeter matching the camera view:
    #   - Top boundary perimeter: (0, 505) -> (1280, 505)
    #   - Bottom floor coverage: (1280, 720) -> (0, 720)
    # Can also be customized in .env via RESTRICTED_ZONE_POLYGON
    restricted_zone_polygon: list = field(default_factory=lambda: (
        [tuple(p) for p in json.loads(os.getenv("RESTRICTED_ZONE_POLYGON"))]
        if os.getenv("RESTRICTED_ZONE_POLYGON")
        else [
            (0, 505),       # Far-left border point (aligned to blue perimeter)
            (1280, 505),    # Far-right border point (aligned to blue perimeter)
            (1280, 720),    # Bottom-right corner
            (0, 720),       # Bottom-left corner
        ]
    ))

    # --- Activity Detection ---
    activity_detection_enabled: bool = os.getenv("ACTIVITY_DETECTION_ENABLED", "false").lower() == "true"
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
        src = str(self.camera_source).strip().lower()
        if src in ("auto", "webcam"):
            return "auto"
        elif src in ("usb", "external"):
            return "usb"
        elif src == "sample":
            if self.sample_videos_dir.exists():
                videos = list(self.sample_videos_dir.glob("*.mp4"))
                if videos:
                    return str(videos[0])
            return "auto"
        elif src.isdigit():
            return int(src)
        return self.camera_source

    def get_yolo_device(self) -> str:
        """Resolve YOLO device, prioritizing CUDA and falling back to CPU if unavailable."""
        dev = self.yolo_device.strip().lower()
        if dev.startswith("cuda"):
            try:
                import torch
                if not torch.cuda.is_available():
                    return "cpu"
            except Exception:
                return "cpu"
        elif dev in ("auto", "gpu"):
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda:0"
                return "cpu"
            except Exception:
                return "cpu"
        return dev

    def get_inference_stride(self) -> int:
        """Resolve inference stride. If 0 (auto), returns 1 on CUDA GPU and 2 on CPU."""
        if self.inference_stride > 0:
            return self.inference_stride
        return 1 if self.get_yolo_device().startswith("cuda") else 2

    def is_half_precision(self) -> bool:
        """Determine if FP16 half-precision is supported and requested (CUDA only)."""
        resolved_dev = self.get_yolo_device()
        return self.yolo_half_precision and resolved_dev.startswith("cuda")

    def get_device_description(self) -> str:
        """Return human-readable execution device string, e.g. GPU: CUDA:0 FP16 (NVIDIA GeForce RTX 3050 Laptop GPU) or CPU (Intel Core i5-13420H)."""
        dev = self.get_yolo_device()
        if dev.startswith("cuda"):
            gpu_name = "NVIDIA GeForce RTX 3050 Laptop GPU"
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_name = torch.cuda.get_device_name(0)
            except Exception:
                pass
            fp16_str = "FP16" if self.is_half_precision() else "FP32"
            return f"GPU: CUDA:0 {fp16_str} ({gpu_name})"
        return "CPU: Intel Core i5-13420H"

    def get_yolo_model_path(self) -> str:
        """Resolve the model path, checking ml/models/ and root for yolo26n.pt."""
        p = Path(self.yolo_model)
        if p.exists():
            return str(p)
        in_models = self.models_dir / self.yolo_model
        if in_models.exists():
            return str(in_models)
        return self.yolo_model
