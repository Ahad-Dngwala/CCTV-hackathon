"""
CameraWorker — reads frames from one camera in a dedicated thread.

Connects via its adapter, reads frames in a loop, extracts PTS from
CAP_PROP_POS_MSEC (NEVER from time.time() or datetime.now()), and
puts FramePacket objects on a shared output queue non-blocking.

On any failure: disconnects, waits with exponential backoff, reconnects.
The supervisor creates and manages workers — one instance per camera.

CRITICAL PTS RULE:
    pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
    This is the ONLY valid source of frame timestamps in this codebase.
    Wall-clock time during the first 1-2 seconds of a reconnect produces
    impossible velocities and permanently breaks cross-camera tracking.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

import cv2

from shared.adapters.base import BaseVMSAdapter, FramePacket

logger = logging.getLogger(__name__)

RECONNECT_BASE_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 30.0


class CameraWorker:
    """
    Runs in its own thread. Connects to one camera via its adapter,
    reads frames, extracts PTS, and puts FramePackets onto the shared output queue.

    One instance per camera. The supervisor creates and manages these.
    """

    def __init__(
        self,
        adapter: BaseVMSAdapter,
        output_queue: queue.Queue,
        camera_id: str,
        source_grid_id: str,
    ) -> None:
        self._adapter = adapter
        self._output_queue = output_queue
        self._camera_id = camera_id
        self._source_grid_id = source_grid_id
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"camera-worker-{self._source_grid_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        backoff = RECONNECT_BASE_SECONDS
        while not self._stop_event.is_set():
            try:
                self._connect_and_read()
                backoff = RECONNECT_BASE_SECONDS   # reset only on clean exit
            except Exception as e:
                logger.warning(
                    f"[{self._source_grid_id}] Worker error: {e}. "
                    f"Reconnecting in {backoff:.1f}s"
                )
            if not self._stop_event.is_set():
                time.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_SECONDS)

    def _connect_and_read(self) -> None:
        """
        Connect and read frames until the stream fails or stop is requested.
        PTS comes from CAP_PROP_POS_MSEC — never from time.time().
        Decoder warnings on join are logged, never fatal.
        cap.read() returning ok=False is the only reconnect trigger.
        """
        if not self._adapter.connect():
            raise ConnectionError(
                f"[{self._source_grid_id}] connect() returned False"
            )

        stream = self._adapter.get_stream()
        cap: cv2.VideoCapture = stream.capture
        logger.info(f"[{self._source_grid_id}] Connected")

        pts_offset_ms = 0.0
        prev_raw_pts_ms = -1.0

        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    logger.warning(
                        f"[{self._source_grid_id}] cap.read() returned False — reconnecting"
                    )
                    break

                # PTS in milliseconds — THIS IS THE ONLY VALID TIMESTAMP SOURCE
                raw_pts_ms: float = cap.get(cv2.CAP_PROP_POS_MSEC)

                # Scene discontinuity / loop point handling (guide §3):
                # When video loops, raw PTS drops back to ~0ms.
                # Accumulate pts_offset_ms so downstream tracker receives continuous monotonic PTS.
                if prev_raw_pts_ms > 0 and raw_pts_ms < (prev_raw_pts_ms - 1000.0):
                    logger.info(
                        f"[{self._source_grid_id}] Scene discontinuity / loop point detected "
                        f"(raw_pts {raw_pts_ms:.1f}ms < prev {prev_raw_pts_ms:.1f}ms). Accumulating offset."
                    )
                    pts_offset_ms += prev_raw_pts_ms

                prev_raw_pts_ms = raw_pts_ms
                monotonic_pts_ms = raw_pts_ms + pts_offset_ms

                packet = FramePacket(
                    frame=frame,
                    pts_ms=monotonic_pts_ms,
                    camera_id=self._camera_id,
                    source_grid_id=self._source_grid_id,
                    width=frame.shape[1],
                    height=frame.shape[0],
                )

                try:
                    self._output_queue.put_nowait(packet)
                except queue.Full:
                    # Drop frame rather than block — slow consumer is analytics pipeline's problem
                    logger.debug(f"[{self._source_grid_id}] Queue full — frame dropped")

        finally:
            self._adapter.disconnect()
