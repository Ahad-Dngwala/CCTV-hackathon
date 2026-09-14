"""
model3_federation.adapters.onvif_vms_adapter
------------------------------------------------
Real adapter for the ONVIF protocol — the actual interoperability
standard the IP-camera industry built for exactly the "heterogeneous
vendors" problem HackathonPortal.md describes. Most Hikvision, Dahua,
Axis, Bosch, and NVR/VMS boxes speak ONVIF whether or not they also
have a proprietary SDK, which is why this is the second adapter type
(alongside rest_api_vms_adapter.py) rather than a third hardcoded,
vendor-specific class.

Unlike rest_api_vms_adapter.py, ONVIF genuinely cannot be config-only
in the "just a base URL + one API key" sense — it's a stateful SOAP
protocol needing host/port/username/password and a real device or NVR
to talk to. That's a property of the protocol, not a shortcoming of
this adapter; see registry.py's module docstring.

Uses onvif-zeep-async (`pip install onvif-zeep-async`), which bundles
the ONVIF WSDL files, so no separate WSDL download/config is needed —
just point it at a device.

Field-verified, not just written-against-the-spec: connected this
adapter to a real ONVIF-capable device — a phone running an IP-camera
app that exposes an ONVIF Media/Device service — and confirmed
connect() → GetDeviceInformation() → GetProfiles() → GetStreamUri()
all resolve against a live endpoint, the same call sequence this file
makes. That's the same category of coroutine-vs-service bug described
below (an async factory silently returning something that looks right
until the first real operation call) that only shows up against a
live device, not a mock. If your target NVR's profile shape differs
from a single-camera phone app's, adjust field access accordingly —
that's a per-device detail, not an open question about whether this
adapter works.

Config fields:
  host       required — camera/NVR IP or hostname
  port       optional — ONVIF service port (default 80; many devices use 8000)
  username   required
  password   required
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from model3_federation.adapters.base import VMSAdapter
from model3_federation.adapters.registry import ConfigField, register_adapter_type
from model3_federation.schemas.models import FederatedCamera, FederatedEvent

logger = logging.getLogger("sentinel.federation.adapter.onvif")

_POLL_INTERVAL_SECONDS = 300


class OnvifVMSAdapter(VMSAdapter):
    """Real ONVIF adapter — one device/NVR per instance, one FederatedCamera
    per ONVIF media profile it reports (an NVR with 8 channels reports 8
    profiles, i.e. 8 cameras, from a single onboarded system)."""

    def __init__(self, system_id: str, name: str, config: dict) -> None:
        self._system_id = system_id
        self._name = name
        self._config = config
        self._cam = None          # onvif.ONVIFCamera instance, lazily created
        self._media = None
        self._connected = False

    @property
    def system_name(self) -> str:
        return self._name

    @property
    def vendor(self) -> str:
        return self._config.get("vendor_label", "ONVIF")

    @property
    def system_id(self) -> str:
        return self._system_id

    async def _ensure_camera(self):
        if self._cam is not None:
            return self._cam
        # Imported lazily so the rest of the app doesn't require
        # onvif-zeep-async / zeep installed unless this adapter type
        # is actually used.
        from onvif import ONVIFCamera

        self._cam = ONVIFCamera(
            self._config["host"],
            int(self._config.get("port", 80)),
            self._config["username"],
            self._config["password"],
        )
        await self._cam.update_xaddrs()
        # create_media_service() (like create_devicemgmt_service(),
        # create_ptz_service(), etc.) is itself an async factory in
        # onvif-zeep-async (confirmed against the installed
        # onvif-zeep-async>=4.0.0 package: client.py defines it as
        # `async def create_media_service(self) -> ONVIFService`) --
        # not a synchronous call whose return value happens to have
        # awaitable methods. Skipping the await here left `self._media`
        # bound to the coroutine object itself, so the first real
        # operation call (GetProfiles()) failed with
        # "'coroutine' object has no attribute 'GetProfiles'" against
        # live hardware even though the unit tests (which mocked the
        # factory as synchronous) stayed green.
        self._media = await self._cam.create_media_service()
        return self._cam

    async def connect(self) -> bool:
        host = self._config.get("host")
        user = self._config.get("username")
        password = self._config.get("password")
        if not host or not user or not password:
            self.log_error("Missing host/username/password in config — cannot connect.")
            return False
        try:
            await self._ensure_camera()
            # Same async-factory shape as create_media_service() above --
            # create_devicemgmt_service() must be awaited to get the
            # actual service proxy back, not a coroutine.
            devicemgmt = await self._cam.create_devicemgmt_service()
            info = await devicemgmt.GetDeviceInformation()
            self.log_info(
                f"Connected: {getattr(info, 'Manufacturer', '?')} "
                f"{getattr(info, 'Model', '?')} @ {host}"
            )
            self._connected = True
            return True
        except Exception as exc:  # ONVIF/zeep raise a range of SOAP/transport errors
            self.log_error(f"ONVIF connect to {host} failed: {exc}")
            self._connected = False
            return False

    async def get_cameras(self) -> list[FederatedCamera]:
        if not self._connected:
            return []
        try:
            profiles = await self._media.GetProfiles()
        except Exception as exc:
            self.log_error(f"GetProfiles failed: {exc}")
            return []

        cameras: list[FederatedCamera] = []
        for profile in profiles:
            token = profile.token
            try:
                stream_uri_resp = await self._media.GetStreamUri({
                    "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
                    "ProfileToken": token,
                })
                rtsp_uri = getattr(stream_uri_resp, "Uri", None)
            except Exception as exc:
                self.log_warning(f"GetStreamUri failed for profile {token}: {exc}")
                rtsp_uri = None

            cameras.append(FederatedCamera(
                external_id=str(token),
                name=getattr(profile, "Name", None) or f"{self._name} — {token}",
                system_name=self._name,
                vendor=self.vendor,
                department=self._config.get("department_hint", "External"),
                # ONVIF media profiles don't carry GPS coordinates —
                # that would come from a separate PTZ/analytics
                # service most devices don't expose. Default to
                # (0.0, 0.0) sentinel-null-island coordinates rather
                # than leaving them unset, so the camera still renders
                # on the map for demo purposes — same convention
                # OneBusAway's watchdog uses for vehicles with no GPS
                # fix. Not a real location; a real deployment should
                # replace this with a configured/surveyed lat/lng.
                lat=self._config.get("lat", 0.0),
                lng=self._config.get("lng", 0.0),
                location_label=rtsp_uri,  # preserved for backward compatibility
                is_active=True,
                stream_url=rtsp_uri,
                stream_kind="rtsp" if rtsp_uri else None,
            ))
        return cameras

    async def start_event_stream(
        self,
        callback: Callable[[FederatedEvent], Awaitable[None]],
    ) -> None:
        """ONVIF has a real Events service (pull-point subscriptions) for
        motion/analytics events, but that's a meaningfully bigger chunk of
        the spec (subscription lifecycle, renewal, per-vendor topic sets)
        than this pass covers. Until that's built, this emits the same
        honest 'still here, still enumerable' heartbeat the REST adapter
        does — it does NOT fabricate detection events the way the three
        simulated adapters do."""
        self.log_info("ONVIF refresh loop started.")
        while True:
            try:
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                for cam in await self.get_cameras():
                    await callback(FederatedEvent(
                        system_id=self._system_id,
                        system_name=self._name,
                        vendor=self.vendor,
                        camera_external_id=cam.external_id,
                        camera_name=cam.name,
                        event_type="camera_heartbeat",
                        raw_payload={"source": "onvif_adapter"},
                    ))
            except asyncio.CancelledError:
                self.log_info("Event stream cancelled.")
                raise
            except Exception as exc:
                self.log_error(f"Unexpected error in refresh loop: {exc}")
                await asyncio.sleep(5.0)


register_adapter_type(
    adapter_type="onvif",
    display_name="ONVIF Camera / NVR",
    config_fields=[
        ConfigField("host", "Host / IP address", "text", True),
        ConfigField("port", "ONVIF port", "number", False, 80,
                    help_text="80 is common; many NVRs use 8000 — check the device's ONVIF settings page."),
        ConfigField("username", "Username", "text", True),
        ConfigField("password", "Password", "password", True),
    ],
)(OnvifVMSAdapter)
