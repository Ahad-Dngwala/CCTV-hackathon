"""
model3_federation.registration
---------------------------------
Registers a connected VMS adapter's identity and camera inventory into
the shared cameras/vms_systems tables at startup.

Why this writes to the *shared* tables (shared/db/schema.sql) instead
of a model3-private schema: a department isn't guaranteed to run
exactly one VMS, and a VMS isn't guaranteed to be government-owned —
so "one VMS system" needed its own row (vms_systems), but the cameras
it reports are still just cameras. Model 1's own camera grid already
has a `cameras` table with department/location/status columns; giving
model3 a second, parallel `federated_cameras` table would mean the
same concept (a camera) lived in two places depending on which part
of the system happened to write it. Every camera model3 reports now
lands in that same `cameras` table, tagged with `vms_system_id` so
it's traceable to whichever VMS reported it — NULL vms_system_id
means "from the main grid or manually onboarded", not "federated".

Why this exists instead of a seed file: each adapter (police/rto/muni)
already knows its own system_id, system_name, vendor, and camera list —
that's what get_cameras() and the system_* properties on VMSAdapter are
for. federation_seed.sql used to duplicate all of that as hand-written
SQL literals with the same UUIDs, names, and coordinates. Two sources
of truth for the same data drift apart silently — a camera renamed or
added in an adapter's Python code just would not show up in the DB
until someone remembered to also edit the SQL file, and vice versa.

An adapter is meant to be Model 3's interface to an *external* VMS —
the external system owns its own camera list, we're just reporting
what it told us. So at startup we ask each adapter what it has and
upsert exactly that, instead of pre-loading fabricated inventory (or,
as federation_seed.sql also did, fabricated historical detection
events and correlations) into the database.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional, Sequence

from model3_federation.adapters.base import VMSAdapter
from model3_federation.schemas.models import FederatedCamera

logger = logging.getLogger("sentinel.federation.registration")


def _resolve_department_id(
    session, department_hint: Optional[str], adapter_name: str
) -> Optional[str]:
    """
    Match an adapter's plain-English department hint (e.g. "Police") against
    departments.name/category. Returns None on no match rather than guessing —
    cameras.department_id has no NOT NULL constraint, so leaving it unset is
    safe and honest; picking an arbitrary department would not be.

    A silent None used to be the only outcome visible anywhere for a hint
    that stops matching (department renamed, adapter typo, a genuinely new
    department not yet in `departments`) — no error, no log line, nothing
    an admin would see. This logs a warning whenever the hint doesn't
    resolve to exactly one department:

      * zero matches — department_id will be NULL, with no other signal
        of why. Naming the adapter and the exact hint string here is what
        makes that diagnosable instead of a silent, unexplained NULL.
      * more than one match (e.g. a short, generic hint) — previously an
        undocumented `LIMIT 1` with no ORDER BY, i.e. "whichever row the
        planner happens to return first," which isn't guaranteed stable
        across Postgres versions/plans. `ORDER BY id` below makes the pick
        deterministic; this warning makes it visible that a pick is even
        being made, so a too-generic hint gets noticed and tightened.
    """
    if not department_hint:
        return None
    from sqlalchemy import text

    rows = session.execute(text(
        "SELECT id, name FROM departments WHERE name ILIKE :pat OR category ILIKE :pat "
        "ORDER BY id"
    ), {"pat": f"%{department_hint}%"}).fetchall()

    if not rows:
        logger.warning(
            "Adapter %s: department hint %r matched no department; "
            "department_id will be NULL.",
            adapter_name, department_hint,
        )
        return None

    if len(rows) > 1:
        matched_names = ", ".join(r[1] for r in rows)
        logger.warning(
            "Adapter %s: department hint %r matched %d departments (%s); "
            "using %r. Consider a more specific hint in the adapter's "
            "camera data.",
            adapter_name, department_hint, len(rows), matched_names, rows[0][1],
        )

    return str(rows[0][0])


def _upsert_system_and_cameras(
    db_session_factory: Callable,
    adapter: VMSAdapter,
    cameras: Sequence[FederatedCamera],
    ownership: str,
) -> None:
    """Synchronous DB work — run in a thread executor, same pattern as the correlation engine."""
    from sqlalchemy import text

    session = db_session_factory()
    try:
        department_hint = cameras[0].department if cameras else None
        department_id = _resolve_department_id(
            session, department_hint, adapter.system_name
        )

        # `protocol` used to be hardcoded to the literal string
        # 'simulated' here regardless of which adapter this was — true
        # for the three demo adapters, false the moment a real adapter
        # exists. Falls back to 'simulated' only for adapters that
        # don't declare an adapter_type (the three demo ones), so
        # nothing about their behavior changes.
        protocol = getattr(adapter, "adapter_type", None) or "simulated"

        session.execute(text(
            """
            INSERT INTO vms_systems
              (id, name, vendor, protocol, adapter_type, config, ownership, department_id, department_hint, status, camera_count, last_heartbeat)
            VALUES
              (:id, :name, :vendor, :protocol, :adapter_type, :config, :ownership, :dept, :dept_hint, 'connected', :count, now())
            ON CONFLICT (id) DO UPDATE
            SET status          = 'connected',
                protocol        = :protocol,
                department_id   = COALESCE(vms_systems.department_id, EXCLUDED.department_id),
                department_hint = EXCLUDED.department_hint,
                camera_count    = :count,
                last_heartbeat  = now()
            """
        ), {
            "id": adapter.system_id,
            "name": adapter.system_name,
            "vendor": adapter.vendor,
            "protocol": protocol,
            # adapter_type/config are set on INSERT only (config-driven
            # rows are created via POST /systems, which already writes
            # these columns) — re-registration on reconnect shouldn't
            # overwrite a row's own config with NULL for adapters that
            # don't carry one (the three demo adapters).
            "adapter_type": getattr(adapter, "adapter_type", None),
            "config": None,
            "ownership": ownership,
            "dept": department_id,
            "dept_hint": department_hint,
            "count": len(cameras),
        })

        for cam in cameras:
            if cam.lat is not None and cam.lng is not None:
                location_sql = "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::GEOGRAPHY"
            else:
                location_sql = "NULL"

            session.execute(text(
                f"""
                INSERT INTO cameras
                  (name, source_grid_id, vms_system_id, department_id,
                   location, location_label, ownership, connectivity_status, is_active)
                VALUES
                  (:name, :ext, :sys, :dept,
                   {location_sql}, :label, :ownership, 'online', :active)
                ON CONFLICT (vms_system_id, source_grid_id) DO UPDATE
                SET name                = :name,
                    location            = {location_sql},
                    location_label      = :label,
                    connectivity_status = 'online',
                    is_active           = :active
                """
            ), {
                "sys": adapter.system_id,
                "ext": cam.external_id,
                "name": cam.name,
                "dept": department_id,
                "lat": cam.lat,
                "lng": cam.lng,
                "label": cam.location_label,
                "ownership": ownership,
                "active": cam.is_active,
            })

        session.commit()
        logger.info(
            "Registered %s (%d cameras) into cameras/vms_systems.",
            adapter.system_name, len(cameras),
        )
    except Exception:
        session.rollback()
        logger.error("Failed to register adapter %s", adapter.system_name, exc_info=True)
        raise
    finally:
        session.close()


def _load_dynamic_adapter_rows(db_session_factory: Callable) -> list[dict]:
    """Synchronous DB read — run in a thread executor.
    Rows with a non-NULL adapter_type are the config-driven onboarding
    path (POST /systems with adapter_type + config, see api/router.py);
    every other row (adapter_type IS NULL) is either a demo adapter's
    own row or a record-only manual onboarding, neither of which this
    loads or touches."""
    from sqlalchemy import text

    session = db_session_factory()
    try:
        rows = session.execute(text(
            "SELECT id, name, adapter_type, config, ownership "
            "FROM vms_systems WHERE adapter_type IS NOT NULL"
        )).fetchall()
        return [
            {"id": str(r[0]), "name": r[1], "adapter_type": r[2], "config": r[3] or {}, "ownership": r[4]}
            for r in rows
        ]
    finally:
        session.close()


async def load_dynamic_adapters(db_session_factory: Callable) -> list[VMSAdapter]:
    """
    Called once at startup (alongside the hardcoded Police/RTO/Municipal
    adapters in start_federation_services) to bring back every
    config-driven VMS system that was onboarded through POST /systems
    with an adapter_type, so a restart doesn't silently drop them.

    Returns only adapters that actually connected — a row whose key
    now fails (revoked, camera moved, wrong password) is logged and
    left in the DB as 'disconnected' rather than crashing startup;
    fixing it is the same "edit and re-test" flow as onboarding it the
    first time, not a special recovery path.
    """
    from model3_federation.adapters.registry import build_adapter

    rows = await asyncio.get_running_loop().run_in_executor(
        None, _load_dynamic_adapter_rows, db_session_factory
    )

    live_adapters: list[VMSAdapter] = []
    for row in rows:
        try:
            adapter = build_adapter(row["adapter_type"], row["id"], row["name"], row["config"])
        except ValueError as exc:
            logger.error("Skipping vms_systems row %s (%s): %s", row["id"], row["name"], exc)
            continue

        connected = await adapter.connect()
        if not connected:
            logger.warning(
                "Dynamic adapter %s (%s) did not connect on startup; "
                "will stay 'disconnected' until re-tested/re-saved.",
                row["name"], row["adapter_type"],
            )
            continue

        await register_adapter(db_session_factory, adapter, ownership=row["ownership"] or "government")
        live_adapters.append(adapter)

    return live_adapters


async def register_adapter(
    db_session_factory: Callable,
    adapter: VMSAdapter,
    ownership: str = "government",
) -> None:
    """
    Ask a connected adapter for its camera inventory and upsert its
    system + camera rows into the shared cameras/vms_systems tables.
    Call this once per adapter after adapter.connect() succeeds and
    before starting its event stream, so the correlation engine's
    camera lookups resolve.

    `ownership` defaults to "government" since Police/RTO/Municipal are
    all government systems today; pass ownership="private" when a
    future adapter represents a private-vendor VMS instead (a mall or
    society's own system Sentinel has been given read access to).
    """
    cameras = await adapter.get_cameras()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, _upsert_system_and_cameras, db_session_factory, adapter, cameras, ownership
    )
