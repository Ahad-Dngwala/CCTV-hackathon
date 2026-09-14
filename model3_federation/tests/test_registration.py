"""
Tests for model3_federation/registration.py (completion-plan Finding 3).

Every verification of register_adapter() before this was done by hand
against a locally-installed Postgres (see model3-completion-plan.md's
Finding 3 and Finding 1's test plans, which both point back at that same
manual session) -- valid at the time, but nothing caught a regression
after. This turns that same manual check ("register once, then again,
confirm it upserts rather than duplicates") into a real, repeatable test.

register_adapter() is async (it awaits adapter.get_cameras(), then runs
the actual DB work in an executor). No plugin here or anywhere else in
the repo teaches plain pytest to run "async def test_..." directly --
there's no pytest-asyncio in any requirements file and no existing
"async def test_" anywhere in model1-registry/ or model2_analytics/
(confirmed by grep before writing this file) -- so this wraps each call
in the small _run() helper below (asyncio.run(...)) inside ordinary
"def test_..." functions, rather than introducing a new test-only
dependency this repo doesn't otherwise use.

register_adapter() takes a db_session_factory callable, not a session --
production code calls it once per adapter with shared/db/session.py's
real sessionmaker (see start_federation_services in api/router.py). For
tests, `lambda: db_session` makes it call the fixture's already-open,
SAVEPOINT-wrapped session every time, so everything register_adapter
does (including its own internal session.commit()) stays inside this
test's transaction and rolls back at teardown -- same trick db_session's
own docstring describes for app code that commits directly.

Needs the same real Postgres sentinel_test setup as model1-registry/tests
(see this directory's conftest.py docstring).
"""

import asyncio

from sqlalchemy import text

from model3_federation.registration import register_adapter
from model3_federation.schemas.models import FederatedCamera


def _run(coro):
    return asyncio.run(coro)


class FakeAdapter:
    """Minimal stand-in for a VMSAdapter (adapters/base.py) -- only the
    attributes/methods register_adapter() actually touches: system_id,
    system_name, vendor, and get_cameras()."""

    def __init__(self, system_id: str, system_name: str, vendor: str, cameras: list[FederatedCamera]):
        self.system_id = system_id
        self.system_name = system_name
        self.vendor = vendor
        self._cameras = cameras

    async def get_cameras(self) -> list[FederatedCamera]:
        return self._cameras


def _camera(external_id: str, name: str, system_name: str, vendor: str,
            department: str = "Police", lat: float = 23.03, lng: float = 72.58) -> FederatedCamera:
    return FederatedCamera(
        external_id=external_id,
        name=name,
        system_name=system_name,
        vendor=vendor,
        department=department,
        lat=lat,
        lng=lng,
        location_label=f"{name} location",
        is_active=True,
    )


def test_register_adapter_creates_system_and_cameras(db_session):
    system_id = "aaaaaaaa-0000-0000-0000-000000000001"
    adapter = FakeAdapter(
        system_id=system_id,
        system_name="Test Police VMS",
        vendor="TestVendor",
        cameras=[
            _camera("EXT-1", "Camera One", "Test Police VMS", "TestVendor"),
            _camera("EXT-2", "Camera Two", "Test Police VMS", "TestVendor"),
        ],
    )

    _run(register_adapter(lambda: db_session, adapter))

    sys_row = db_session.execute(text(
        "SELECT name, vendor, ownership, status, camera_count, department_id "
        "FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert sys_row is not None
    assert sys_row[0] == "Test Police VMS"
    assert sys_row[1] == "TestVendor"
    assert sys_row[2] == "government"  # register_adapter's default
    assert sys_row[3] == "connected"
    assert sys_row[4] == 2
    # "Police" hint should resolve against the real seeded Home Department
    # (Police) -- see shared/db/seed.sql. Not the focus of this test
    # (Finding 4 covers resolution itself in depth), just confirming the
    # two features compose correctly.
    assert sys_row[5] is not None

    cam_rows = db_session.execute(text(
        "SELECT name, source_grid_id, connectivity_status, is_active "
        "FROM cameras WHERE vms_system_id = :id ORDER BY source_grid_id"
    ), {"id": system_id}).fetchall()
    assert [r[1] for r in cam_rows] == ["EXT-1", "EXT-2"]
    assert [r[0] for r in cam_rows] == ["Camera One", "Camera Two"]
    assert all(r[2] == "online" and r[3] is True for r in cam_rows)


def test_register_adapter_twice_updates_not_duplicates(db_session):
    system_id = "aaaaaaaa-0000-0000-0000-000000000002"
    first_cameras = [_camera("EXT-1", "Camera One", "Test RTO VMS", "TestVendor", department="RTO")]
    adapter = FakeAdapter(
        system_id=system_id, system_name="Test RTO VMS", vendor="TestVendor", cameras=first_cameras,
    )
    _run(register_adapter(lambda: db_session, adapter))

    # Second registration: same system_id, same camera external_id, but
    # the camera's name changed (simulating a re-registration after the
    # source VMS renamed something) and a second camera was added.
    adapter._cameras = [
        _camera("EXT-1", "Camera One Renamed", "Test RTO VMS", "TestVendor", department="RTO"),
        _camera("EXT-2", "Camera Two", "Test RTO VMS", "TestVendor", department="RTO"),
    ]
    _run(register_adapter(lambda: db_session, adapter))

    sys_rows = db_session.execute(text(
        "SELECT camera_count FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchall()
    assert len(sys_rows) == 1, "second registration duplicated the vms_systems row instead of updating it"
    assert sys_rows[0][0] == 2

    cam_rows = db_session.execute(text(
        "SELECT name, source_grid_id FROM cameras WHERE vms_system_id = :id ORDER BY source_grid_id"
    ), {"id": system_id}).fetchall()
    assert len(cam_rows) == 2, "second registration duplicated a camera row instead of updating it"
    assert cam_rows[0] == ("Camera One Renamed", "EXT-1")
    assert cam_rows[1] == ("Camera Two", "EXT-2")


def test_register_adapter_sticky_department_id_not_overwritten(db_session):
    """
    ON CONFLICT ... department_id = COALESCE(vms_systems.department_id,
    EXCLUDED.department_id) in _upsert_system_and_cameras: once a
    department_id resolves successfully, a later registration whose hint
    happens to resolve differently (or not at all) must not clobber it.
    """
    system_id = "aaaaaaaa-0000-0000-0000-000000000003"
    adapter = FakeAdapter(
        system_id=system_id, system_name="Test Municipal VMS", vendor="TestVendor",
        cameras=[_camera("EXT-1", "Camera One", "Test Municipal VMS", "TestVendor",
                          department="Municipal Corporation")],
    )
    _run(register_adapter(lambda: db_session, adapter))

    first_dept = db_session.execute(text(
        "SELECT department_id FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()[0]
    assert first_dept is not None

    # Re-register with a hint that would resolve to nothing on its own.
    adapter._cameras = [_camera("EXT-1", "Camera One", "Test Municipal VMS", "TestVendor",
                                 department="NonexistentDepartmentXYZ")]
    _run(register_adapter(lambda: db_session, adapter))

    second_dept = db_session.execute(text(
        "SELECT department_id FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()[0]
    assert second_dept == first_dept
