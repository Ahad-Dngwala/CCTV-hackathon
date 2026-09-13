# Platform — the shared app shell

Model 1, Model 2, and (in progress) Model 3 all run as one FastAPI
process, not three services. That's a real architectural decision, not
a shortcut: one process means one login session, one template engine,
one static-file mount, and one deployment story on a single VPS instead
of three services that all need to agree on auth. This document covers
the plumbing that decision requires — the parts of `model1-registry/`
that exist to hold the whole platform together rather than to
implement Model 1's own feature set. Model 1's actual feature
documentation is [docs/model1/README.md](model1/README.md); RBAC/audit/
transport security is [docs/SECURITY.md](SECURITY.md).

---

## 1. Why this code lives in `model1-registry/`

There's no fourth "platform" package — the app entrypoint
(`model1-registry/app/main.py`), the auth layer (`app/auth/`), and the
page router (`app/routers/pages.py`) all live inside the Model 1
package because Model 1 shipped first and the shell had to live
somewhere. Every model that came after mounts into it rather than
standing up its own app. Two different mounting strategies exist side
by side, and the difference is worth understanding before touching
either:

- **Model 2** is mounted by **runtime auto-discovery** — `main.py`
  globs every `.py` file in `model2_analytics/app/routers/` and loads
  it dynamically. Model 2's code never has to be imported by name
  anywhere in Model 1. (This is slated to be replaced with a normal
  static import, matching Model 3 below — see §3.)
- **Model 3** is mounted by an **ordinary import** —
  `from model3_federation.api.router import router as federation_router,
  start_federation_services, stop_federation_services`. It's a normal,
  static dependency: Model 1's entrypoint imports Model 3's package
  directly, by name, same as it imports its own routers.

## 2. Boot sequence (`main.py`'s `lifespan()`)

In order, on startup:

1. `init_engine(settings.DATABASE_URL)` — one SQLAlchemy engine for the
   whole app, all models.
2. A shared `queue.Queue` is created and stashed on `app.state.frame_queue`
   — Model 2's analytics pipeline reads frames off this queue. Model 1
   never writes to it; it's initialized here purely because this is
   where the app itself is initialized.
3. `IngestionSupervisor` (Model 2) and `CataloguePoller` (Model 2) are
   constructed and stashed on `app.state`. The poller makes a real HTTPS
   call to the government camera grid on every boot and retries with
   backoff on failure — fine in production, a real problem for a test
   suite with no network access, which is why
   `DISABLE_CATALOGUE_POLL=true` exists and is set unconditionally by
   `tests/conftest.py` before any app import.
4. `start_federation_services(...)` (Model 3) — registers each
   federation adapter's cameras and starts its event stream as its own
   background task. Non-blocking: startup doesn't wait for federation
   services to finish initializing before serving requests.
5. `yield` — app serves requests.
6. On shutdown: cancel the poll task, stop the ingestion supervisor,
   `stop_federation_services()`.

## 3. The Model 2 router auto-loader

`main.py`'s final block currently mounts Model 2's routers by loading
every file in `model2_analytics/app/routers/` off disk at runtime
(`importlib.util.spec_from_file_location`) rather than a normal package
import — this is being replaced with a static import, at which point
this section (and this line) goes away.

## 4. Templates, static files, and the detection-image exception

This app serves two kinds of files off disk, and they get treated
differently on purpose. `/static` — CSS, JS, the Leaflet map logic —
is public, no login required, same as static assets are everywhere.
Detection crop images from Model 2's pipeline are the opposite: they're
frames pulled from live surveillance, so serving them to anyone who
guesses a filename would be a real exposure. FastAPI's built-in static
file server (`StaticFiles`) can't tell those two cases apart — it has
no hook to require a login before handing back a file, it's public or
it's nothing. So the detection-image path isn't a `StaticFiles` mount
at all; it's a small hand-written route that checks the requester is
logged in and confirms the requested path can't escape its own folder
before it ever touches the filesystem — the one directory in this app
that actually holds sensitive imagery gets the one route that actually
checks who's asking.

`app.state.templates` is one `Jinja2Templates` instance shared by every
model's pages — `pages.py` renders Model 1, Model 2, and Model 3
templates through the same environment, off the same
`model1-registry/app/templates/` directory. There's no per-model
template namespace; a template belongs to whichever model its content
describes, not whichever directory convention might suggest.

## 5. The page router (`app/routers/pages.py`)

One `APIRouter`, no prefix, covering every HTML page in the platform —
Model 1's map/cameras/departments/districts/audit/gap-analysis pages,
Model 2's live grid/detection/watchlist/alerts/anpr/face-detection
pages, and Model 3's federation dashboard. They share this file for the
same reason they share one FastAPI app: one login redirect pattern
(`if not user: return RedirectResponse("/login")`), one template
environment, one nav shell. Splitting it per model would mean
duplicating that pattern three times for no functional gain — the cost
is that a file named for "pages" rather than a model requires reading
its section comments (`# ── Model 2 placeholders ──`, etc.) to know
which endpoints belong to which model, which is exactly why
[docs/model1/README.md](model1/README.md) enumerates Model 1's actual
page list explicitly rather than pointing here and leaving it implicit.

## 6. Configuration (`app/config.py`)

A single `pydantic-settings` `Settings` object, env-var or `.env`
driven, covers every model's configuration — database URL, JWT secret
and expiry, login rate-limit tuning, the government grid host/ports
(Model 2), and `REDIS_URL` for the federation event bus (Model 3). One
config object per app process, same reasoning as one template
environment: there's only one process to configure.

One fail-fast check lives here worth knowing about:
`SECRET_KEY` ships with a public, checked-in insecure default (needed
so local dev and the test suite work with zero setup), and the app
**refuses to start** if that default is still active while `DEBUG=False`
— see [docs/SECURITY.md](SECURITY.md) for why.
