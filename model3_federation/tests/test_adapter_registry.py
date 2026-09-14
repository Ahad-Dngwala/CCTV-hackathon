"""
Unit tests for model3_federation/adapters/registry.py.

No DB, no network -- this only tests the registry bookkeeping itself
(registration, listing, config validation, unknown-type handling), so
unlike most of this test directory it does NOT need conftest.py's
Postgres-backed fixtures. Importing model3_federation.adapters.registry
alone is enough; the concrete adapter modules are imported too so their
register_adapter_type(...) decorators actually run and populate the
registry the same way router.py's own imports do at startup.
"""

import pytest

from model3_federation.adapters import registry
# Importing these runs their register_adapter_type(...) decorators.
import model3_federation.adapters.rest_api_vms_adapter  # noqa: F401
import model3_federation.adapters.onvif_vms_adapter  # noqa: F401


def test_windy_and_rest_api_and_onvif_are_registered():
    types = {t["adapter_type"] for t in registry.list_adapter_types()}
    assert {"windy", "rest_api", "onvif"} <= types


def test_list_adapter_types_exposes_config_fields():
    windy = next(t for t in registry.list_adapter_types() if t["adapter_type"] == "windy")
    field_names = {f["name"] for f in windy["config_fields"]}
    assert field_names == {"api_key", "lat", "lng", "radius_km", "limit"}
    api_key_field = next(f for f in windy["config_fields"] if f["name"] == "api_key")
    assert api_key_field["required"] is True
    assert api_key_field["type"] == "password"


def test_validate_config_reports_missing_required_fields():
    errors = registry.validate_config("windy", {})
    assert any("api_key" in e for e in errors)
    assert any("lat" in e for e in errors)


def test_validate_config_passes_with_all_required_fields():
    errors = registry.validate_config("windy", {"api_key": "x", "lat": "23.0", "lng": "72.5"})
    assert errors == []


def test_validate_config_unknown_type_is_reported_not_raised():
    errors = registry.validate_config("not_a_real_adapter_type", {})
    assert len(errors) == 1
    assert "not_a_real_adapter_type" in errors[0]


def test_is_known_type():
    assert registry.is_known_type("windy") is True
    assert registry.is_known_type("nope") is False


def test_build_adapter_unknown_type_raises():
    with pytest.raises(ValueError, match="nope"):
        registry.build_adapter("nope", "sys-id", "name", {})


def test_build_adapter_returns_working_instance_with_declared_type():
    adapter = registry.build_adapter("windy", "sys-id-123", "Test Windy", {"api_key": "k"})
    assert adapter.system_id == "sys-id-123"
    assert adapter.system_name == "Test Windy"
    assert adapter.adapter_type == "windy"
