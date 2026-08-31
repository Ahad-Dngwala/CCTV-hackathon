import pytest

# Approximate real-world district areas (sq km), for sanity-checking the
# geodesic math. Generous tolerance because seed.sql's boundaries are
# Shapely-simplified (coverage_simplify, tolerance 0.002°).
KNOWN_APPROX_AREA_SQ_KM = {
    "Kutch": 45652,       # India's largest district by area
    "Ahmedabad": 8087,
    "Surat": 4418,
}


def test_gap_analysis_returns_all_districts(admin_home_client):
    resp = admin_home_client.get("/api/v1/gap-analysis")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 33


def test_gap_analysis_coverage_pct_within_bounds(admin_home_client):
    rows = admin_home_client.get("/api/v1/gap-analysis").json()
    for r in rows:
        assert 0.0 <= r["coverage_pct"] <= 100.0
        assert r["uncovered_area_sq_km"] <= r["district_area_sq_km"] + 0.01
        assert r["district_area_sq_km"] > 0


def test_gap_analysis_zero_camera_district_is_fully_uncovered(admin_home_client):
    rows = admin_home_client.get("/api/v1/gap-analysis").json()
    for r in rows:
        if r["camera_count"] == 0:
            assert r["coverage_pct"] == 0.0
            assert r["uncovered_area_sq_km"] == pytest.approx(
                r["district_area_sq_km"], rel=0.01
            )


def test_gap_analysis_district_area_matches_real_world_geography(admin_home_client):
    """Regression test for the DEG_TO_SQ_KM=11322.0 flat-conversion bug:
    that constant was calibrated for 23°N and distorted area for districts
    away from that latitude. The fix uses ST_Area(boundary::geography),
    which should land close to each district's real-world area regardless
    of latitude."""
    rows = {r["district_name"]: r for r in admin_home_client.get("/api/v1/gap-analysis").json()}
    for name, expected_km2 in KNOWN_APPROX_AREA_SQ_KM.items():
        actual = rows[name]["district_area_sq_km"]
        assert actual == pytest.approx(expected_km2, rel=0.25), (
            f"{name}: expected ~{expected_km2} km^2, got {actual} km^2 "
            f"(possible regression to flat-degree area conversion)"
        )


def test_gap_analysis_radius_changes_uncovered_area(admin_home_client):
    small = {
        r["district_name"]: r["uncovered_area_sq_km"]
        for r in admin_home_client.get(
            "/api/v1/gap-analysis", params={"radius_km": 0.5}
        ).json()
    }
    large = {
        r["district_name"]: r["uncovered_area_sq_km"]
        for r in admin_home_client.get(
            "/api/v1/gap-analysis", params={"radius_km": 5.0}
        ).json()
    }
    # A bigger monitoring radius per camera should never leave *more*
    # uncovered area than a smaller radius, for any district with cameras.
    for name in small:
        assert large[name] <= small[name] + 0.01


def test_gap_analysis_rejects_out_of_range_radius(admin_home_client):
    assert admin_home_client.get(
        "/api/v1/gap-analysis", params={"radius_km": 0.0}
    ).status_code == 422
    assert admin_home_client.get(
        "/api/v1/gap-analysis", params={"radius_km": 50.0}
    ).status_code == 422


def test_gap_analysis_requires_auth(anon_client):
    resp = anon_client.get("/api/v1/gap-analysis")
    assert resp.status_code == 401


def test_gap_analysis_uncovered_geojson_is_valid_multipolygon_or_null(admin_home_client):
    rows = admin_home_client.get("/api/v1/gap-analysis").json()
    for r in rows:
        gj = r["uncovered_geojson"]
        if gj is not None:
            assert gj["type"] in ("MultiPolygon", "Polygon", "GeometryCollection")
