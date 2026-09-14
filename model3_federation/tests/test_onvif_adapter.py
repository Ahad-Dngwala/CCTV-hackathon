"""
Unit tests for model3_federation/adapters/onvif_vms_adapter.py.

No DB, no real ONVIF hardware: `onvif` (the onvif-zeep-async package)
is imported lazily inside OnvifVMSAdapter._ensure_camera() specifically
so it doesn't have to be installed unless this adapter type is
actually used -- which also means it doesn't have to be installed to
test the adapter's own logic. These tests inject a fake `onvif` module
into sys.modules with a fake ONVIFCamera matching the real package's
documented call shape (update_xaddrs() awaited, create_media_service()
/ create_devicemgmt_service() are synchronous factories whose
individual operations are what's awaitable -- see the fix in this same
change: create_media_service() was incorrectly awaited before this).

This verifies the adapter's own mapping/error-handling logic against
that documented shape. It does NOT verify the real onvif-zeep-async
package still matches that shape, or that any particular camera/NVR
speaks ONVIF exactly the way the spec says -- that needs a real device
or an ONVIF simulator, flagged the same way in the adapter's own
module docstring.
"""

import asyncio
import sys
import types

import pytest

from model3_federation.schemas.models import FederatedEvent


def _run(coro):
    return asyncio.run(coro)


class _FakeDeviceMgmt:
    def __init__(self, info=None, raise_on_info=None):
        self._info = info or types.SimpleNamespace(Manufacturer="FakeVendor", Model="FakeModel")
        self._raise_on_info = raise_on_info

    async def GetDeviceInformation(self):
        if self._raise_on_info:
            raise self._raise_on_info
        return self._info


class _FakeMedia:
    def __init__(self, profiles=None, stream_uris=None, raise_on_profiles=None):
        self._profiles = profiles or []
        self._stream_uris = stream_uris or {}
        self._raise_on_profiles = raise_on_profiles

    async def GetProfiles(self):
        if self._raise_on_profiles:
            raise self._raise_on_profiles
        return self._profiles

    async def GetStreamUri(self, params):
        token = params["ProfileToken"]
        if token in self._stream_uris:
            return types.SimpleNamespace(Uri=self._stream_uris[token])
        raise RuntimeError(f"no stream configured for {token}")


class _FakeONVIFCamera:
    """Stand-in for onvif.ONVIFCamera. Constructor and update_xaddrs()
    match the real package's documented signature; create_media_service()/
    create_devicemgmt_service() are sync factories, same as the real
    package (see the adapter fix this change also makes)."""

    instances = []  # so tests can assert on how the adapter constructed it

    def __init__(self, host, port, username, password, media=None, devicemgmt=None, fail_update_xaddrs=False):
        self.host, self.port, self.username, self.password = host, port, username, password
        self._media = media or _FakeMedia()
        self._devicemgmt = devicemgmt or _FakeDeviceMgmt()
        self._fail_update_xaddrs = fail_update_xaddrs
        _FakeONVIFCamera.instances.append(self)

    async def update_xaddrs(self):
        if self._fail_update_xaddrs:
            raise ConnectionError("simulated: device unreachable")

    def create_media_service(self):
        return self._media

    def create_devicemgmt_service(self):
        return self._devicemgmt


@pytest.fixture(autouse=True)
def fake_onvif_module(monkeypatch):
    """Installs a fake `onvif` module for the duration of each test, and
    lets each test configure the *next* ONVIFCamera instance's behavior
    via `fake_onvif_module.next_kwargs`. Reverted automatically after
    each test (both the sys.modules entry and the instances list)."""
    _FakeONVIFCamera.instances = []
    next_kwargs = {}

    def _factory(host, port, username, password):
        return _FakeONVIFCamera(host, port, username, password, **next_kwargs)

    fake_module = types.ModuleType("onvif")
    fake_module.ONVIFCamera = _factory
    monkeypatch.setitem(sys.modules, "onvif", fake_module)

    fake_factory = types.SimpleNamespace(next_kwargs=next_kwargs)
    yield fake_factory


def _adapter(config=None):
    from model3_federation.adapters.onvif_vms_adapter import OnvifVMSAdapter
    return OnvifVMSAdapter("sys-onvif-1", "Test NVR", config or {
        "host": "10.0.0.5", "port": 8000, "username": "admin", "password": "hunter2",
    })


def test_connect_missing_config_fails_without_touching_network():
    adapter = _adapter(config={"host": "10.0.0.5"})  # no username/password
    assert _run(adapter.connect()) is False
    assert _FakeONVIFCamera.instances == []  # never even tried


def test_connect_success(fake_onvif_module):
    adapter = _adapter()
    assert _run(adapter.connect()) is True
    assert len(_FakeONVIFCamera.instances) == 1
    cam = _FakeONVIFCamera.instances[0]
    assert (cam.host, cam.port, cam.username, cam.password) == ("10.0.0.5", 8000, "admin", "hunter2")


def test_connect_failure_when_device_unreachable(fake_onvif_module):
    fake_onvif_module.next_kwargs["fail_update_xaddrs"] = True
    adapter = _adapter()
    assert _run(adapter.connect()) is False


def test_connect_failure_when_devicemgmt_call_raises(fake_onvif_module):
    fake_onvif_module.next_kwargs["devicemgmt"] = _FakeDeviceMgmt(raise_on_info=RuntimeError("SOAP fault"))
    adapter = _adapter()
    assert _run(adapter.connect()) is False


def test_get_cameras_before_connect_returns_empty():
    adapter = _adapter()
    assert _run(adapter.get_cameras()) == []


def test_get_cameras_maps_profiles_to_federated_cameras(fake_onvif_module):
    profiles = [
        types.SimpleNamespace(token="Profile_1", Name="Main Stream"),
        types.SimpleNamespace(token="Profile_2", Name="Sub Stream"),
    ]
    stream_uris = {
        "Profile_1": "rtsp://10.0.0.5:554/Streaming/Channels/101",
        "Profile_2": "rtsp://10.0.0.5:554/Streaming/Channels/102",
    }
    fake_onvif_module.next_kwargs["media"] = _FakeMedia(profiles=profiles, stream_uris=stream_uris)

    adapter = _adapter()
    _run(adapter.connect())
    cameras = _run(adapter.get_cameras())

    assert [c.external_id for c in cameras] == ["Profile_1", "Profile_2"]
    assert [c.name for c in cameras] == ["Main Stream", "Sub Stream"]
    assert cameras[0].location_label == "rtsp://10.0.0.5:554/Streaming/Channels/101"
    assert all(c.lat is None and c.lng is None for c in cameras)  # ONVIF media profiles carry no GPS
    assert all(c.is_active is True for c in cameras)
    assert all(c.system_name == "Test NVR" for c in cameras)


def test_get_cameras_profile_without_name_falls_back(fake_onvif_module):
    profiles = [types.SimpleNamespace(token="Profile_9", Name=None)]
    fake_onvif_module.next_kwargs["media"] = _FakeMedia(profiles=profiles, stream_uris={})
    adapter = _adapter()
    _run(adapter.connect())
    cameras = _run(adapter.get_cameras())
    assert cameras[0].name == "Test NVR — Profile_9"


def test_get_cameras_continues_when_one_profiles_stream_uri_fails(fake_onvif_module):
    """A single profile's GetStreamUri failing (e.g. that channel is
    misconfigured) shouldn't drop the whole camera or crash the call --
    just that one camera's location_label stays unset."""
    profiles = [
        types.SimpleNamespace(token="Profile_ok", Name="OK Cam"),
        types.SimpleNamespace(token="Profile_bad", Name="Bad Cam"),
    ]
    stream_uris = {"Profile_ok": "rtsp://10.0.0.5:554/ok"}  # Profile_bad deliberately missing
    fake_onvif_module.next_kwargs["media"] = _FakeMedia(profiles=profiles, stream_uris=stream_uris)

    adapter = _adapter()
    _run(adapter.connect())
    cameras = _run(adapter.get_cameras())

    assert len(cameras) == 2
    assert cameras[0].location_label == "rtsp://10.0.0.5:554/ok"
    assert cameras[1].location_label is None


def test_get_cameras_returns_empty_when_get_profiles_fails(fake_onvif_module):
    fake_onvif_module.next_kwargs["media"] = _FakeMedia(raise_on_profiles=RuntimeError("SOAP fault"))
    adapter = _adapter()
    _run(adapter.connect())
    assert _run(adapter.get_cameras()) == []


def test_event_stream_emits_heartbeat_per_camera_then_cancels_cleanly(fake_onvif_module, monkeypatch):
    import model3_federation.adapters.onvif_vms_adapter as mod
    monkeypatch.setattr(mod, "_POLL_INTERVAL_SECONDS", 0)

    profiles = [types.SimpleNamespace(token="Profile_1", Name="Cam One")]
    fake_onvif_module.next_kwargs["media"] = _FakeMedia(profiles=profiles, stream_uris={})
    adapter = _adapter()
    _run(adapter.connect())

    received: list[FederatedEvent] = []

    async def _callback(event: FederatedEvent) -> None:
        received.append(event)

    async def _scenario():
        task = asyncio.create_task(adapter.start_event_stream(_callback))
        for _ in range(50):
            await asyncio.sleep(0)
            if received:
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    _run(_scenario())

    assert len(received) >= 1
    assert received[0].camera_external_id == "Profile_1"
    assert received[0].event_type == "camera_heartbeat"


def test_registered_adapter_type():
    from model3_federation.adapters.onvif_vms_adapter import OnvifVMSAdapter
    assert OnvifVMSAdapter.adapter_type == "onvif"
