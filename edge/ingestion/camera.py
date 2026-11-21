"""
IBVAP — Camera Ingestion Module
================================
Handles video capture from RTSP streams, video files, or webcams.
Provides frames as an async-compatible generator.

Supports intelligent Windows DirectShow / MSMF auto-probing, resilient reconnection,
and continuous polling so the edge engine seamlessly attaches to your built-in or USB webcam.
"""

import os
import sys
import cv2
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Generator, Optional, Tuple
import numpy as np

# Suppress verbose DirectShow/MSMF backend warnings on Windows
os.environ["OPENCV_LOG_LEVEL"] = "ERROR"

# Low-latency FFMPEG capture options for RTSP/network streams (must be set before VideoCapture)
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|analyzeduration;0|probesize;32768",
)

logger = logging.getLogger(__name__)


@dataclass
class FramePacket:
    """A single captured frame with metadata."""
    frame: np.ndarray
    frame_id: int
    timestamp: float
    camera_id: str
    width: int
    height: int
    fps: float
    source: str


class CameraStream:
    """
    Manages a video source (RTSP, file, or live webcam) and yields frames.
    Supports auto-reconnection and device auto-detection.
    """

    def __init__(
        self,
        source: str | int,
        camera_id: str = "cam_01",
        target_fps: int = 15,
        width: int = 1280,
        height: int = 720,
        max_reconnect_attempts: int = 10,
        reconnect_delay: float = 2.0,
    ):
        self.source = source
        self.camera_id = camera_id
        self.target_fps = target_fps
        self.width = width
        self.height = height
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay

        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_count = 0
        self._start_time = 0.0
        self._is_file = False
        self._running = False
        self._active_index: Optional[int] = None

        # Live-source (RTSP/webcam) threaded capture state
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_raw_frame: Optional[np.ndarray] = None
        self._latest_raw_seq: int = 0
        self._latest_raw_ts: float = 0.0
        self._frame_lock = threading.Lock()
        self._new_frame_event = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None

    def _is_webcam_source(self) -> bool:
        """Check if source refers to a local webcam device."""
        if isinstance(self.source, int):
            return True
        if isinstance(self.source, str):
            s = self.source.strip().lower()
            if s.isdigit() or s in ("webcam", "auto", "cam", "live", "usb", "external", ""):
                return True
        return False

    def _get_preferred_webcam_index(self) -> Optional[int]:
        """Extract user-requested webcam index if specified."""
        if isinstance(self.source, int):
            return self.source
        if isinstance(self.source, str):
            s = self.source.strip().lower()
            if s.isdigit():
                return int(s)
            if s in ("usb", "external"):
                return 1  # Standard external USB camera index on Windows laptops
        return None

    def _probe_webcam(self) -> bool:
        """
        Scan webcam devices on Windows using DirectShow (cv2.CAP_DSHOW),
        Media Foundation (cv2.CAP_MSMF), and default backends.
        Evaluates real frame visual luminance to distinguish active optical
        feeds from dark/covered sensors or closed privacy shutters.
        """
        preferred = self._get_preferred_webcam_index()
        all_possible_indices = [0, 1, 2, 3]
        indices_to_test = [preferred] if preferred is not None else []
        for i in all_possible_indices:
            if i not in indices_to_test:
                indices_to_test.append(i)

        # Prioritize DirectShow (CAP_DSHOW) on Windows — rock-solid UVC stability, eliminates MSMF stride assertions
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, 0] if sys.platform == "win32" else [0]
        fallback_cap = None
        fallback_idx = None
        fallback_backend = ""

        logger.info(f"[{self.camera_id}] Scanning camera devices on indices {indices_to_test}...")

        for idx in indices_to_test:
            for backend in backends:
                cap = None
                backend_name = "DirectShow" if backend == cv2.CAP_DSHOW else ("MSMF" if backend == cv2.CAP_MSMF else "Default")
                logger.info(f"[{self.camera_id}] Probing camera index {idx} ({backend_name})...")
                try:
                    cap = cv2.VideoCapture(idx, backend) if backend != 0 else cv2.VideoCapture(idx)
                    if cap is None or not cap.isOpened():
                        logger.info(f"[{self.camera_id}] ❌ Index {idx} ({backend_name}) could not be opened.")
                        continue

                    # Configure MJPG format & requested resolution for clean, smooth 30 FPS streaming
                    try:
                        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    except Exception:
                        pass
                    try:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                        cap.set(cv2.CAP_PROP_FPS, max(30, int(self.target_fps)))
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffer for zero-lag latest-frame capture
                    except Exception:
                        pass

                    # Allow hardware sensor and auto-exposure to wake up
                    time.sleep(0.3)
                    for _ in range(3):
                        cap.read()

                    ret, test_frame = cap.read()
                    if not ret or test_frame is None or test_frame.size == 0:
                        logger.info(f"[{self.camera_id}] ℹ️ Camera index {idx} ({backend_name}) opened but frame read failed.")
                        cap.release()
                        continue

                    brightness = float(np.mean(test_frame))
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or test_frame.shape[1])
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or test_frame.shape[0])

                    # 1. If camera has active visual light (> 2.0), this backend successfully turned on the camera!
                    if brightness > 2.0:
                        logger.info(
                            f"[{self.camera_id}] ✅ Connected to active optical camera on index {idx} via {backend_name} "
                            f"({w}x{h} @ {self.target_fps}fps, active visual stream, mean luminance: {brightness:.1f})"
                        )
                        self._cap = cap
                        self._is_file = False
                        self._active_index = idx
                        if fallback_cap is not None and fallback_cap is not cap:
                            fallback_cap.release()
                        return True

                    # 2. If frame is dark (mean <= 2.0), log diagnostic and try alternative backends / indices
                    logger.info(
                        f"[{self.camera_id}] ℹ️ Camera index {idx} ({backend_name}) opened but frame is dark (mean: {brightness:.1f}). "
                        "Checking alternative backend/index..."
                    )
                    if fallback_cap is None or (preferred is not None and idx == preferred and fallback_idx != preferred):
                        if fallback_cap is not None and fallback_cap is not cap:
                            fallback_cap.release()
                        fallback_cap = cap
                        fallback_idx = idx
                        fallback_backend = backend_name
                    else:
                        cap.release()

                except Exception as e:
                    logger.debug(f"[{self.camera_id}] Error testing index {idx} ({backend_name}): {e}")
                    if cap is not None and cap is not fallback_cap:
                        try:
                            cap.release()
                        except Exception:
                            pass

        # If no index had brightness > 2.0, fall back to the preferred or first open device
        if fallback_cap is not None:
            self._cap = fallback_cap
            self._is_file = False
            self._active_index = fallback_idx
            logger.warning(
                f"[{self.camera_id}] ⚠️ Camera index {fallback_idx} ({fallback_backend}) is returning a dark frame. "
                "💡 If feed is black, check: (1) Lenovo 300 FHD top physical slider, (2) Windows Settings > Privacy & security > Camera > 'Let desktop apps access camera' ON, (3) Lenovo Vantage Privacy Mode OFF."
            )
            return True

        return False

    def _open(self) -> bool:
        """Open the video source."""
        try:
            if self._is_webcam_source():
                return self._probe_webcam()
            elif isinstance(self.source, str) and (
                self.source.startswith("rtsp://") or self.source.startswith("http")
            ):
                self._cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                self._is_file = False
                if self._cap is not None and self._cap.isOpened():
                    logger.info(f"[{self.camera_id}] Opened network stream: {self.source}")
                    self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    return True
                return False
            else:
                # Video File path
                path = Path(self.source)
                if not path.exists():
                    logger.error(f"[{self.camera_id}] Video file not found: {self.source}")
                    return False
                self._cap = cv2.VideoCapture(str(path))
                self._is_file = True
                if self._cap is not None and self._cap.isOpened():
                    logger.info(f"[{self.camera_id}] Opened video file: {self.source}")
                    return True
                return False

        except Exception as e:
            logger.error(f"[{self.camera_id}] Error opening source: {e}")
            return False

    def _reconnect(self) -> bool:
        """Attempt to reconnect to the source."""
        if self._is_file:
            return False

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        time.sleep(self.reconnect_delay)
        return self._open()

    def _make_packet(self, frame: np.ndarray) -> FramePacket:
        """Resize if needed and wrap a raw frame into a FramePacket."""
        h, w = frame.shape[:2]
        if w != self.width or h != self.height:
            frame = cv2.resize(frame, (self.width, self.height))
            h, w = self.height, self.width

        elapsed = time.time() - self._start_time
        current_fps = self._frame_count / elapsed if elapsed > 0 else 0

        return FramePacket(
            frame=frame,
            frame_id=self._frame_count,
            timestamp=time.time(),
            camera_id=self.camera_id,
            width=w,
            height=h,
            fps=round(current_fps, 1),
            source=str(self.source),
        )

    def _live_capture_loop(self):
        """
        Background thread for RTSP/webcam sources: pulls frames as fast as
        the camera provides them and signals when a fresh frame is ready.
        """
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                if not self._reconnect():
                    time.sleep(0.5)
                continue

            try:
                if not self._cap.grab():
                    ret, frame = False, None
                else:
                    ret, frame = self._cap.retrieve()
            except Exception as e:
                logger.warning(f"[{self.camera_id}] Frame read exception: {e}. Reconnecting...")
                if self._cap is not None:
                    try:
                        self._cap.release()
                    except Exception:
                        pass
                    self._cap = None
                time.sleep(0.5)
                continue

            if not ret or frame is None or frame.size == 0:
                logger.warning(f"[{self.camera_id}] Frame signal interrupted. Reconnecting...")
                if self._cap is not None:
                    try:
                        self._cap.release()
                    except Exception:
                        pass
                    self._cap = None
                time.sleep(0.5)
                continue

            now_mono = time.monotonic()
            with self._frame_lock:
                self._latest_frame = frame
                self._latest_raw_frame = frame
                self._latest_raw_seq += 1
                self._latest_raw_ts = now_mono
                self._new_frame_event.set()

    def _frames_from_live_source(self, frame_interval: float) -> Generator[FramePacket, None, None]:
        self._latest_frame = None
        self._new_frame_event.clear()
        self._capture_thread = threading.Thread(target=self._live_capture_loop, daemon=True)
        self._capture_thread.start()

        try:
            while self._running:
                # Wait for next fresh frame from camera hardware (max 100ms)
                if not self._new_frame_event.wait(timeout=0.1):
                    continue

                with self._frame_lock:
                    self._new_frame_event.clear()
                    frame = self._latest_frame
                    self._latest_frame = None

                if frame is None:
                    continue

                self._frame_count += 1
                yield self._make_packet(frame)
        finally:
            self._running = False

    def _frames_from_file(self, frame_interval: float) -> Generator[FramePacket, None, None]:
        """Synchronous, frame-paced read for recorded video playback."""
        last_frame_time = 0.0
        while self._running:
            now = time.time()
            if frame_interval > 0 and (now - last_frame_time) < frame_interval:
                time.sleep(0.001)
                continue

            ret, frame = self._cap.read()
            if not ret:
                logger.info(f"[{self.camera_id}] Video ended, looping...")
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            self._frame_count += 1
            last_frame_time = time.time()
            now_mono = time.monotonic()
            with self._frame_lock:
                self._latest_raw_frame = frame
                self._latest_raw_seq += 1
                self._latest_raw_ts = now_mono
            yield self._make_packet(frame)

    def frames(self) -> Generator[FramePacket, None, None]:
        """
        Yield frames from the video source.
        If a webcam source is specified but not yet connected,
        gracefully polls until the webcam becomes available.
        """
        if not self._open():
            if self._is_webcam_source():
                logger.info("=" * 60)
                logger.info(f"[{self.camera_id}] 📡 WAITING FOR WEBCAM CONNECTION...")
                logger.info("    💡 Ensure your built-in or USB webcam is connected and not in use by another app.")
                logger.info("    (The system will automatically detect the stream when connected)")
                logger.info("=" * 60)

                self._running = True
                while self._running:
                    time.sleep(2.0)
                    if self._open():
                        break
            else:
                logger.error(f"[{self.camera_id}] Cannot start — source unavailable: {self.source}")
                return

        if self._cap is None or not self._cap.isOpened():
            return

        self._running = True
        self._start_time = time.time()
        self._frame_count = 0
        frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0

        logger.info(
            f"[{self.camera_id}] Ingestion active at {self.target_fps} FPS "
            f"from {'file' if self._is_file else 'live camera stream'}"
        )

        if self._is_file:
            yield from self._frames_from_file(frame_interval)
        else:
            yield from self._frames_from_live_source(frame_interval)

    def get_latest_raw_frame(self) -> Optional[Tuple[int, float, np.ndarray]]:
        """Non-blocking read of the freshest captured raw frame (seq, monotonic_ts, frame).

        Does NOT clear or steal frames from the inference generator `frames()`,
        allowing a dedicated live-stream renderer thread to run at a steady 25+ FPS
        independently of AI inference latency.
        """
        with self._frame_lock:
            if self._latest_raw_frame is None:
                return None
            return (self._latest_raw_seq, self._latest_raw_ts, self._latest_raw_frame)

    def release(self):
        """Release camera and capture thread resources."""
        self._running = False
        if (
            self._capture_thread is not None
            and self._capture_thread.is_alive()
            and threading.current_thread() is not self._capture_thread
        ):
            self._capture_thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info(f"[{self.camera_id}] Released camera resource")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def __del__(self):
        self.release()
