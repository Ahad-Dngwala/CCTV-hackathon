"""
Shared pytest fixtures.

Design:
  * Tests run against a REAL Postgres + PostGIS database (``sentinel_test``),
    not sqlite/mocks — this app leans on PostGIS geography functions
    (ST_Buffer, ST_Union, ST_Difference, ST_Area on ::geography) and
    Postgres triggers (status_history audit log, updated_at stamping)
    that have no sqlite equivalent. Testing against anything else would
    not actually exercise the code paths that matter most here.
  * ``shared/db/schema.sql`` + ``triggers.sql`` + ``seed.sql`` are applied
    once per test session (session-scoped), exactly as docker-compose
    does it in production.
  * Each individual test runs inside an outer transaction + SAVEPOINT
    that is rolled back on teardown, so tests can freely create/update/
    delete rows (including calling the real API, which calls db.commit())
    without leaking state into other tests or requiring a full reseed
    per test.
"""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# ── Make `app` and `shared` importable ─────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL1_ROOT = Path(__file__).resolve().parents[1]
for p in (str(MODEL1_ROOT), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

TEST_DB_URL = "postgresql://sentinel:sentinel_dev@127.0.0.1:5432/sentinel_test"
TEST_DB_NAME = "sentinel_test"
ADMIN_DB_URL = "postgresql://sentinel:sentinel_dev@127.0.0.1:5432/postgres"

SEED_PASSWORD = "password123"  # matches README's documented demo accounts


def _run_psql(database: str, sql_file: Path) -> None:
    result = subprocess.run(
        [
            "psql",
            "-h", "127.0.0.1",
            "-U", "sentinel",
            "-d", database,
            "-v", "ON_ERROR_STOP=1",
            "-f", str(sql_file),
        ],
        env={"PGPASSWORD": "sentinel_dev", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"psql failed applying {sql_file.name} to {database}:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )


@pytest.fixture(scope="session")
def test_engine():
    """Build a fresh sentinel_test database from the real schema/triggers/seed
    once for the whole test session, and return an engine bound to it."""
    subprocess.run(
        ["psql", "-h", "127.0.0.1", "-U", "sentinel", "-d", "postgres",
         "-c", f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}";'],
        env={"PGPASSWORD": "sentinel_dev", "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["psql", "-h", "127.0.0.1", "-U", "sentinel", "-d", "postgres",
         "-c", f'CREATE DATABASE "{TEST_DB_NAME}" OWNER sentinel;'],
        env={"PGPASSWORD": "sentinel_dev", "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )

    db_dir = REPO_ROOT / "shared" / "db"
    _run_psql(TEST_DB_NAME, db_dir / "schema.sql")
    _run_psql(TEST_DB_NAME, db_dir / "triggers.sql")
    _run_psql(TEST_DB_NAME, db_dir / "seed.sql")

    engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """One test = one outer transaction + SAVEPOINT, rolled back at the end.

    App code calls ``session.commit()`` (see cameras.py / pages.py). Under a
    plain session that would end the test's transaction early. Instead we
    bind the session to a connection that already has an open outer
    transaction, and re-open a SAVEPOINT every time the inner transaction
    ends (i.e. every commit), so nothing the app does can escape the
    outer rollback.
    """
    connection = test_engine.connect()
    outer_trans = connection.begin()

    TestingSessionLocal = sessionmaker(bind=connection)
    session = TestingSessionLocal()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_trans.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    """A TestClient whose every request uses the isolated db_session."""
    from app.main import app
    from shared.db.session import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(c: TestClient, username: str, password: str = SEED_PASSWORD) -> TestClient:
    resp = c.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"login as {username} failed: {resp.text}"
    return c


# ── Seeded demo users (see shared/db/seed.sql) ─────────────────────
# admin_home -> dept_admin, Home Department (Police)
# admin_rto  -> dept_admin, Regional Transport Office (RTO)
# operator1  -> operator,   no department
# viewer1    -> viewer,     no department
#
# IMPORTANT: each of these builds its OWN TestClient (own cookie jar) even
# though they all share the same underlying `db_session` transaction. A
# previous version of this fixture set reused pytest's cached `client`
# fixture for every role, which meant "admin_home_client" and
# "admin_rto_client" were literally the same object with the same cookie
# jar — logging in as the second user silently logged the first one out
# for the rest of the test. That produced false-positive RBAC bugs
# (cross-department writes appearing to succeed because the "admin_home"
# client was actually authenticated as admin_rto by the time the test
# body ran). Keep these independent.


def _independent_client(db_session):
    from app.main import app
    from shared.db.session import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    c = TestClient(app)
    c.__enter__()
    return c


@pytest.fixture()
def admin_home_client(db_session):
    c = _independent_client(db_session)
    yield _login(c, "admin_home")
    c.__exit__(None, None, None)


@pytest.fixture()
def admin_rto_client(db_session):
    c = _independent_client(db_session)
    yield _login(c, "admin_rto")
    c.__exit__(None, None, None)


@pytest.fixture()
def operator_client(db_session):
    c = _independent_client(db_session)
    yield _login(c, "operator1")
    c.__exit__(None, None, None)


@pytest.fixture()
def viewer_client(db_session):
    c = _independent_client(db_session)
    yield _login(c, "viewer1")
    c.__exit__(None, None, None)


@pytest.fixture()
def anon_client(client):
    return client


def unique_camera_name(prefix: str = "Test Cam") -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"
