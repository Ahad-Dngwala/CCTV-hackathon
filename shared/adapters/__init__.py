"""
shared.adapters package — exports the VMS adapter interface and types.

Import from here to avoid deep path coupling:
    from shared.adapters import BaseVMSAdapter, FramePacket, CameraMetadata, StreamHandle
"""

from shared.adapters.base import BaseVMSAdapter, CameraMetadata, FramePacket, StreamHandle

__all__ = [
    "BaseVMSAdapter",
    "CameraMetadata",
    "FramePacket",
    "StreamHandle",
]
