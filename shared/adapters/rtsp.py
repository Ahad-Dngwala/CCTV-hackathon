"""
RTSPAdapter — primary camera adapter.

Connects to a government grid RTSP stream over TCP using OpenCV's
FFmpeg backend. One instance per camera; not thread-safe — each
CameraWorker creates and owns its own RTSPAdapter instance.

TCP transport is mandatory: UDP silently corrupts frames across
NAT/firewalls and is indistinguishable from model errors at demo time.
"""

from __future__ import annotations

import os

import cv2

from shared.adapters.base import BaseVMSAdapter, CameraMetadata, StreamHandle


class RTSPAdapter(BaseVMSAdapter):
    """
    Primary adapter. Uses OpenCV + FFmpeg backend over TCP.
    One instance per camera. Not thread-safe — each worker owns its own instance.
    """

    def __init__(
        self,
        rtsp_url: str,
        source_grid_id: str,
        camera_id: str,
        catalogue_metadata: CameraMetadata,
    ) -> None:
        self._rtsp_url = rtsp_url
        self._source_grid_id = source_grid_id
        self._camera_id = camera_id
        self._catalogue_meta = catalogue_metadata   # grid-provided values, more reliable than OpenCV props
        self._cap: cv2.VideoCapture | None = None

    def connect(self) -> bool:
        """Force TCP. Set before VideoCapture construction — env var is read at init time."""
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        self._cap = cv2.VideoCapture(self._rtsp_url, cv2.CAP_FFMPEG)
        return self._cap is not None and self._cap.isOpened()

    def get_stream(self) -> StreamHandle:
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError(
                f"RTSPAdapter.get_stream() called before successful connect() for {self._rtsp_url}"
            )
        return StreamHandle(
            capture=self._cap,
            camera_id=self._camera_id,
            source_grid_id=self._source_grid_id,
        )

    def get_metadata(self) -> CameraMetadata:
        """
        Prefer catalogue values (more reliable) over OpenCV-reported values.
        Width/height from OpenCV are fine; fps from OpenCV is NOT reliable — use catalogue fps.
        """
        if self._cap is None:
            return self._catalogue_meta
        return CameraMetadata(
            source_grid_id=self._source_grid_id,
            rtsp_url=self._rtsp_url,
            codec=self._catalogue_meta.codec,
            width=int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self._catalogue_meta.width,
            height=int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self._catalogue_meta.height,
            fps=self._catalogue_meta.fps,   # use catalogue value — DO NOT use CAP_PROP_FPS
            bitrate_kbps=self._catalogue_meta.bitrate_kbps,
            location_label=self._catalogue_meta.location_label,
        )

    def disconnect(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
