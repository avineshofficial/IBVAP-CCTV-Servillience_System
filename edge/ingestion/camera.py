"""
IBVAP — Camera Ingestion Module
================================
Handles video capture from RTSP streams, video files, or webcam.
Provides frames as an async-compatible generator.

Live sources (RTSP/webcam) are read on a background thread that always
keeps only the newest frame. Without this, cv2.VideoCapture's own
internal buffer quietly grows whenever a frame takes longer to process
than the camera's capture interval -- which happens as soon as
detection/tracking/face/ANPR are all running per frame -- and the feed
drifts further and further behind real time. File sources keep the
original paced, sequential read since a demo/test video should play
back in order, not skip around.
"""

import cv2
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Generator, Optional
import numpy as np

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
    Manages a video source (RTSP, file, or webcam) and yields frames.
    Supports auto-reconnection for network streams.
    """

    def __init__(
        self,
        source: str | int,
        camera_id: str = "cam_01",
        target_fps: int = 15,
        width: int = 1280,
        height: int = 720,
        max_reconnect_attempts: int = 5,
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

        # Live-source (RTSP/webcam) threaded capture state
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._capture_thread: Optional[threading.Thread] = None

    def _open(self) -> bool:
        """Open the video source."""
        try:
            if isinstance(self.source, int):
                self._cap = cv2.VideoCapture(self.source)
                self._is_file = False
                logger.info(f"[{self.camera_id}] Opened webcam device {self.source}")
            elif isinstance(self.source, str) and (
                self.source.startswith("rtsp://") or self.source.startswith("http")
            ):
                self._cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
                self._is_file = False
                logger.info(f"[{self.camera_id}] Opened RTSP stream: {self.source}")
            else:
                # File path
                path = Path(self.source)
                if not path.exists():
                    logger.error(f"[{self.camera_id}] Video file not found: {self.source}")
                    return False
                self._cap = cv2.VideoCapture(str(path))
                self._is_file = True
                logger.info(f"[{self.camera_id}] Opened video file: {self.source}")

            if self._cap is None or not self._cap.isOpened():
                logger.error(f"[{self.camera_id}] Failed to open source: {self.source}")
                return False

            # Set resolution for webcam/RTSP
            if not self._is_file:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                # Keep OpenCV's own internal buffer as small as possible so a
                # slow processing loop can't make it hoard stale frames.
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            return True

        except Exception as e:
            logger.error(f"[{self.camera_id}] Error opening source: {e}")
            return False

    def _reconnect(self) -> bool:
        """
        Attempt to reconnect to the source. May be called from the background
        capture thread itself, so this only touches self._cap -- never
        self._running or the thread object, to avoid a thread trying to stop
        or join itself.
        """
        if self._is_file:
            return False

        for attempt in range(1, self.max_reconnect_attempts + 1):
            logger.warning(
                f"[{self.camera_id}] Reconnection attempt {attempt}/{self.max_reconnect_attempts}..."
            )
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            time.sleep(self.reconnect_delay)
            if self._open():
                logger.info(f"[{self.camera_id}] Reconnected successfully")
                return True

        logger.error(f"[{self.camera_id}] All reconnection attempts failed")
        return False

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
        the camera provides them and always keeps only the latest one, so
        the consuming loop never sees a growing backlog of stale frames.
        """
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                if not self._reconnect():
                    self._running = False
                    return
                continue

            ret, frame = self._cap.read()
            if not ret:
                if not self._reconnect():
                    self._running = False
                    return
                continue

            with self._frame_lock:
                self._latest_frame = frame

    def _frames_from_live_source(self, frame_interval: float) -> Generator[FramePacket, None, None]:
        self._latest_frame = None
        self._capture_thread = threading.Thread(target=self._live_capture_loop, daemon=True)
        self._capture_thread.start()

        last_frame_time = 0.0
        try:
            while self._running:
                now = time.time()
                if frame_interval > 0 and (now - last_frame_time) < frame_interval:
                    time.sleep(0.001)
                    continue

                with self._frame_lock:
                    frame = None if self._latest_frame is None else self._latest_frame.copy()

                if frame is None:
                    # Camera thread hasn't delivered a first frame yet, or is
                    # mid-reconnect -- wait rather than yielding nothing.
                    time.sleep(0.01)
                    continue

                self._frame_count += 1
                last_frame_time = time.time()
                yield self._make_packet(frame)
        finally:
            self._running = False

    def _frames_from_file(self, frame_interval: float) -> Generator[FramePacket, None, None]:
        """Original synchronous, frame-paced read -- correct for demo video playback."""
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
            yield self._make_packet(frame)

    def frames(self) -> Generator[FramePacket, None, None]:
        """
        Yield frames from the video source.
        Handles frame rate limiting and auto-reconnection.
        """
        if not self._open():
            logger.error(f"[{self.camera_id}] Cannot start — source unavailable")
            return

        self._running = True
        self._start_time = time.time()
        self._frame_count = 0
        frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0

        logger.info(
            f"[{self.camera_id}] Starting capture at {self.target_fps} FPS "
            f"from {'file' if self._is_file else 'stream'}: {self.source}"
        )

        if self._is_file:
            yield from self._frames_from_file(frame_interval)
        else:
            yield from self._frames_from_live_source(frame_interval)

    def release(self):
        """Release the video capture resource and stop the capture thread if running."""
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
