"""
Tests for the manual VMS onboarding endpoints (completion-plan Finding 1's
own test plan, run here as the plan's suggested follow-up "Finding 3
again" step): POST/PATCH/DELETE /api/v3/systems.

Auth/role coverage for these three endpoints already lives in
test_auth.py (acknowledge_alert and these share the same
require_role("dept_admin", "operator") gate, and that file's scope is
specifically auth). This file covers the rest of Finding 1's test plan:
the actual create/update/delete behavior, validation, and how a
manually-onboarded system shows up in GET /api/v3/systems.

Needs the same real Postgres sentinel_test setup as model1-registry/tests
(see this directory's conftest.py docstring).
"""

import uuid

from sqlalchemy import text


def test_create_system_as_operator(operator_client, db_session):
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Sentinel Test VMS",
        "vendor": "Acme Corp",
        "ownership": "private",
    })
    assert resp.status_code == 201
    body = resp.json()
    system_id = body["id"]
    assert body["status"] == "disconnected"

    row = db_session.execute(text(
        "SELECT name, vendor, protocol, ownership, status, camera_count, department_id "
        "FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert row is not None
    assert row[0] == "Sentinel Test VMS"
    assert row[1] == "Acme Corp"
    assert row[2] == "manual"  # default when not supplied
    assert row[3] == "private"
    assert row[4] == "disconnected"
    assert row[5] == 0
    assert row[6] is None


def test_create_system_defaults_ownership_and_protocol(operator_client, db_session):
    """name is the only thing this endpoint actually requires."""
    resp = operator_client.post("/api/v3/systems", json={"name": "Minimal VMS"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["ownership"] == "government"
    assert body["protocol"] == "manual"

    row = db_session.execute(text(
        "SELECT ownership, protocol FROM vms_systems WHERE id = :id"
    ), {"id": body["id"]}).fetchone()
    assert row == ("government", "manual")


def test_create_system_with_valid_department(operator_client, db_session):
    dept_id = db_session.execute(text(
        "SELECT id FROM departments ORDER BY id LIMIT 1"
    )).fetchone()[0]

    resp = operator_client.post("/api/v3/systems", json={
        "name": "Departmental VMS", "department_id": str(dept_id),
    })
    assert resp.status_code == 201
    row = db_session.execute(text(
        "SELECT department_id FROM vms_systems WHERE id = :id"
    ), {"id": resp.json()["id"]}).fetchone()
    assert str(row[0]) == str(dept_id)


def test_create_system_rejects_invalid_ownership(operator_client):
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Bad Ownership VMS", "ownership": "cooperative",
    })
    assert resp.status_code == 422


def test_create_system_rejects_nonexistent_department(operator_client, db_session):
    fake_dept_id = str(uuid.uuid4())
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Orphan Dept VMS", "department_id": fake_dept_id,
    })
    assert resp.status_code == 400

    count = db_session.execute(text(
        "SELECT count(*) FROM vms_systems WHERE name = 'Orphan Dept VMS'"
    )).scalar()
    assert count == 0, "the row should not have been created when validation failed"


def test_create_system_forbidden_for_viewer(viewer_client):
    resp = viewer_client.post("/api/v3/systems", json={"name": "Should Not Exist"})
    assert resp.status_code == 403


def test_create_system_requires_auth(anon_client):
    resp = anon_client.post("/api/v3/systems", json={"name": "Should Not Exist"})
    assert resp.status_code == 401


def _create(operator_client, **overrides) -> str:
    payload = {"name": "Editable VMS", "vendor": "Original Vendor", "ownership": "government"}
    payload.update(overrides)
    resp = operator_client.post("/api/v3/systems", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


def test_patch_updates_name_only(operator_client, db_session):
    system_id = _create(operator_client)
    resp = operator_client.patch(f"/api/v3/systems/{system_id}", json={"name": "Renamed VMS"})
    assert resp.status_code == 200
    assert resp.json()["id"] == system_id
    assert resp.json()["updated_fields"] == ["name"]

    row = db_session.execute(text(
        "SELECT id, name, vendor, ownership FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert str(row[0]) == system_id  # id unchanged
    assert row[1] == "Renamed VMS"
    assert row[2] == "Original Vendor"  # untouched fields stay untouched
    assert row[3] == "government"


def test_patch_can_clear_department_explicitly(operator_client, db_session):
    dept_id = db_session.execute(text("SELECT id FROM departments ORDER BY id LIMIT 1")).fetchone()[0]
    system_id = _create(operator_client, department_id=str(dept_id))

    resp = operator_client.patch(f"/api/v3/systems/{system_id}", json={"department_id": None})
    assert resp.status_code == 200

    row = db_session.execute(text(
        "SELECT department_id FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert row[0] is None


def test_patch_rejects_nonexistent_department(operator_client, db_session):
    system_id = _create(operator_client)
    resp = operator_client.patch(f"/api/v3/systems/{system_id}", json={
        "department_id": str(uuid.uuid4()),
    })
    assert resp.status_code == 400

    row = db_session.execute(text(
        "SELECT department_id FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert row[0] is None, "the failed update should not have partially applied"


def test_patch_nonexistent_system_404s(operator_client):
    resp = operator_client.patch(f"/api/v3/systems/{uuid.uuid4()}", json={"name": "Ghost"})
    assert resp.status_code == 404


def test_patch_forbidden_for_viewer(viewer_client, operator_client):
    system_id = _create(operator_client)
    resp = viewer_client.patch(f"/api/v3/systems/{system_id}", json={"name": "Nope"})
    assert resp.status_code == 403


def test_delete_system_with_zero_cameras_succeeds(operator_client, db_session):
    system_id = _create(operator_client)
    resp = operator_client.delete(f"/api/v3/systems/{system_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted", "id": system_id}

    row = db_session.execute(text(
        "SELECT 1 FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert row is None


def test_delete_system_with_camera_returns_409(operator_client, db_session):
    system_id = _create(operator_client)
    db_session.execute(text(
        "INSERT INTO cameras (name, source_grid_id, vms_system_id, ownership, connectivity_status, is_active) "
        "VALUES ('Attached Camera', 'EXT-ATTACHED', :sys, 'government', 'online', true)"
    ), {"sys": system_id})
    db_session.commit()

    resp = operator_client.delete(f"/api/v3/systems/{system_id}")
    assert resp.status_code == 409

    still_there = db_session.execute(text(
        "SELECT 1 FROM cameras WHERE vms_system_id = :sys AND source_grid_id = 'EXT-ATTACHED'"
    ), {"sys": system_id}).fetchone()
    assert still_there is not None, "the camera should not have been touched"
    system_still_there = db_session.execute(text(
        "SELECT 1 FROM vms_systems WHERE id = :id"
    ), {"id": system_id}).fetchone()
    assert system_still_there is not None, "the system row should not have been deleted either"


def test_delete_nonexistent_system_404s(operator_client):
    resp = operator_client.delete(f"/api/v3/systems/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_delete_forbidden_for_viewer(viewer_client, operator_client):
    system_id = _create(operator_client)
    resp = viewer_client.delete(f"/api/v3/systems/{system_id}")
    assert resp.status_code == 403


def test_manually_created_system_appears_in_listing(operator_client):
    """The other half of Finding 1's own recommendation: a manually
    onboarded system shows up in GET /api/v3/systems as itself --
    disconnected, zero cameras -- rather than being hidden, and doesn't
    crash that endpoint's query (which was written assuming every system
    came from an adapter)."""
    resp = operator_client.post("/api/v3/systems", json={
        "name": "Listed Manual VMS", "vendor": "Some Vendor",
    })
    system_id = resp.json()["id"]

    listing = operator_client.get("/api/v3/systems").json()
    match = [s for s in listing if s["id"] == system_id]
    assert len(match) == 1
    assert match[0]["status"] == "disconnected"
    assert match[0]["camera_count"] == 0
    assert match[0]["vendor"] == "Some Vendor"
    # No department set on purpose, not a failed hint -- Finding 4's
    # unmatched_department_hint should stay null, not flag this as unresolved.
    assert match[0]["unmatched_department_hint"] is None
