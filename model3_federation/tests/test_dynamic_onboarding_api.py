"""
Integration tests for the config-driven onboarding endpoints added
alongside adapters/registry.py: GET /api/v3/adapter-types,
POST /api/v3/systems/test-connection, and POST /api/v3/systems when
called WITH adapter_type+config (the original record-only behavior,
called without those, is covered by test_systems_api.py already).

Uses a test-only fake adapter type ("test_fake", registered below via
the same register_adapter_type() decorator every real adapter type
uses) instead of Windy/ONVIF, so these never touch real network or
real hardware -- same spirit as test_registration.py's FakeAdapter,
extended to also be config-driven/registry-constructible.

load_dynamic_adapters() (the restart-survival path) is NOT covered
here yet: it runs its DB work in a thread executor against a session
opened from a factory, and getting that to interact correctly with
this test suite's SAVEPOINT-based per-test rollback (db_session
fixture, model1-registry/tests/conftest.py) needs verifying against a
real DB run, not guessing blind. What IS covered here -- that
POST /systems with adapter_type persists adapter_type/config exactly
as load_dynamic_adapters() would need to read them back
(test_create_with_adapter_type_connects_and_saves_cameras) -- is real
coverage of the data it depends on, just not the restart path itself.

Needs the same real Postgres sentinel_test setup as model1-registry/tests
(see this directory's conftest.py docstring).
"""

import uuid

from sqlalchemy import text

from model3_federation.adapters.base import VMSAdapter
from model3_federation.adapters.registry import ConfigField, register_adapter_type
from model3_federation.schemas.models import FederatedCamera


class FakeConfigurableAdapter(VMSAdapter):
    """connect() succeeds unless config['should_connect'] is falsy;
    get_cameras() returns config['camera_count'] (default 2) synthetic
    cameras. No network, no real credentials -- config is just numbers/
    flags a test can set."""

    def __init__(self, system_id: str, name: str, config: dict):
        self._system_id = system_id
        self._name = name
        self._config = config
        self._connected = False

    @property
    def system_name(self) -> str:
        return self._name

    @property
    def vendor(self) -> str:
        return "FakeVendor"

    @property
    def system_id(self) -> str:
        return self._system_id

    async def connect(self) -> bool:
        self._connected = str(self._config.get("should_connect", "true")).lower() != "false"
        return self._connected

    async def get_cameras(self) -> list[FederatedCamera]:
        if not self._connected:
            return []
        count = int(self._config.get("camera_count", 2))
        return [
            FederatedCamera(
                external_id=f"fake-{i}",
                name=f"Fake Camera {i}",
                system_name=self._name,
                vendor=self.vendor,
                department="External",
                is_active=True,
            )
            for i in range(count)
        ]

    async def start_event_stream(self, callback) -> None:
        # Never actually awaited to completion in these tests -- POST
        # /systems only creates the task, it doesn't wait on it, and
        # nothing here cancels it either. An infinite no-op loop is
        # fine: it just sits idle for the rest of the test session,
        # same as it would in the real app between polls.
        import asyncio
        while True:
            await asyncio.sleep(3600)


register_adapter_type(
    adapter_type="test_fake",
    display_name="Fake Adapter (tests only)",
    config_fields=[
        ConfigField("should_connect", "Should connect", "text", False, "true"),
        ConfigField("camera_count", "Camera count", "number", False, 2),
        ConfigField("required_field", "Required field", "text", True),
    ],
)(FakeConfigurableAdapter)


# ── GET /api/v3/adapter-types ───────────────────────────────────────────

def test_adapter_types_lists_known_types(operator_client):
    resp = operator_client.get("/api/v3/adapter-types")
    assert resp.status_code == 200
    types = {t["adapter_type"] for t in resp.json()}
    assert {"windy", "rest_api", "onvif", "test_fake"} <= types


def test_adapter_types_requires_auth(anon_client):
    resp = anon_client.get("/api/v3/adapter-types")
    assert resp.status_code == 401


def test_adapter_types_exposes_config_fields_for_frontend(operator_client):
    types = operator_client.get("/api/v3/adapter-types").json()
    fake = next(t for t in types if t["adapter_type"] == "test_fake")
    names = {f["name"] for f in fake["config_fields"]}
    assert names == {"should_connect", "camera_count", "required_field"}


# ── POST /api/v3/systems/test-connection ────────────────────────────────

def test_connection_success_reports_camera_count(operator_client, db_session):
    resp = operator_client.post("/api/v3/systems/test-connection", json={
        "name": "Probe Fake VMS",
        "adapter_type": "test_fake",
        "config": {"required_field": "x", "camera_count": 3},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["camera_count"] == 3
    assert len(body["sample_cameras"]) == 3

    # Nothing persisted -- that's the whole point of "test" connection.
    count = db_session.execute(text(
        "SELECT count(*) FROM vms_systems WHERE name = 'Probe Fake VMS'"
    )).scalar()
    assert count == 0


def test_connection_failure_reported_not_raised(operator_client):
    resp = operator_client.post("/api/v3/systems/test-connection", json={
        "name": "Probe Fake VMS",
        "adapter_type": "test_fake",
        "config": {"required_field": "x", "should_connect": "false"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["camera_count"] == 0


def test_connection_missing_required_config_field_400s(operator_client):
    resp = operator_client.post("/api/v3/systems/test-connection", json={
        "name": "Probe Fake VMS",
        "adapter_type": "test_fake",
        "config": {},  # required_field missing
    })
    assert resp.status_code == 400
    assert "required_field" in str(resp.json()["detail"])


def test_connection_unknown_adapter_type_400s(operator_client):
    resp = operator_client.post("/api/v3/systems/test-connection", json={
        "name": "Probe", "adapter_type": "not_a_real_type", "config": {},
    })
    assert resp.status_code == 400


def test_connection_missing_adapter_type_400s(operator_client):
    resp = operator_client.post("/api/v3/systems/test-connection", json={"name": "Probe"})
    assert resp.status_code == 400


def test_connection_requires_auth(anon_client):
    resp = anon_client.post("/api/v3/systems/test-connection", json={
        "name": "Probe", "adapter_type": "test_fake", "config": {"required_field": "x"},
    })
    assert resp.status_code == 401


def test_connection_forbidden_for_viewer(viewer_client):
    resp = viewer_client.post("/api/v3/systems/test-connection", json={
        "name": "Probe", "adapter_type": "test_fake", "config": {"required_field": "x"},
    })
    assert resp.status_code == 403


# ── POST /api/v3/systems (config-driven path) ───────────────────────────

def test_create_with_adapter_type_connects_and_saves_cameras(operator_client, db_session):
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Live Fake VMS",
        "adapter_type": "test_fake",
        "config": {"required_field": "x", "camera_count": 4},
    })
    assert resp.status_code == 201
    body = resp.json()
    system_id = body["id"]
    assert body["status"] == "connected"

    row = db_session.execute(text(
        "SELECT status, camera_count, adapter_type, config, protocol "
        "FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert row is not None
    assert row[0] == "connected"
    assert row[1] == 4
    assert row[2] == "test_fake"
    assert row[3] == {"required_field": "x", "camera_count": 4}
    assert row[4] == "test_fake"  # protocol mirrors adapter_type on this path

    cam_count = db_session.execute(text(
        "SELECT count(*) FROM cameras WHERE vms_system_id = :id"
    ), {"id": system_id}).scalar()
    assert cam_count == 4


def test_create_with_adapter_type_appears_in_listing_with_marker(operator_client):
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Listed Live Fake VMS",
        "adapter_type": "test_fake",
        "config": {"required_field": "x", "camera_count": 1},
    })
    system_id = resp.json()["id"]

    listing = operator_client.get("/api/v3/systems").json()
    match = next(s for s in listing if s["id"] == system_id)
    assert match["adapter_type"] == "test_fake"
    assert match["status"] == "connected"
    assert match["camera_count"] == 1


def test_create_with_adapter_type_that_fails_to_connect_saves_disconnected(operator_client, db_session):
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Broken Fake VMS",
        "adapter_type": "test_fake",
        "config": {"required_field": "x", "should_connect": "false"},
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "disconnected"

    row = db_session.execute(text(
        "SELECT status, camera_count FROM vms_systems WHERE id = :id"
    ), {"id": resp.json()["id"]}).fetchone()
    assert row == ("disconnected", 0)

    cam_count = db_session.execute(text(
        "SELECT count(*) FROM cameras WHERE vms_system_id = :id"
    ), {"id": body["id"]}).scalar()
    assert cam_count == 0


def test_create_with_adapter_type_missing_required_config_400s(operator_client, db_session):
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Should Not Exist", "adapter_type": "test_fake", "config": {},
    })
    assert resp.status_code == 400
    count = db_session.execute(text(
        "SELECT count(*) FROM vms_systems WHERE name = 'Should Not Exist'"
    )).scalar()
    assert count == 0


def test_create_with_adapter_type_forbidden_for_viewer(viewer_client):
    resp = viewer_client.post("/api/v3/systems", json={
        "name": "Nope", "adapter_type": "test_fake", "config": {"required_field": "x"},
    })
    assert resp.status_code == 403


def test_create_without_adapter_type_still_record_only(operator_client, db_session):
    """Regression guard: the original manual/record-only path (no
    adapter_type at all) must still behave exactly as
    test_systems_api.py already verifies -- this endpoint now branches
    on adapter_type, and that branch must not accidentally swallow the
    no-adapter_type case."""
    resp = operator_client.post("/api/v3/systems", json={"name": "Still Manual VMS"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "disconnected"
    assert "adapter_type" not in body or body.get("adapter_type") is None

    row = db_session.execute(text(
        "SELECT adapter_type, config FROM vms_systems WHERE id = :id"
    ), {"id": resp.json()["id"]}).fetchone()
    assert row == (None, None)
