"""
Anonymous-401 / role-403 regression tests for model3_federation/api/router.py
(completion-plan Finding 3's auth coverage).

model3_federation had zero test files before this, so nothing was actually
verifying the "auth on every endpoint" hardening pass (commit 619aa51,
already on main before this plan started) still holds. Follows the exact
pattern model2_analytics/tests/test_detections_recorded_auth.py already
uses for the identical situation in that component: one function per
endpoint, anonymous gets 401, the one write endpoint with a narrower role
gate (acknowledge_alert; the finding also names Finding 1's new onboarding
endpoints, covered in test_systems_api.py once that work exists) also
gets a 403-for-viewer check.

This is deliberately scoped to auth only, same as that file - not whether
each endpoint's data comes back correctly, which is what
test_registration.py / test_correlation_engine.py / test_composite_uniqueness.py
cover instead.

Needs the same real Postgres sentinel_test setup as model1-registry/tests
(see this directory's conftest.py docstring).
"""

import json

import pytest
from starlette.testclient import WebSocketDisconnect

FAKE_ID = "00000000-0000-0000-0000-000000000000"


# ── GET endpoints -- any authenticated role; anon gets 401 ───────────

def test_systems_requires_auth(anon_client):
    resp = anon_client.get("/api/v3/systems")
    assert resp.status_code == 401


def test_cameras_requires_auth(anon_client):
    resp = anon_client.get("/api/v3/cameras")
    assert resp.status_code == 401


def test_events_requires_auth(anon_client):
    resp = anon_client.get("/api/v3/events")
    assert resp.status_code == 401


def test_events_stats_requires_auth(anon_client):
    resp = anon_client.get("/api/v3/events/stats")
    assert resp.status_code == 401


def test_correlations_requires_auth(anon_client):
    resp = anon_client.get("/api/v3/correlations")
    assert resp.status_code == 401


def test_correlations_track_requires_auth(anon_client):
    # plate is a required query param (Query(...)) -- pass a well-formed
    # one so the only thing that can make this request fail is auth, not
    # 422 param validation racing 401 for which error wins.
    resp = anon_client.get("/api/v3/correlations/track", params={"plate": "GJ01AB1234"})
    assert resp.status_code == 401


def test_alerts_requires_auth(anon_client):
    resp = anon_client.get("/api/v3/alerts")
    assert resp.status_code == 401


# ── POST endpoints -- anon gets 401 ───────────────────────────────────

def test_acknowledge_alert_requires_auth(anon_client):
    resp = anon_client.post(f"/api/v3/alerts/{FAKE_ID}/acknowledge")
    assert resp.status_code == 401


def test_simulate_requires_auth(anon_client):
    resp = anon_client.post(f"/api/v3/systems/{FAKE_ID}/simulate")
    assert resp.status_code == 401


# ── Role-gated: acknowledge_alert needs dept_admin/operator ──────────

def test_acknowledge_alert_forbidden_for_viewer(viewer_client):
    # require_role() runs as a dependency before the handler body, so a
    # nonexistent alert_id still correctly exercises the 403 path -- the
    # DB is never touched for a role check that fails.
    resp = viewer_client.post(f"/api/v3/alerts/{FAKE_ID}/acknowledge")
    assert resp.status_code == 403


def test_acknowledge_alert_allowed_for_operator_role(operator_client):
    # Not asserting 200 here -- FAKE_ID doesn't exist, so this correctly
    # 404s past the role gate. The point is 403 is specific to viewer,
    # not every non-dept_admin role.
    resp = operator_client.post(f"/api/v3/alerts/{FAKE_ID}/acknowledge")
    assert resp.status_code == 404


# ── WebSocket ──────────────────────────────────────────────────────
#
# Not folded into the flat GET/POST checks above: websocket_connect()
# reports a rejected handshake differently than resp.status_code does
# (see test_detections_recorded_auth.py's docstring, which defers this
# same case for /ws/detections for the same reason -- this is that
# "own focused test" for model3's equivalent socket instead of another
# deferral).

def test_ws_federation_rejects_unauthenticated(anon_client):
    """An unauthenticated handshake gets a clean WS_1008_POLICY_VIOLATION
    close rather than connecting (see router.py's ws_federation docstring
    for why this isn't just Depends(get_current_user) like the REST
    endpoints above)."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with anon_client.websocket_connect("/api/v3/ws/federation"):
            pass
    assert exc_info.value.code == 1008


def test_ws_federation_accepts_authenticated_user(viewer_client):
    """The other half of the same case, and not redundant with the anon
    check above: proves the fix actually lets a legitimate connection
    through end to end, not just that unauthenticated ones are rejected."""
    with viewer_client.websocket_connect("/api/v3/ws/federation") as ws:
        message = json.loads(ws.receive_text())
        assert message["type"] == "heartbeat"
