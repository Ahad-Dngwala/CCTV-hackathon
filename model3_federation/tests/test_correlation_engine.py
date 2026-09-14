"""
Tests for model3_federation/correlation/engine.py (completion-plan
Finding 3): "a plate seen at two cameras under different vms_system_ids
resolves to one vehicle_tracks row and produces a correlation; a
watchlisted plate produces an alerts row" -- the exact scenario the
completion plan says was hand-verified this session against a real
Postgres instance, turned into an actual, repeatable test here.

These call CorrelationEngine._process_in_db() directly rather than going
through on_event()/the event bus: _process_in_db is where all the actual
DB logic in this finding's scope lives (camera lookup, vehicle_tracks
upsert, watchlist check, detections insert, correlation query), it is
already a plain synchronous method (no asyncio.run() workaround needed,
unlike register_adapter() in test_registration.py), and on_event() layers
on dedup/broadcast concerns this finding's scope doesn't cover. bus and
ws_broadcast are constructor-required but never touched by
_process_in_db, so both get harmless stand-ins below.

Needs the same real Postgres sentinel_test setup as model1-registry/tests
(see this directory's conftest.py docstring).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from model3_federation.correlation.engine import CorrelationEngine, _normalize_plate
from model3_federation.schemas.models import FederatedEvent


async def _noop_broadcast(message):
    pass


def _make_engine(db_session) -> CorrelationEngine:
    return CorrelationEngine(bus=None, db_session_factory=lambda: db_session, ws_broadcast=_noop_broadcast)


def _seed_system_and_camera(db_session, system_id: str, system_name: str, source_grid_id: str, camera_name: str) -> None:
    """Arrange a vms_systems row + one camera on it -- the minimum
    _process_in_db needs to resolve an incoming event's camera_id (it
    skips the DB write entirely for a system/external_id pair it can't
    find, per its own docstring)."""
    db_session.execute(text(
        """
        INSERT INTO vms_systems (id, name, vendor, protocol, ownership, status, camera_count)
        VALUES (:id, :name, 'TestVendor', 'simulated', 'government', 'connected', 1)
        """
    ), {"id": system_id, "name": system_name})
    db_session.execute(text(
        """
        INSERT INTO cameras (name, source_grid_id, vms_system_id, ownership, connectivity_status, is_active)
        VALUES (:name, :ext, :sys, 'government', 'online', true)
        """
    ), {"name": camera_name, "ext": source_grid_id, "sys": system_id})
    db_session.commit()


def _make_event(system_id: str, system_name: str, camera_external_id: str, camera_name: str,
                 plate: str, received_at: datetime) -> FederatedEvent:
    return FederatedEvent(
        system_id=system_id,
        system_name=system_name,
        vendor="TestVendor",
        camera_external_id=camera_external_id,
        camera_name=camera_name,
        event_type="vehicle_detection",
        detected_plate=plate,
        confidence=0.95,
        vehicle_type="car",
        source_timestamp=received_at,
        received_at=received_at,
    )


def test_cross_system_correlation(db_session):
    sys_a, sys_b = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_system_and_camera(db_session, sys_a, "Test System A", "CAM-A", "Camera A")
    _seed_system_and_camera(db_session, sys_b, "Test System B", "CAM-B", "Camera B")

    engine = _make_engine(db_session)
    plate_raw = "ZZ TEST-0001"
    plate_norm = _normalize_plate(plate_raw)
    t0 = datetime.now(tz=timezone.utc)

    # First sighting, system A only -- nothing to correlate against yet.
    event_a = _make_event(sys_a, "Test System A", "CAM-A", "Camera A", plate_raw, t0)
    result_a = engine._process_in_db(event_a, plate_norm)
    assert "correlation" not in result_a
    assert "alert" not in result_a

    # Second sighting, system B, five minutes later -- same plate, a
    # different vms_system_id, well within the 30-minute window.
    event_b = _make_event(sys_b, "Test System B", "CAM-B", "Camera B", plate_raw, t0 + timedelta(minutes=5))
    result_b = engine._process_in_db(event_b, plate_norm)

    assert "correlation" in result_b
    correlation = result_b["correlation"]
    assert correlation.plate_number == plate_norm
    assert set(correlation.systems_involved) == {"Test System A", "Test System B"}
    assert correlation.travel_time_secs == 300
    assert correlation.is_watchlisted is False

    # Both detections resolved to the same vehicle_tracks row.
    track_rows = db_session.execute(text(
        "SELECT DISTINCT vehicle_track_id FROM detections d JOIN cameras c ON c.id = d.camera_id "
        "WHERE c.vms_system_id IN (:a, :b)"
    ), {"a": sys_a, "b": sys_b}).fetchall()
    assert len(track_rows) == 1
    assert track_rows[0][0] is not None


def test_watchlisted_plate_produces_alert(db_session):
    sys_c = str(uuid.uuid4())
    _seed_system_and_camera(db_session, sys_c, "Test System C", "CAM-C", "Camera C")

    plate_raw = "ZZ TEST-0002"
    plate_norm = _normalize_plate(plate_raw)
    db_session.execute(text(
        "INSERT INTO vehicles_watchlist (plate_number, category, status) "
        "VALUES (:p, 'stolen', 'active')"
    ), {"p": plate_norm})
    db_session.commit()

    engine = _make_engine(db_session)
    event = _make_event(sys_c, "Test System C", "CAM-C", "Camera C", plate_raw, datetime.now(tz=timezone.utc))
    result = engine._process_in_db(event, plate_norm)

    assert "alert" in result
    alert = result["alert"]
    assert alert.plate_number == plate_norm
    assert alert.system_name == "Test System C"
    assert alert.severity == "high"

    alert_rows = db_session.execute(text(
        "SELECT a.severity, a.alert_type FROM alerts a "
        "JOIN detections d ON d.id = a.detection_id "
        "JOIN cameras c ON c.id = d.camera_id WHERE c.vms_system_id = :sys"
    ), {"sys": sys_c}).fetchall()
    assert len(alert_rows) == 1
    assert alert_rows[0][0] == "high"
    assert alert_rows[0][1] == "federated_vehicle_match"

    track_row = db_session.execute(text(
        "SELECT is_watchlisted FROM vehicle_tracks WHERE plate_number = :p"
    ), {"p": plate_norm}).fetchone()
    assert track_row[0] is True


def test_unlisted_plate_produces_no_alert(db_session):
    sys_d = str(uuid.uuid4())
    _seed_system_and_camera(db_session, sys_d, "Test System D", "CAM-D", "Camera D")

    engine = _make_engine(db_session)
    plate_norm = _normalize_plate("ZZTEST0003")
    event = _make_event(sys_d, "Test System D", "CAM-D", "Camera D", "ZZTEST0003", datetime.now(tz=timezone.utc))
    result = engine._process_in_db(event, plate_norm)

    assert "alert" not in result
    # "alert" not in result is also what a silently-swallowed DB error
    # would look like (_process_in_db returns {} either way) - confirming
    # the detection row actually exists is what tells those two cases
    # apart. (An earlier draft of this test only had the assertion above,
    # and passed even while the write itself was failing every time on a
    # SQL bug now fixed in engine.py - this is here so that mistake can't
    # repeat silently.)
    written = db_session.execute(text(
        "SELECT detected_plate FROM detections d JOIN cameras c ON c.id = d.camera_id "
        "WHERE c.vms_system_id = :sys"
    ), {"sys": sys_d}).fetchone()
    assert written is not None
    assert written[0] == plate_norm


def test_event_for_unregistered_camera_is_skipped(db_session):
    """No cameras row exists for this (system_id, external_id) pair --
    _process_in_db should skip the write entirely (per its own
    docstring) rather than violate detections.camera_id's FK."""
    count_before = db_session.execute(text("SELECT count(*) FROM detections")).scalar()

    engine = _make_engine(db_session)
    event = _make_event(str(uuid.uuid4()), "Ghost System", "CAM-GHOST", "Ghost Camera",
                         "ZZTEST0004", datetime.now(tz=timezone.utc))
    result = engine._process_in_db(event, "ZZTEST0004")

    assert result == {}
    count_after = db_session.execute(text("SELECT count(*) FROM detections")).scalar()
    assert count_after == count_before
