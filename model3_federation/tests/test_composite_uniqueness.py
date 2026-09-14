"""
Tests for the composite uniqueness constraint on cameras (completion-plan
Finding 3): "two different vms_system_ids can each register a camera with
the same source_grid_id without conflict; the same vms_system_id +
source_grid_id twice updates, doesn't duplicate."

This is deliberately at the schema/constraint level -- raw SQL against
cameras directly, no registration.py involved -- rather than duplicating
test_registration.py's coverage of register_adapter()'s own upsert
behavior. The two are checking different things: test_registration.py
confirms register_adapter() behaves correctly *given* the constraint;
this file confirms the constraint itself (shared/db/schema.sql's
idx_cameras_source_per_system) actually exists and is scoped to the pair,
not just source_grid_id alone -- something every writer of cameras rows
depends on, not only register_adapter() (Finding 1's manual-onboarding
endpoints will too).

Needs the same real Postgres sentinel_test setup as model1-registry/tests
(see this directory's conftest.py docstring).
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _make_system(db_session, name: str) -> str:
    system_id = str(uuid.uuid4())
    db_session.execute(text(
        "INSERT INTO vms_systems (id, name, vendor, protocol, ownership, status, camera_count) "
        "VALUES (:id, :name, 'TestVendor', 'simulated', 'government', 'connected', 0)"
    ), {"id": system_id, "name": name})
    return system_id


def test_same_source_grid_id_allowed_across_different_systems(db_session):
    sys_a = _make_system(db_session, "Test System A")
    sys_b = _make_system(db_session, "Test System B")

    for sys_id in (sys_a, sys_b):
        db_session.execute(text(
            "INSERT INTO cameras (name, source_grid_id, vms_system_id, ownership, connectivity_status, is_active) "
            "VALUES ('Shared External ID Camera', 'CAM-SAME', :sys, 'government', 'online', true)"
        ), {"sys": sys_id})
    db_session.commit()

    rows = db_session.execute(text(
        "SELECT vms_system_id FROM cameras WHERE source_grid_id = 'CAM-SAME' ORDER BY vms_system_id"
    )).fetchall()
    assert len(rows) == 2, "two systems sharing a source_grid_id should both be allowed to exist"
    assert {str(r[0]) for r in rows} == {sys_a, sys_b}


def test_same_system_and_source_grid_id_twice_raises_without_on_conflict(db_session):
    """
    Confirms the constraint is actually enforced at the DB level (not
    just something application code happens to always avoid by using
    ON CONFLICT) -- a plain second INSERT with no conflict handling for
    the same (vms_system_id, source_grid_id) pair should fail outright.
    """
    sys_id = _make_system(db_session, "Test System C")
    db_session.execute(text(
        "INSERT INTO cameras (name, source_grid_id, vms_system_id, ownership, connectivity_status, is_active) "
        "VALUES ('First', 'CAM-DUP', :sys, 'government', 'online', true)"
    ), {"sys": sys_id})
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(text(
            "INSERT INTO cameras (name, source_grid_id, vms_system_id, ownership, connectivity_status, is_active) "
            "VALUES ('Second', 'CAM-DUP', :sys, 'government', 'online', true)"
        ), {"sys": sys_id})
        db_session.commit()
    db_session.rollback()  # leave the session usable for the fixture's own teardown


def test_same_system_and_source_grid_id_twice_upserts_with_on_conflict(db_session):
    """The upsert half of the same finding: the ON CONFLICT clause every
    real writer (registration.py) actually uses updates in place instead
    of hitting the IntegrityError the previous test deliberately
    provoked."""
    sys_id = _make_system(db_session, "Test System D")
    db_session.execute(text(
        "INSERT INTO cameras (name, source_grid_id, vms_system_id, ownership, connectivity_status, is_active) "
        "VALUES ('Original Name', 'CAM-UPSERT', :sys, 'government', 'online', true)"
    ), {"sys": sys_id})
    db_session.commit()

    db_session.execute(text(
        """
        INSERT INTO cameras (name, source_grid_id, vms_system_id, ownership, connectivity_status, is_active)
        VALUES ('Updated Name', 'CAM-UPSERT', :sys, 'government', 'online', true)
        ON CONFLICT (vms_system_id, source_grid_id) DO UPDATE
        SET name = 'Updated Name'
        """
    ), {"sys": sys_id})
    db_session.commit()

    rows = db_session.execute(text(
        "SELECT name FROM cameras WHERE vms_system_id = :sys AND source_grid_id = 'CAM-UPSERT'"
    ), {"sys": sys_id}).fetchall()
    assert len(rows) == 1, "ON CONFLICT should have updated the existing row, not inserted a second one"
    assert rows[0][0] == "Updated Name"
