"""
Shared fixtures for model3_federation/tests/.

Same situation as model2_analytics/tests/conftest.py, and the same fix:
model3's router gets mounted at runtime into *model1-registry's* FastAPI
app object (a plain `app.include_router(federation_router)` in
model1-registry/app/main.py) -- there's no separate model3 app to spin
up. The DB-backed fixtures model1-registry/tests/conftest.py already
built (real Postgres+PostGIS `sentinel_test`, one transaction +
SAVEPOINT per test, a TestClient per seeded role) are exactly the right
fixtures for testing model3's endpoints too.

Rather than forking/duplicating that ~300-line fixture file, this loads
it by file path and re-exports its names into this module's namespace,
so pytest sees the same fixtures here as it does under
model1-registry/tests/ and model2_analytics/tests/. Loaded under a
distinct module name (not "conftest") deliberately -- this file is
*also* named conftest.py, so a plain `from conftest import *` would
resolve to itself (already mid-import in sys.modules) instead of
model1-registry's copy.

Requires the same local setup as model1-registry/tests: a reachable
Postgres server, `sentinel`/`sentinel_test` bootstrapped per
model1-registry/README.md's Testing section (or `PSQL_PATH` set).

sys.path
--------
Two things need to be importable here (one fewer than model2_analytics'
conftest needs -- model3_federation has no `pipeline`-style dependency
on model2 at all, so there's no MODEL2_ROOT to add):
  1. `app` -> model1-registry/app/ (needs MODEL1_ROOT on sys.path).
     model3_federation/api/router.py does `from app.auth.dependencies
     import ...`, same as model1's and model2's own routers.
  2. `model3_federation` / `shared` -> both resolve once REPO_ROOT is on
     sys.path, since model3_federation is already a proper package
     directly under the repo root (it imports itself the same way,
     e.g. registration.py's `from model3_federation.adapters.base
     import VMSAdapter`) and `shared` is REPO_ROOT/shared/.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL1_ROOT = REPO_ROOT / "model1-registry"

sys.path.insert(0, str(MODEL1_ROOT))  # for `app`
sys.path.insert(0, str(REPO_ROOT))    # for `shared` and `model3_federation`

_MODEL1_CONFTEST_PATH = MODEL1_ROOT / "tests" / "conftest.py"

_spec = importlib.util.spec_from_file_location("model1_registry_conftest", _MODEL1_CONFTEST_PATH)
_model1_conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_model1_conftest)

# Re-export everything public (pytest fixtures, the _login/unique_camera_name
# helpers, SEED_PASSWORD, etc.) into this module's namespace so pytest picks
# up the fixtures when collecting tests under model3_federation/tests/.
for _name in dir(_model1_conftest):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_model1_conftest, _name)
del _name, _spec
