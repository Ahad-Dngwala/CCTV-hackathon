# Sentinels — Gujarat CCTV Integration Platform — Project Context

> **Read this before doing anything else.** This is the internal working
> context for our team's build — not the official hackathon brief (that's
> `Context.md` from the hackathon portal, which this document summarizes
> and then extends with *our* decisions). Any AI assistant or teammate
> picking this project up should read this file first. Keep it updated as
> decisions change — stale context here is worse than no context.

---

## 0. The one rule that overrides everything else

**Do not optimize for "technically complete." Optimize for "the jury looks
at this for 30 seconds and knows it's different."**

The evaluation criteria (Step 7 of the brief) score architecture soundness,
interoperability, analytics quality, and scalability readiness — not
raw feature count. Dozens of teams will submit a map with pins on it and
call it Model 1. A working demo that checks every box but looks and feels
like every other submission will not stand out, and standing out is the
actual goal here, not just passing the checklist.

Every design decision below should be checked against this question:
**"Does this make a jury member say 'oh, that's a genuinely better way
to do this,' or does it just make the checklist green?"** If a feature
only does the latter, it's not disqualified — it's just not where our
effort goes first.

---

## 1. What the hackathon actually wants (condensed)

- 26 Gujarat govt departments run independent, heterogeneous CCTV systems
  (different vendors, VMS, storage, retention periods) across geographically
  scattered sites (up to ~1000km apart).
- Government wants these unified into one ecosystem, eventually integrated
  with law-enforcement databases (VAHAN, SARTHI, eGujCop, AFIS, NAFIS) for
  automated real-time alerts.
- Five reference architectures are offered (Model 1–4, or Hybrid/Custom).
  **Model 1 is explicitly the shared foundation** other models build on.
- **The actual scored test (Step 4):** onboard ~50 real, heterogeneous
  government-provided cameras, trace one designated vehicle by plate
  number across the network with timestamped movement history, and
  demonstrate live cross-referencing against a watchlist DB with
  real-time alert generation. This is model-agnostic — whatever
  architecture we pick has to survive this test.
- Long-term ambition stated in the brief: ~80,000 cameras statewide.
  We don't need to build that — we need to *credibly explain* how our
  architecture gets there without a redesign.

Full official spec lives in the uploaded `Context.md` — this doc doesn't
replace it, it's our working interpretation + our decisions on top of it.

---

## 2. Our chosen approach

**Sequencing:** Model 1 (Registry & GIS Foundation) first, standalone and
solid, then Model 2 (Unified Viewing & Analytics) on top of it — since
Model 2 is where ANPR + watchlist correlation live, and that's what Step 4
actually scores. Model 3/4/Hybrid framing is a later decision once 1+2
are real and working; we will not stretch thin chasing every model.

**Tech stack — deliberately not the "suggested" one:**

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** (not Node.js/Django) | Async-native — this system is I/O-bound (many camera connections, WebSocket pushes, concurrent DB writes). Same language as our AI/analytics layer (OpenCV, ANPR models), so Model 2 doesn't need a separate service just to talk to Model 1. |
| Frontend | **Leaflet + Jinja2 templates + HTMX/Alpine.js** (no React, no Node, no build step) | Model 1 is map- and interaction-heavy, not component-state-heavy. No npm/node_modules to manage, no build pipeline, served straight from FastAPI. |
| Database | **PostgreSQL + PostGIS** | Required, not optional — Model 1 is a *GIS* foundation, and gap-analysis (coverage holes) needs real spatial operations (buffers, polygon containment), not just lat/lng floats. PostGIS is a lightweight extension, not a heavy separate service — negligible overhead at our scale. |
| Time-series (deferred) | **TimescaleDB — not yet** | Solves a different problem (high-volume timestamped data: health-check logs, ANPR events, vehicle-position history). Not needed while Model 1 only tracks *current* status. Introduce it when Model 2's event/detection logging reaches real volume — call this out explicitly in the HLD's scalability section as the intended future addition. |
| Streaming (Model 2+) | **MediaMTX (Go, open source)** for RTSP→WebRTC/HLS bridging, custom Go glue via **Pion** where needed | Don't hand-roll a WebRTC stack — MediaMTX already does RTSP/RTMP/ONVIF ingestion and WebRTC/HLS re-serving. Use Go where it earns its keep (a real media server), not just because we know Go. |
| Deployment | Docker Compose locally and on a VPS for consistency; Nginx/Caddy reverse proxy + TLS | Keep local/VPS parity so "works on my machine" isn't a demo-day risk. |

**Hard constraint:** everything in the stack must be fully open source —
no proprietary VMS SDKs as a dependency for the core platform. Camera
hyperlinks to native VMS software (see §3) are an exception since they
link *out* to existing departmental infra, not something we depend on.

---

## 3. Model 1 — detailed spec

**Map:**
- Leaflet + OpenStreetMap base layer.
- Camera markers, clustered (Leaflet.markercluster) for the "flock" effect
  at low zoom — clusters resolve into individual cameras as you zoom into
  a district/city.
- **Custom-designed marker icons — not default Leaflet pins.** Each
  status (online / offline / maintenance) and each department gets its
  own deliberately designed icon, not a color-tinted stock pin. This is
  one of the "make it look different" investments — a jury scrolling
  through submissions will visually clock ours as distinct in the first
  two seconds.
- Layer toggle control: filter by department (Home/Police, Food & Civil
  Supplies, RTO, Municipal Corporations, etc.).
- **Filter by district** (not just "city") — Gujarat's actual
  administrative unit is the district (33 total), and the brief names
  specific districts (Valsad, Dahod, Somnath, Jamnagar, Dwarka) as
  deployment points. This reads as us understanding the real geography,
  not a generic template.
- Click a marker → side panel/popup with metadata: department, camera
  type, ownership, connectivity status, storage/retention details.
  **Optional hyperlink out to the camera's native VMS viewer** — honest
  about what Model 1 is (registry only, no centralized video) while
  visibly gesturing at how it plugs into Model 2+.

**Required but easy to underweight (don't skip these for map polish):**
- Bulk import + manual entry + API-based onboarding.
- Camera health/maintenance-status tracking.
- Gap-analysis report generation (uncovered zones, ageing infrastructure)
  — this is where PostGIS spatial queries actually get used, not just for
  display.
- Role-based search, filter, export, and metadata **audit trail**.

**Data model sketch (to refine as we build):**
- `cameras`: id, name, department_id, location (PostGIS geography point),
  district, camera_type, ownership, connectivity_status, storage_type,
  retention_days, vms_url (nullable), created_at, updated_at.
- `departments`: id, name.
- `status_history` / audit log: camera_id, changed_field, old_value,
  new_value, changed_by, changed_at — plain Postgres table for now, not
  Timescale (see §2 rationale).
- `districts`: id, name, boundary (PostGIS polygon) — needed for
  gap-analysis and the district filter.

---

## 4. Model 2 — analytics pipeline & watchlist spec

Not a single ANPR model — a small pipeline:

1. **Vehicle detection** — localize vehicles in-frame; feeds both plate
   detection and cross-camera tracking.
2. **Plate detection** — localize plate region within the vehicle crop
   (YOLO-family, fine-tuned on Indian plate proportions/fonts — generic
   pretrained detectors underperform here, usually trained on US/EU plates).
3. **OCR / character recognition** — PaddleOCR / EasyOCR / small CRNN.
   Separate failure mode from detection: finding the plate ≠ reading it right.
4. **Cross-camera vehicle tracking / route reconstruction** — this is what
   Step 4's scored test actually is ("trace the vehicle across the network").
   Primary: join detections into a track by plate string + timestamp.
   Fallback when OCR fails at one camera: appearance-based re-id (color,
   vehicle type, rough embedding) so one bad read doesn't break the route.
5. **Bonus/stretch, not core path**: face recognition vs. person-watchlist,
   generic object/anomaly detection (intrusion, crowding). These appear in
   the HLD's analytics ask and Model 4's feature list but are not what
   Step 4 scores — don't let them dilute the vehicle pipeline.

"Event tagging/indexing" in the brief is a data-pipeline concern, not a
model: every detection is tagged with `camera_id`, `timestamp`,
`department`, and a watchlist-match id if any, and indexed so "searchable
vehicle-movement records" is a query, not a separate feature.

**Watchlist DB schema:**

- `vehicles_watchlist`: id, plate_number (normalized), category
  (stolen/wanted/blacklisted), reported_date, department, description, status
- `persons_watchlist` (bonus scope): id, name, category
  (wanted/missing/suspect), face_embedding, status
- `detections`: id, camera_id, timestamp, detected_plate, confidence,
  cropped_image_path, vehicle_track_id (nullable — groups detections of
  the same physical vehicle across cameras)
- `alerts`: id, detection_id, watchlist_id, alert_type, severity,
  created_at, acknowledged_by, acknowledged_at
- `vehicle_tracks`: id, plate_number, first_seen, last_seen — the route
  itself is a query joining `detections` on `vehicle_track_id`, ordered
  by timestamp

Every incoming detection is matched against `vehicles_watchlist` near
real-time; a match writes an `alerts` row and pushes to the dashboard
over WebSocket.

**Interoperability inside Model 2 (not Model 3):** Model 2 explicitly
connects to each VMS *directly*, with no intermediate middleware/
federation layer — that's what distinguishes it from Model 3. We are not
building Model 3. But the brief's architecture mandate ("documented
standard APIs, open protocols, SDKs, modular adapter-based frameworks,
avoid vendor lock-in") applies regardless of which model number we picked.
So: our VMS-connection code still uses a clean **adapter pattern** — one
adapter class per vendor/VMS, all implementing the same interface
(`connect()`, `get_stream()`, `get_metadata()`) — and leans on **ONVIF**
wherever a camera supports it, since that's the actual industry-standard
protocol for this exact cross-vendor problem. This isn't "building Model
3," it's engineering that happens to satisfy the same mandate — and it
means extending toward Model 3 later, if we ever want to, doesn't require
ripping anything out.

## 5. Evaluation discipline — precision / recall / F1, never bare "accuracy"

Mandate: every analytics stage reports precision, recall, and F1 — never
a single accuracy number. This is a **rule-0 differentiator**, not just
correctness: watchlist hits are rare events (a small % of traffic), so a
model that says "no match" every time scores misleadingly high on
accuracy alone while being useless. Most competing teams will report one
shiny accuracy % because it sounds good in a slide; a real confusion
matrix signals we understand what we built.

Apply separately at each stage — they measure different failures:

- **Plate detection**: precision/recall/F1 on IoU-thresholded boxes vs.
  ground truth (did we find the plate at all).
- **OCR read**: character-level accuracy AND full-plate exact-match rate,
  reported separately — a plate read "90% correct" character-wise is a
  0% useful match.
- **Watchlist alerting** (the headline number — this is what Step 4
  really tests): precision/recall/F1 on generated alerts. False
  positives flood the operator and get ignored; false negatives miss the
  wanted vehicle.
- **Cross-camera tracking** (if built): track-continuity precision/recall
  — correctly stitched the same vehicle's sightings without merging two
  different vehicles into one route.

Build a small hand-labeled test set from our own recorded feed (needed
anyway for the "Own-Feed Demonstration" deliverable) and run a real eval
harness against it for the output report — an actual measured report,
not a claimed number.

## 6. Open questions / not yet decided

- Hackathon deadline / how much time we actually have — affects how much
  of Model 1's "nice to have" list (full audit trail UI, bulk import UX
  polish) we build now vs. stub for the demo.
- Whether we go Model 2 next as planned, or evaluate Hybrid framing once
  Model 1 + 2 exist.
- Exact icon/visual design direction for markers (in progress — deliberately
  custom, not finalized).
- Watchlist DB schema and matching logic (Model 2 concern, not urgent yet).

---

## 5. Notes for whoever (human or AI) picks this up next

- Don't re-litigate the FastAPI/no-Node/no-React decision — it's made,
  and it's a defensible architecture call, not a shortcut. See §2 for why.
- Don't add TimescaleDB "just in case" — see §2, it's a deliberate deferral,
  not an oversight.
- Every UI decision gets checked against §0 before it gets checked against
  the feature checklist.
- Update this file when a decision changes — don't let it go stale while
  the actual build diverges from what's written here.