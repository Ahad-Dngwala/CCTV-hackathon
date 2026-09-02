"""
HLSAdapter — secondary camera adapter for HLS streams (.m3u8).

Used for remote fallback when RTSP ports (8554) are restricted or firewalled,
or when connecting via CDN endpoints (e.g. https://cctv.corp8.cloud/<id>/index.m3u8).
"""

from __future__ import annotations

import cv2

from shared.adapters.base import BaseVMSAdapter, CameraMetadata, StreamHandle


class HLSAdapter(BaseVMSAdapter):
    """
    HLS adapter. Uses OpenCV + FFmpeg backend to pull HLS (.m3u8) streams.
    One instance per camera worker.
    """

    def __init__(
        self,
        hls_url: str,
        source_grid_id: str,
        camera_id: str,
        catalogue_metadata: CameraMetadata,
    ) -> None:
        self._hls_url = hls_url
        self._source_grid_id = source_grid_id
        self._camera_id = camera_id
        self._catalogue_meta = catalogue_metadata
        self._cap: cv2.VideoCapture | None = None

    def connect(self) -> bool:
        """Connect to the HLS (.m3u8) endpoint via OpenCV FFmpeg."""
        self._cap = cv2.VideoCapture(self._hls_url, cv2.CAP_FFMPEG)
        return self._cap is not None and self._cap.isOpened()

    def get_stream(self) -> StreamHandle:
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError(
                f"HLSAdapter.get_stream() called before successful connect() for {self._hls_url}"
            )
        return StreamHandle(
            capture=self._cap,
            camera_id=self._camera_id,
            source_grid_id=self._source_grid_id,
        )

    def get_metadata(self) -> CameraMetadata:
        if self._cap is None:
            return self._catalogue_meta
        return CameraMetadata(
            source_grid_id=self._source_grid_id,
            rtsp_url=self._catalogue_meta.rtsp_url,
            codec=self._catalogue_meta.codec,
            width=int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self._catalogue_meta.width,
            height=int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self._catalogue_meta.height,
            fps=self._catalogue_meta.fps,
            bitrate_kbps=self._catalogue_meta.bitrate_kbps,
            location_label=self._catalogue_meta.location_label,
        )

    def disconnect(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
