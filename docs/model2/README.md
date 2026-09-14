# Model 2 — Unified Viewing Platform & Live Analytics Engine

Model 2 is the operational core of Sentinel that answers the second
fundamental question in this problem space: *how do command center
operators view, monitor, and run automated analytics across dozens of
independent departmental camera systems simultaneously, without ripping
out existing VMS infrastructure or drowning in multi-terabyte centralized
video storage?*

Today, twenty-six Gujarat state departments operate disparate CCTV
installations through isolated, closed Video Management Systems (VMS).
For an operator in a central command center, tracking an incident across
department boundaries means switching between physically separate viewer
stations, juggling incompatible proprietary client software, and manually
scanning hours of raw footage.

Model 2 solves this by implementing the **Unified Viewing Platform**
specified in the Hackathon Brief, structured around three core architectural
principles:

1. **Direct Connection Without Middleware**: The platform connects directly
   to each departmental CCTV or VMS stream via RTSP (forced over TCP),
   aggregating video feeds into a unified control-room interface without
   introducing an intermediate transcoding middleware or federation proxy layer.
   Existing departmental VMS recorders and local storage continue to operate
   completely undisturbed.
2. **Centralized Viewing & Operational Accessibility**: A responsive,
   multi-camera matrix grid (`/grid`) delivers 2×2, 3×3, and 4×4 video walls
   directly into the browser via low-latency WebRTC WHEP and HLS relay, backed
   by server-side MJPEG fallback relays (`app/routers/streams.py`) to
   sidestep browser codec limitations.
3. **Selective Metadata Generation Over Bulk Storage**: Sentinel
   deliberately rejects the unmaintainable brute-force approach of
   re-recording 24/7 raw video centrally. Instead, the AI inference
   pipeline extracts **selective metadata** in real time: YOLOv8 vehicle
   detections, multi-frame vehicle tracking, automated license plate
   recognition (ANPR), and cross-camera movement records. Raw bulk video
   is discarded after frame evaluation; only confirmed sightings, journey
   tracks, cropped thumbnails, and security alerts are persisted to
   PostgreSQL.

To deliver this, Model 2 integrates four operational capabilities:

- **Unified Control-Room Video Wall (`/grid`)**: Multi-tile matrix switching
  (2×2, 3×3, 4×4) across up to 30 live departmental cameras with instant
  spotlight modal inspection and stream URL telemetry.
- **AI Vehicle Detection, Tracking & Native ANPR Pipeline (`/detection`)**:
  A continuous, single-pass visual pipeline combining Indian Traffic YOLOv8
  inference (classifying cars, auto-rickshaws, buses, trucks, mini-trucks,
  motorcycles), in-frame IoU + spatial centroid tracking with EMA smoothing, and
  native license plate character recognition normalized against standard Indian
  state and Bharat Series patterns (`GJ01AB1234`, `22BH1234AA`).
- **Dual Ingestion Paths (Live Streams + Forensic Video Upload)**:
  Operates identically across continuous 24/7 live camera grid streams
  (`cam04`, `cam22`) or high-capacity forensic video uploads (`/recorded-detection`,
  supporting files up to 2 GB) with OpenCV metadata probing and execution
  throttling (`1x Realtime`, `2x Fast Scan`, `Max Speed ⚡`) in isolated daemon threads.
- **Target Watchlist & Automated Incident Alerting (`/watchlist`, `/alerts`)**:
  Real-time sub-millisecond correlation against active vehicle targets,
  enriching alerts with camera geolocation and pushing instant notifications
  over WebSockets (`/ws/detections`).

> [!NOTE]
> **Biometric Facial Recognition Seam**: In addition to the primary vehicle
> and ANPR tracking engine, Model 2 includes a fully realized biometric
> facial recognition system (5-gate face quality screening, 512-dimensional
> InceptionResnetV1 embeddings, and PostgreSQL `pgvector` cosine similarity
> matching) with dedicated UI portals (`/watchlist/persons` and
> `/face-detection`). To preserve architectural clarity for evaluators, this
> biometric pipeline is documented in depth in [§5](#5-biometric-watchlist-person-watchlist--5-gate-ai-quality-pipeline)
> and [§6](#6-surveillance-video-face-detection-matching--live-alerting) as
> an isolated, asynchronous intelligence subsystem that runs independently of
> the main vehicle tracking pipeline.

---

## 1. Architecture at a glance

```
   [SOURCE A: Live CCTV Streams]                  [SOURCE B: Forensic Evidence Upload]
     (30 Departmental RTSP Feeds,                    (User Video Uploads up to 2 GB:
       H.264/HEVC, port 8554)                         .mp4, .avi, .mov, .mkv, .webm)
                 │                                                  │
                 ▼                                                  ▼
     Direct Ingestion Supervisor                        Pre-Recorded Video Worker
     (CataloguePoller -> /api/ingest,                   (OpenCV metadata probe, frame PTS,
      StreamWorkers, forced TCP)                         speed throttle: 1x / 2x / max)
                 │                                                  │
       ┌─────────┴─────────┐                                        │
       ▼                   ▼                                        │
Unified Video Wall     Frame Queue                                  │
  (/grid Relay:      (app.state.                                    │
   MediaMTX HLS/     frame_queue,                                   │
   WHEP + MJPEG)      maxsize=500)                                  │
                           │                                        │
                           └───────────────────┬────────────────────┘
                                               │
                                               ▼
                                  Indian Traffic YOLOv8 Detector
                                 (Specialized: Cars, Auto-Rickshaws,
                                  Trucks, Buses, Mini-Trucks, Bikes)
                                               │
                                               ▼
                                       In-Frame Tracker
                                    (IoU + Spatial Proximity,
                                     EMA Bounding-Box Smoothing)
                                               │
                                               ▼
                                    Integrated ANPR Pipeline
                                 (Plate Crop, OCR Extraction,
                                  Regex Validation: GJ01.. / 22BH..)
                                               │
                                               ▼
                                   Target Watchlist Matcher
                                 (vehicles_watchlist DB lookup,
                                  Severity: low/med/high/critical)
                                               │
                       ┌───────────────────────┴───────────────────────┐
                       ▼                                               ▼
           PostgreSQL + Disk Storage                       Real-Time WebSocket Push
        (detections, vehicle_tracks,                      (Live Boxes & Sighting Events:
         alerts, detection-image/)                         /ws/detections, /ws/recorded)
```

Three design principles govern this architecture:

### I. The Direct-Connection Seam vs. The Federation Layer
The hackathon brief explicitly demands that feeds be accessed *"through a
single interface without introducing an intermediate middleware or federation
layer."* Sentinel respects this distinction cleanly:
- **Model 2 (Live RTSP Path)**: Connects straight from `IngestionSupervisor`
  to each camera stream over raw RTSP TCP. No transcode proxy, no broker, no
  federation bridge sits in between. What the camera outputs is what the
  worker ingests.
- **Protocol Boundary Disclosure**: Ingestion via ONVIF, vendor SDKs, or
  REST APIs exists in the repository under `model3_federation/adapters/`
  (`OnvifVMSAdapter`, `RestApiVMSAdapter`). Those adapters are currently wired
  to onboard external cameras into the registry database; the active, live
  video analytics pipeline in Model 2 is intentionally driven by direct RTSP
  transport. Acknowledging this seam upfront shows architectural honesty: RTSP
  is live, production-grade, and direct; vendor SDK onboarding exists as an
  on-ramp without bloating the real-time frame pipeline.

### II. Decoupled Ingestion & Worker Isolation (The In-Memory Frame Queue)
Decoding H.264/HEVC video over variable-latency networks cannot run on the
FastAPI event loop. Model 2 decouples stream capture from AI inference via
an in-memory, thread-safe queue:
- `IngestionSupervisor` (`app/ingestion/supervisor.py`) spins up one
  `StreamWorker` thread per active camera.
- Each worker captures frames, synchronizes strictly off the presentation
  timestamp (`CAP_PROP_POS_MSEC`), and puts decoded `FramePacket` objects into
  `app.state.frame_queue` (maximum 500 frames).
- If inference temporarily falls behind, the ingestion layer drops frames
  rather than buffering stale video. The analytics pipeline processes what is
  live now, not what happened three seconds ago.
- Similarly, pre-recorded forensic video analysis (`PreRecordedVideoWorker`)
  runs inside its own isolated daemon thread, ensuring that heavy 2 GB video
  decoding and user playback actions (pause, resume, speed shifts) never starve
  live camera ingestion workers or block HTTP requests.

### III. Selective Metadata Generation (Zero Central Video Storage)
Rather than streaming gigabytes of raw video back to a central datacenter,
the pipeline discards raw image matrices the instant inferences finish.
Only high-value intelligence is retained:
- Bounding boxes and class confidence scores.
- Standardized plate strings normalized by Indian license plate regex.
- High-resolution vehicle and license plate thumbnail crops saved to
  `detection-image/`.
- Sighting rows inserted into `detections`, joined with cross-camera
  `vehicle_tracks`.
- Watchlist violation records inserted into `alerts` and broadcast over
  WebSockets.

The result is a system that scales linearly with network bandwidth and
storage capacity: central storage grows with *incidents*, not with *camera count*.

---

## 2. Data model

Six PostgreSQL tables carry Model 2's feature set, dividing cleanly into the
**Vehicle Movement & Alerting schema** (four tables) and the **Biometric Facial
Intelligence schema** (two tables). Full DDL lives in `shared/db/schema.sql`,
with ANPR extended columns in `migrations/003_detections_anpr_columns.sql`.
SQLAlchemy ORM models are in `shared/db/models.py`.

| Table | Owns | Relational & Indexing Notes |
|---|---|---|
| `vehicles_watchlist` | Target plates, category, reporting department, status | `idx_vehicles_watchlist_plate`; DB `CHECK` on `category` (`stolen`, `wanted`, `blacklisted`) and `status` (`active`, `resolved`) |
| `vehicle_tracks` | Synthesized cross-camera vehicle journeys | Indexed on `plate_number`; aggregates `first_seen`, `last_seen`, `vehicle_type`, `is_watchlisted` |
| `detections` | Instantaneous sightings emitted by video workers | FK to `cameras.id` (`RESTRICT`) and `vehicle_tracks.id` (`SET NULL`); composite index `idx_detections_camera_time` |
| `alerts` | Verified watchlist matches with audit lifecycle | FK to `detections.id` (`CASCADE`) and `vehicles_watchlist.id` (`RESTRICT`); indexed by `watchlist_id` and `created_at DESC` |
| `persons_watchlist` | Target individuals and reference face portraits | `VECTOR(512)` pgvector embeddings; HNSW cosine index `idx_persons_watchlist_embedding` |
| `person_alerts` | Biometric face match alerts from video analysis | FK to `persons_watchlist.id` (`CASCADE`); records `similarity_score`, `distance`, `face_crop_path` |

Model 2 also writes the **grid-sync columns** on the shared `cameras` table
(`source_grid_id`, `codec`, `rtsp_url`, `whep_url`, `hls_url`, `grid_synced_at`)
via `CataloguePoller` (`app/ingestion/catalogue.py`).

---

### Migration 003: ANPR Schema Evolution (`migrations/003_detections_anpr_columns.sql`)
To support native ANPR without breaking existing detection rows or locking
active tables, Migration 003 appended non-blocking nullable columns to `detections`:
- `ocr_confidence`, `plate_confidence`: Dual confidence metrics (YOLO plate localization vs OCR text recognition).
- `plate_crop_path`: Direct disk reference to the tight license plate bounding box crop.
- `anpr_provider`: Provenance tag (`awiros`, `fastalpr`, `onnx_ocr`, or `paddleocr`).
- `source_type`: Differentiates continuous `live_stream` from forensic `recorded_upload`.
- `video_timestamp_ms`: Preserves native video presentation timestamp for recorded footage.
- **Optimized Indices**: Added `idx_detections_provider` and `idx_detections_plate_time` (`detected_plate, timestamp DESC`) for sub-millisecond timeline queries.

---

### Key Architectural Seams

Four relational boundaries govern this schema:

1. **Sighting vs. Track Seam (`detections` vs. `vehicle_tracks`)**:
   `detections` stores single-camera instantaneous sightings with crops and confidence.
   `vehicle_tracks` aggregates those sightings across time and cameras into a persistent
   journey. `DetectionWriter` links them via `detections.vehicle_track_id`, enabling
   instant route reconstruction queries without full table scans.
2. **Sighting vs. Alert Seam (`detections` vs. `alerts`)**:
   An alert is not a boolean column; it is an auditable incident entity. It enforces
   database-level severity checks (`critical`, `high`, `medium`, `low`) and requires
   an attributable user signature (`acknowledged_by`, `acknowledged_at`). Foreign key
   `ON DELETE RESTRICT` ensures an active target cannot be deleted while alert cases
   remain open.
3. **Native Vector Embedding Seam (`persons_watchlist.face_embedding`)**:
   Uses PostgreSQL `pgvector` with HNSW cosine indexing (`vector_cosine_ops`) instead
   of an external vector DB. Embeddings, metadata, and portraits commit within a single
   ACID transaction, giving sub-millisecond 1:N similarity searches (`<=> <= 0.30`)
   with zero cache lag.
4. **Audit & State Enforcement**:
   Status transitions across both watchlists are bound by DB-level `CHECK (status IN ('active', 'resolved'))`.
   Marking a target `resolved` silences future alerts while preserving the forensic
   investigation history. Hard deletes cleanly cascade associated image crops from disk.

---

---

## 3. The Unified Viewing Platform & Direct Ingestion

The core of the Hackathon Brief requires connecting directly to departmental
CCTV streams without introducing an intermediate middleware or federation layer,
leaving existing departmental VMS installations undisturbed.

Teams often default to inserting a heavyweight transcoding proxy (Nginx RTMP,
Wowza) that re-encodes streams, buffers raw video, and doubles bandwidth.
Sentinel rejects this: **the connection is truly direct.**

```
Departmental CCTV/VMS ──▶ RTSP over TCP (port 8554) ────▶ StreamWorker (app.state.frame_queue)
(Undisturbed, raw)   ├──▶ WebRTC WHEP (port 8889)  ────▶ Browser <video> (Low-latency preview)
                     ├──▶ HLS CDN (cctv.corp8.cloud) ───▶ HLS.js (Matrix Grid Wall)
                     └──▶ Server MJPEG (/streams.py) ───▶ Fallback Relay (Viewer-aware)
```

---

### 1. Direct Connection on the Wire: Ingestion Supervisor & StreamWorker

Stream capture runs through two dedicated classes in `model2_analytics/app/ingestion/`:

- **`StreamWorker` (`worker.py`)**: One background daemon thread per active camera.
  It opens an OpenCV `VideoCapture` pipeline bound directly to the camera's RTSP endpoint.
  To prevent UDP packet-drop artifacts and H.264 macroblock corruption over congested links,
  it forces TCP transport via `os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"`.
  All frame timestamps are driven strictly by stream presentation timestamps
  (`pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)`), never wall-clock time. Decoded frames
  are wrapped in `FramePacket` (`shared/adapters/base.py`) and pushed into `app.state.frame_queue`
  via non-blocking `put_nowait()`. If the 500-slot queue fills during heavy inference,
  frames drop gracefully to guarantee the analytics engine processes live truth, not laggy history.
- **`IngestionSupervisor` (`supervisor.py`)**: Manages the lifecycle of all camera worker
  threads. It reads active cameras from PostgreSQL, diffs them against running threads,
  spawns new workers for newly activated streams, and cleanly terminates workers for
  decommissioned feeds. If a camera NIC drops offline, it backs off exponentially
  (starting at 2s, doubling per failure, capped at 30s) to prevent network thrashing.
- **Loop-Point Discontinuity Handling**: Surveillance feeds frequently loop, causing
  abrupt negative presentation timestamp resets. `StreamWorker` detects negative PTS
  deltas, re-synchronizes tracker state, and logs an informational scene-cut rather than
  crashing the worker.

---

### 2. The Dynamic Catalogue Poller (`CataloguePoller`)

Camera URLs, resolutions, and operational states change constantly across government
installations. Hard-coding stream endpoints in seed scripts is a fatal flaw.

Model 2 implements `CataloguePoller` (`app/ingestion/catalogue.py`), which periodically
queries the media gateway's `/api/ingest` endpoint:
- **Dynamic Catalogue Discovery**: Inspects all 30 live cameras—capturing source grid ID,
  departmental attribution, physical district, declared resolution, framerate, codec
  (`H.264` or `H.265`), and stream URLs.
- **Atomic Database Upsert**: Calls `upsert_cameras_to_db()`, matching on `source_grid_id`.
  It preserves Model 1's administrative fields (ownership, retention policy, manual notes)
  while atomically updating stream endpoints (`rtsp_url`, `whep_url`, `hls_url`) and
  setting `grid_synced_at = now()`.
- **MediaMTX Auto-Registration**: For any camera flagged `is_live = true`, `_sync_cameras()`
  in `app/main.py` registers the RTSP source with the MediaMTX streaming gateway via
  `register_stream_in_mediamtx()`, ensuring instant browser availability without manual
  server restarts.

---

### 3. Dual-Host Streaming Matrix & The Server MJPEG Relay

Streaming 30 live cameras to browser control rooms spans two distinct hosts,
built dynamically by `_build_stream_urls()` in `app/routers/grid.py`:

| Protocol | Endpoint Template | Host | Purpose & Client |
|---|---|---|---|
| **RTSP** | `rtsp://<host>:8554/stream/{cam_tag}` | `GRID_RTSP_HOST` (`103.250.160.189`) | Primary ingestion for AI inference (`StreamWorker`, OpenCV) |
| **WebRTC WHEP** | `http://<host>:8889/stream/{cam_tag}/whep` | `GRID_RTSP_HOST` (same static IP) | Ultra-low latency browser playback (<500ms) |
| **HLS** | `https://cctv.corp8.cloud/{cam_tag}/index.m3u8` | `GRID_CDN_HOST` (`cctv.corp8.cloud`) | High-concurrency matrix grid video wall (HLS.js) |
| **Server MJPEG** | `/api/v1/cameras/{id}/live` | Sentinel App Server | Fallback stream relay for firewalled WebRTC or HEVC gaps |

#### The Server-Side MJPEG Relay Fallback (`app/routers/streams.py`)
Modern browsers still lack ubiquitous hardware decode support for H.265/HEVC,
and restrictive government enterprise firewalls routinely block WebRTC UDP traffic.
To guarantee zero black screens in the control room, Sentinel includes a built-in
fallback relay in `model1-registry/app/routers/streams.py`:
- `CameraStreamReader` connects to the RTSP feed, decodes H.264/HEVC frames server-side,
  re-encodes them to JPEG, and serves a `multipart/x-mixed-replace` MJPEG stream.
- **Viewer-Aware Auto-Reaping**: Spawning decode threads for 30 cameras would exhaust
  server CPU. `CameraStreamReader` tracks active HTTP client connections and
  **automatically terminates the decode thread after 10 seconds of zero viewers**.
- **GOP Keyframe Drift Tolerance**: Remote surveillance feeds have Group of Pictures (GOP)
  keyframe intervals up to 10–12 seconds. `streams.py` tolerates up to 9 seconds of decode
  waits before forcing an RTSP reconnect, preventing connection thrashing during keyframe pauses.

---

### 4. Control-Room Grid UI (`/grid`)

Rendered via Jinja2 + HTMX + Alpine.js at `http://localhost:8000/grid`:
- **Configurable Matrix Layouts**: Switch dynamically between **2×2 (4 cameras)**,
  **3×3 (9 cameras)**, and **4×4 (16 cameras)** layouts, or inspect all 30 cameras
  in a scrollable control wall.
- **Zero-Reflow Performance**: Replacing per-frame `getBoundingClientRect()` calls with
  a cached `ResizeObserver` dimension map eliminated 50 forced layout reflows per second,
  maintaining smooth 60 FPS UI rendering even with 16 active video players.
- **Spotlight Modal**: Clicking any camera card opens an expanded high-resolution inspector
  displaying live telemetry (FPS, resolution, bitrate, codec, source ID), direct copy
  buttons for RTSP/WHEP/HLS endpoints, and quick links to the camera's GIS record.
- **Department & District Filtering**: Filter visible tiles on the fly to isolate police,
  transportation, or specific district camera clusters without page reloads.

---

### 5. API Reference — Grid & Ingestion (`grid.py` & `streams.py`)

Base path: `/api/v1`. All endpoints enforce authentication unless explicitly noted.

| Method & Path | Auth Required | Purpose |
|---|---|---|
| `GET /grid` | Viewer+ | Control-room multi-camera video wall HTML page |
| `GET /api/ingest` | None (Public) | Hackathon ingestion contract (all 30 camera profiles) |
| `GET /api/v1/grid/streams` | Viewer+ | List active streams with verified RTSP/WHEP/HLS URLs |
| `POST /api/v1/grid/sync` | Dept Admin | Trigger external catalogue polling and DB synchronization |
| `GET /api/v1/cameras/{id}/live` | Viewer+ | Serves authenticated server-side MJPEG stream by camera UUID |
| `GET /api/v1/cameras/grid/{grid_id}/live` | Viewer+ | Serves authenticated server-side MJPEG stream by grid ID (e.g. `cam04`) |
| `GET /api/v1/cameras/grid/{grid_id}/frame` | Viewer+ | Captures and serves single latest JPEG snapshot thumbnail |
| `GET /api/v1/streams/catalogue` | Viewer+ | Dynamic JSON catalogue of all active stream endpoints |

#### Query Parameters for `GET /api/v1/grid/streams`
- `department_id` (UUID, optional): Filter streams by owning department.
- `district_id` (UUID, optional): Filter streams by administrative district.
- `connectivity_status` (string, optional): Filter by connectivity (`online`, `offline`, `maintenance`).
- `is_live_only` (bool, default `false`): Restrict results to active live feeds only.
- `limit` (int, default `100`, max `500`): Maximum records to return.
- `offset` (int, default `0`): Pagination offset.

#### Example: Querying Active Streams (`GET /api/v1/grid/streams`)

Request:
```http
GET /api/v1/grid/streams?is_live_only=true&limit=1 HTTP/1.1
Host: localhost:8000
Authorization: Bearer <jwt_token>
```

Response (`200 OK`):
```json
[
  {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "name": "SG Highway Junction Cam 04",
    "department_name": "Home Department (Police)",
    "district_name": "Ahmedabad",
    "connectivity_status": "online",
    "is_active": true,
    "is_live": true,
    "source_grid_id": "cam04",
    "location_label": "SG Highway, Thaltej",
    "vms_url": null,
    "rtsp_url": "rtsp://103.250.160.189:8554/stream/cam04",
    "whep_url": "http://103.250.160.189:8889/stream/cam04/whep",
    "hls_url": "https://cctv.corp8.cloud/cam04/index.m3u8",
    "properties": {
      "codec": "H.264",
      "stream_width": 1920,
      "stream_height": 1080,
      "stream_fps": 25.0,
      "bitrate_kbps": 4096
    }
  }
]
```

#### Example: Triggering Catalogue Sync (`POST /api/v1/grid/sync`)

Request:
```http
POST /api/v1/grid/sync HTTP/1.1
Host: localhost:8000
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "catalogue_url": "http://103.250.160.189:8000/api/ingest"
}
```

Response (`200 OK`):
```json
{
  "synced_count": 30,
  "updated_count": 4,
  "status": "success",
  "message": "Synchronized 30 cameras from external catalogue"
}
```

---

## IV. Target Registry — Vehicle Watchlist Engine

The **Vehicle Watchlist Engine** (`app/routers/watchlist.py`) maintains the authoritative target registry queried synchronously by downstream inference workers during ANPR matching.

### 4.1 Plate Normalization & Validation Rules

To ensure reliable matching regardless of operator input formatting, plate strings are normalized via `re.sub(r"[\s\-\.]+", "", v.strip().upper())` and validated against standard Indian vehicle numbering formats:
* **Standard State Series**: `^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$` (e.g., `GJ01AB1234`, `DL4C1234`, `MH121433`)
* **Bharat (BH) Series**: `^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$` (e.g., `22BH1234AA`)

Deviating formats fail at the API boundary with `422 Unprocessable Entity`.

### 4.2 Operational Constraints & Lifecycle

* **Mandatory FIR/Incident Context**: The `description` field enforces `min_length=10, max_length=500` to guarantee investigative traceability.
* **Categories & Status**: `category` accepts `stolen`, `wanted`, or `blacklisted`; `status` transitions between `active` and `resolved`.
* **Duplicate Prevention**: Re-registering an already `active` plate returns `409 Conflict`.
* **Cascade Deletion**: Calling `DELETE /api/v1/watchlist/vehicles/{id}` purges linked records from `alerts` before removing the target row, preventing foreign-key violations.

### 4.3 API Surface

All mutating endpoints require `operator` or `dept_admin` role:

| Method | Path | Auth / Role | Query Parameters / Payload | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/watchlist/vehicles` | `operator`, `dept_admin` | `status`, `category`, `plate_number`, `department_id`, `limit` (max 500), `offset` | List watchlist entries ordered by `created_at` DESC. |
| `POST` | `/api/v1/watchlist/vehicles` | `operator`, `dept_admin` | `VehicleWatchlistCreate` payload | Register vehicle target (`201 Created`). Rejects duplicates with `409 Conflict`. |
| `GET` | `/api/v1/watchlist/vehicles/{id}` | `operator`, `dept_admin` | `id` (path, UUID) | Fetch single target record by UUID. |
| `PATCH` | `/api/v1/watchlist/vehicles/{id}` | `operator`, `dept_admin` | `id` (path, UUID), `VehicleWatchlistUpdate` | Partial update (e.g., setting `status="resolved"`). |
| `DELETE` | `/api/v1/watchlist/vehicles/{id}` | `operator`, `dept_admin` | `id` (path, UUID) | Delete target record and cascade-delete linked alerts (`204 No Content`). |

#### Example: Register Target (`POST /api/v1/watchlist/vehicles`)

```http
POST /api/v1/watchlist/vehicles HTTP/1.1
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "plate_number": "GJ01AB1234",
  "category": "stolen",
  "reported_date": "2026-09-14",
  "department_id": "8f3b2089-9a74-4b53-a5c6-b37996f018e4",
  "description": "White Hyundai Creta reported stolen under FIR 412/26 at Vastrapur PS.",
  "status": "active"
}
```

Response (`201 Created`):
```json
{
  "id": "e2a18456-78bc-4f71-a0c3-f09852026ab1",
  "plate_number": "GJ01AB1234",
  "category": "stolen",
  "reported_date": "2026-09-14",
  "department_id": "8f3b2089-9a74-4b53-a5c6-b37996f018e4",
  "department_name": "Home Department (Police)",
  "description": "White Hyundai Creta reported stolen under FIR 412/26 at Vastrapur PS.",
  "status": "active",
  "created_at": "2026-09-14T20:45:00Z"
}
```

---

## V. AI Vehicle Detection, In-Frame Tracking & Native ANPR Pipeline

The analytics engine converts unstructured RTSP streams and forensic video files into structured, queryable vehicular intelligence. Rather than relying on heavyweight centralized video recording, Model 2 extracts telemetry at the edge of ingestion, persisting only selective metadata rows.

### 5.1 Dual Ingestion Architecture

Surveillance workflows require handling both real-time operational feeds and forensic post-incident footage:

1. **Live RTSP Stream Pipeline (`MultiStreamPipelineRunner`)**:
   Runs in an on-demand lifecycle (`app/routers/detections.py`). Camera workers do not run continuously in the background eating server GPU cycles; instead, they spin up when an operator opens `/detection` and connects to `/ws/detections`. When the last client disconnects, workers gracefully stop, terminating thread execution and halting database writes.
2. **Forensic Video Ingestion (`PreRecordedVideoWorker`)**:
   Investigators routinely receive exported CCTV clips from external systems (e.g., USB drives, private store VMS). The upload endpoint (`POST /api/v1/recorded/upload`) accepts video containers up to 2 GB (`.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`). It executes an OpenCV probe (`cv2.VideoCapture`) to extract native FPS, frame counts, and dimensions, then spawns an isolated daemon thread. Operators control analysis via `1x`, `2x`, or `max` speed throttles with real-time pause, resume, and stop controls.

### 5.2 The 3-Stage Visual Pipeline

Every ingested frame passes through three tightly coupled in-memory stages:

* **Stage 1 — YOLOv8 Indian Traffic Inference (`VehicleDetector`)**:
  Standard COCO models fail on Indian roads due to atypical vehicle distributions. Model 2 defaults to `indian_traffic_yolov8.pt` (auto-downloaded from HuggingFace, with fallback to `yolov8n.pt`), fine-tuned to classify 7 Indian traffic categories: `Auto-Rickshaw` (CNG/Tuk-Tuk), `Motorcycle/Scooter`, `Car`, `Bus`, `Truck`, `Mini-Truck`, and `Bicycle`.
* **Stage 2 — In-Frame Centroid & IoU Tracking (`InFrameTracker`)**:
  Raw frame-by-frame detections produce flickering and redundant alerts. `InFrameTracker` assigns persistent track IDs across frames using spatial centroid proximity combined with Intersection over Union (`iou_threshold=0.25`). Trajectory coordinates use Exponential Moving Average (EMA) bounding-box smoothing and require at least 2 consecutive confirmed frames (`min_confirmed_frames=2`) before promoting a detection to a confirmed track.
* **Stage 3 — Native Integrated ANPR**:
  ANPR is not a separate microservice; it is embedded directly in the detection loop. Bounding-box crops of detected vehicles are routed to the OCR engine (`pipeline/plate/` and `pipeline/ocr/`). Recognized character sequences are normalized, validated against Indian plate regexes, and linked directly to the parent vehicle track ID.

### 5.3 Selective Metadata Persistence

In compliance with edge analytics standards, Model 2 discards raw video frames immediately after inference. Only structured analytical metadata is written to PostgreSQL via `DetectionWriter`:
* Timestamp and camera UUID.
* Normalized license plate string and OCR confidence score.
* Classified vehicle type and unique `vehicle_track_id`.
* Cropped plate image thumbnail (stored in `/uploads/crops/` for forensic verification).

Zero centralized raw video is retained, eliminating massive SAN/NAS storage overheads.

### 5.4 Detection & ANPR API Surface

| Method | Path | Auth / Role | Parameters / Body | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/detection/events` | any user | None | Returns the 20 most recent confirmed vehicle sightings (in-memory ring buffer with DB fallback). |
| `GET` | `/api/v1/detections` | any user | `camera_tag` (opt), `page` (default: 1), `page_size` (default: 20, max: 100) | Paginated database history of vehicle detections with plate crops and track IDs. |
| `GET` | `/api/v1/detections/stats` | any user | None | Real-time counts: `total_today`, `total_all_time`, and active track counts per camera. |
| `POST` | `/api/v1/detections/start` | `operator`, `dept_admin` | None | Manually forces live pipeline runner workers to start. |
| `POST` | `/api/v1/detections/stop` | `operator`, `dept_admin` | None | Manually halts live pipeline runner workers. |
| `WS` | `/ws/detections` | authenticated JWT | `token` query param / cookie | Real-time WebSocket pushing new detection events; automatically manages worker lifecycle. |
| `GET` | `/api/v1/anpr/health` | public | None | Health check verifying that integrated ANPR is active inside the detection pipeline. |
| `GET` | `/api/v1/recorded/cameras` | any user | None | List active cameras to associate uploaded forensic video with a physical location. |
| `POST` | `/api/v1/recorded/upload` | `operator`, `dept_admin` | Multipart file (up to 2 GB), `camera_id` (opt), `speed` (`1x`/`2x`/`max`) | Upload forensic video; probes metadata with OpenCV and initializes processing job. |
| `POST` | `/api/v1/recorded/start` | `operator`, `dept_admin` | `job_id` (JSON) | Starts pre-recorded video analysis thread. |
| `POST` | `/api/v1/recorded/pause` | `operator`, `dept_admin` | `job_id` (JSON) | Pauses video worker thread execution. |
| `POST` | `/api/v1/recorded/resume` | `operator`, `dept_admin` | `job_id` (JSON) | Resumes paused video worker thread. |
| `POST` | `/api/v1/recorded/stop` | `operator`, `dept_admin` | `job_id` (JSON) | Terminates video worker thread. |
| `GET` | `/api/v1/recorded/status/{job_id}` | any user | `job_id` (path) | Returns job progress percentage, frame index, detections count, and status. |
| `WS` | `/ws/recorded/{job_id}` | public / token | `job_id` (path) | WebSocket streaming processed frames (JPEG base64), bounding boxes, and plate sightings. |

#### Example: Paginated Detection History (`GET /api/v1/detections?page=1&page_size=2`)

```http
GET /api/v1/detections?page=1&page_size=2 HTTP/1.1
Authorization: Bearer <jwt_token>
```

Response (`200 OK`):
```json
{
  "status": "ok",
  "total": 142,
  "page": 1,
  "page_size": 2,
  "pages": 71,
  "detections": [
    {
      "id": "7a8b9c0d-1234-5678-90ab-cdef01234567",
      "camera_tag": "cam04",
      "timestamp": "2026-09-14 21:15:32",
      "detected_plate": "GJ01AB1234",
      "confidence": 92.4,
      "crop_path": "/uploads/crops/crop_7a8b9c0d.jpg",
      "camera_name": "SG Highway Junction Cam 04",
      "location_label": "SG Highway, Thaltej",
      "vehicle_type": "Car",
      "vehicle_track_id": "trk-04-00892"
    },
    {
      "id": "1b2c3d4e-5678-90ab-cdef-1234567890ab",
      "camera_tag": "cam04",
      "timestamp": "2026-09-14 21:15:28",
      "detected_plate": "GJ01EF5678",
      "confidence": 88.7,
      "crop_path": "/uploads/crops/crop_1b2c3d4e.jpg",
      "camera_name": "SG Highway Junction Cam 04",
      "location_label": "SG Highway, Thaltej",
      "vehicle_type": "Auto Rickshaw",
      "vehicle_track_id": "trk-04-00891"
    }
  ]
}
```

#### Example: Forensic Video Upload (`POST /api/v1/recorded/upload`)

Request:
```http
POST /api/v1/recorded/upload HTTP/1.1
Authorization: Bearer <jwt_token>
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW

------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="file"; filename="traffic_clip_01.mp4"
Content-Type: video/mp4

[binary video data]
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="speed"

2x
------WebKitFormBoundary7MA4YWxkTrZu0gW--
```

```json
{
  "status": "ok",
  "job_id": "rec-f47ac10b",
  "filename": "traffic_clip_01.mp4",
  "metadata": {
    "total_frames": 1800,
    "fps": 30.0,
    "duration_seconds": 60.0,
    "width": 1920,
    "height": 1080,
    "speed": "2x"
  },
  "ws_url": "/ws/recorded/rec-f47ac10b",
  "message": "Video uploaded and probed successfully. Ready to start."
}
```

---

## VI. Real-Time Alerting & Sighting Correlation Engine

Detection telemetry is purely observational until correlated against active security interests. The **Alerting Engine** (`app/routers/alerts.py`) bridges raw vehicle plate readings and the target registry, turning transient detections into auditable security incidents.

### 6.1 Sighting Correlation & Severity Matrix

Whenever the ANPR module confirms a normalized plate number, the pipeline executes a synchronous query against the `vehicles_watchlist` table:

```sql
SELECT id, category, plate_number 
FROM vehicles_watchlist 
WHERE plate_number = :plate_str AND status = 'active'
LIMIT 1;
```

If a target record is matched, the engine generates an incident row in `alerts`, linking the detection record, watchlist ID, camera metadata, and timestamp. The alert severity is dynamically derived from the target's investigative category:

| Target Category | Alert Severity | Operational Response Trigger |
|---|---|---|
| `stolen` | `critical` | Red-banner visual alert on operator console; immediate dispatch notification to nearest patrol unit. |
| `wanted` | `high` | Amber flashing indicator on active video feed; logged to prioritized incident queue. |
| `blacklisted` | `medium` | Automated gate/barrier hold or perimeter entry denial flag. |

### 6.2 Instant Broadcast & Acknowledgment Lifecycle

To prevent alert fatigue while ensuring critical incidents are not missed:
1. **WebSocket Dispatch**: The event is pushed immediately across the `/ws/detections` broadcast hub with type `"NEW_ALERT"`, updating the control room dashboard in under 50 milliseconds.
2. **Operator Acknowledgment**: Alerts remain in an `unacknowledged` state (`acknowledged_by IS NULL`) until an operator takes action. Calling `PATCH /api/v1/alerts/{alert_id}/ack` stamps the record with `acknowledged_at = now()` and records the operator's identifier. The endpoint is idempotent, preventing concurrency races when multiple control-room desks view the same incident feed.

### 6.3 Alerts API Surface

| Method | Path | Auth / Role | Query Parameters / Payload | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/alerts` | any user | `severity` (opt), `alert_type` (opt), `acknowledged` (opt, bool), `limit` (max 200), `offset` | List incident alerts ordered by creation time descending with joined camera and plate metadata. |
| `GET` | `/api/v1/alerts/stats` | any user | None | Aggregated counts: `total`, `today`, `unacked`, and unacknowledged counts grouped by severity level. |
| `PATCH` | `/api/v1/alerts/{id}/ack` | any user | `id` (path, UUID) | Acknowledges an active alert, stamping `acknowledged_at` and operator UUID (`200 OK`). |

#### Example: Alert Acknowledgment (`PATCH /api/v1/alerts/{id}/ack`)

```http
PATCH /api/v1/alerts/9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d/ack HTTP/1.1
Authorization: Bearer <jwt_token>
```

Response (`200 OK`):
```json
{
  "status": "ok",
  "alert_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "acknowledged": true
}
```

---

## VII. Biometric Watchlist — Person Registry & 5-Gate AI Quality Pipeline

While vehicular tracking handles roadway corridors, perimeter and facility security requires identifying individuals of interest. The **Person Watchlist Engine** (`app/routers/persons_watchlist.py`) operates as a decoupled biometric target registry for wanted criminals, missing persons, and investigative suspects.

### 7.1 The 5-Gate AI Quality Pipeline

Low-quality reference portraits produce unreliable vector embeddings, degrading vector similarity search and causing false positives. When an operator registers an individual via `POST /api/v1/watchlist/persons`, the image must pass five automated validation gates (`FaceQualityChecker`) before any embedding is calculated:

1. **Integrity & Count Gate**: Detects face bounding boxes using MTCNN. Rejects images with zero faces (unusable) or multiple faces (group photos where target identity is ambiguous).
2. **Anti-Clipping Boundary Gate**: Ensures the detected face bounding box does not touch the edge of the image frame, preventing truncated forehead, chin, or cheek features.
3. **Sharpness & Defocus Blur Gate**: Computes the Laplacian variance across the cropped face. Blurry or motion-degraded photos below the sharpness threshold are rejected.
4. **3D Head Pose Filtering**: Evaluates yaw, pitch, and roll angles. Extreme side-profiles (beyond $\pm 35^\circ$ yaw) are rejected to ensure fronto-lateral alignment.
5. **Illumination & Dynamic Range Gate**: Assesses mean pixel intensity and histogram spread to prevent severe overexposure or underexposure.

If any gate fails, the API immediately returns `422 Unprocessable Entity` accompanied by the exact diagnostic failure reason and computed metrics, preventing corrupt biometric anchors from entering the vector database.

### 7.2 InceptionResnetV1 Embedding & pgvector Persistence

Once validated, the face crop is aligned and passed to `FaceEmbeddingEngine` (`InceptionResnetV1`), which extracts a unit-normalized **512-dimensional vector embedding**:

$$\|\mathbf{v}\|_2 = \sqrt{\sum_{i=1}^{512} v_i^2} = 1.0$$

The resulting vector is committed to the `persons_watchlist` table in PostgreSQL using `pgvector` with an HNSW cosine-distance index:

```sql
CREATE INDEX idx_persons_watchlist_embedding
ON persons_watchlist USING hnsw (face_embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

### 7.3 Person Watchlist API Surface

All mutating endpoints require an authenticated JWT bearing either the `operator` or `dept_admin` role:

| Method | Path | Auth / Role | Parameters / Body | Description |
|---|---|---|---|---|
| `POST` | `/api/v1/watchlist/persons` | `operator`, `dept_admin` | Multipart: `name`, `category` (`wanted`/`missing`/`suspect`), `status` (`active`/`resolved`), `photo` (JPEG/PNG up to 10 MB) | Runs 5-gate quality check, generates 512-d embedding, and registers person (`201 Created`). |
| `GET` | `/api/v1/watchlist/persons` | any user | `category` (opt), `status` (opt), `search` (opt, name prefix), `limit`, `offset` | List registered persons with category, status, and embedding status. |
| `GET` | `/api/v1/watchlist/persons/{id}` | any user | `id` (path, UUID) | Fetch single person profile including cropped reference portrait path and quality metrics. |
| `PATCH` | `/api/v1/watchlist/persons/{id}` | `operator`, `dept_admin` | `id` (path, UUID), `PersonWatchlistUpdate` | Update person details or toggle status (`active` $\rightarrow$ `resolved`). |
| `DELETE` | `/api/v1/watchlist/persons/{id}` | `operator`, `dept_admin` | `id` (path, UUID) | Permanently deletes person record and removes reference portrait from disk (`204 No Content`). |

#### Example: Registering a Wanted Suspect (`POST /api/v1/watchlist/persons`)

Request:
```http
POST /api/v1/watchlist/persons HTTP/1.1
Authorization: Bearer <jwt_token>
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW

------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="name"

Vikram Singh
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="category"

wanted
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="status"

active
------WebKitFormBoundary7MA4YWxkTrZu0gW
Content-Disposition: form-data; name="photo"; filename="suspect_portrait.jpg"
Content-Type: image/jpeg

[binary image bytes]
------WebKitFormBoundary7MA4YWxkTrZu0gW--
```

Response (`201 Created`):
```json
{
  "id": "c3f2e1a0-5b6c-4d7e-8f90-1a2b3c4d5e6f",
  "name": "Vikram Singh",
  "category": "wanted",
  "status": "active",
  "photo_path": "/uploads/persons/c3f2e1a0_portrait.jpg",
  "has_embedding": true,
  "embedding_dim": 512,
  "created_at": "2026-09-14T22:10:15Z",
  "quality_metrics": {
    "faces_detected": 1,
    "sharpness_score": 248.5,
    "yaw_angle": -4.2,
    "pitch_angle": 2.1,
    "passed": true
  }
}
```

---

## VIII. Surveillance Video Face Detection, Matching & Live Alerting

The biometric surveillance pipeline (`app/routers/face_detection.py` and `pipeline/face_detection/worker.py`) extends facial recognition to surveillance footage. It performs continuous face extraction on video streams, matches detected faces against the 512-d target registry in PostgreSQL, and generates instant match alerts.

### 8.1 Two-Layer Visual Matching Pipeline

```
Video Frame ──> [Layer 1: MTCNN Detection] ──> Face Crop ──> [Layer 2: InceptionResnetV1] ──> 512-d Vector
                                                                                                    │
                                                                                                    ▼
                                                      [pgvector Cosine Search]: distance <= 0.30 ───┘
                                                                │
                                                                ├── MATCH FOUND ──> Generate PersonAlert + WS Broadcast
                                                                └── NO MATCH    ──> Discard vector (Zero archival)
```

1. **Layer 1 — Spatial Face Localization**:
   Each frame is scanned for human faces using MTCNN. False detections and microscopic crops are discarded by enforcing a minimum bounding box threshold ($40 \times 40$ pixels).
2. **Layer 2 — Cosine Vector Search (`pgvector`)**:
   Detected faces are transformed into unit-normalized 512-d feature vectors and matched against the active `persons_watchlist` using the cosine distance operator (`<=>`):
   ```sql
   SELECT id, name, category, photo_path,
          (face_embedding <=> :probe_vector) AS distance
   FROM persons_watchlist
   WHERE status = 'active'
     AND (face_embedding <=> :probe_vector) <= 0.30
   ORDER BY distance ASC
   LIMIT 1;
   ```
   A cosine distance threshold of $\le 0.30$ guarantees a minimum **70% cosine similarity** ($\text{similarity} = 1.0 - \text{distance} \ge 0.70$), eliminating false positive alerts in crowded scenes.

### 8.2 Live Forensic Streaming & UI Controls (`/face-detection`)

The dedicated `/face-detection` web interface gives operators full tactical control over video processing:
* **Asynchronous Execution**: `FaceVideoWorker` runs on a dedicated background thread, decoupled from the FastAPI async event loop to ensure zero UI freezing.
* **Playback Throttles**: Operators can dynamically process footage at `1x`, `2x`, or `max` speed, with instant `pause`, `resume`, and `stop` controls.
* **Live WebSocket Telemetry (`/ws/{job_id}`)**: Streams real-time base64-encoded JPEG frames overlaid with bounding boxes (green for general faces, bright red with name badge for confirmed watchlist matches).
* **Path-Traversal Protected Crops**: Face match crops are stored with randomized UUID filenames and served through `GET /api/v1/face-detection/crops/{filename}`, enforcing strict `is_relative_to` path containment to prevent directory traversal attacks.

### 8.3 Face Detection API Surface

| Method | Path | Auth / Role | Parameters / Body | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/face-detection/cameras` | any user | None | Lists active cameras for physical location association. |
| `POST` | `/api/v1/face-detection/upload` | `operator`, `dept_admin` | Multipart video file (up to 2 GB), `camera_id` (opt) | Uploads footage, probes video metadata with OpenCV, and initializes processing job. |
| `POST` | `/api/v1/face-detection/start` | `operator`, `dept_admin` | `JobControlRequest` (`job_id`, `speed`) | Launches background face worker thread. |
| `POST` | `/api/v1/face-detection/pause` | `operator`, `dept_admin` | `JobControlRequest` (`job_id`) | Pauses active video worker thread. |
| `POST` | `/api/v1/face-detection/resume` | `operator`, `dept_admin` | `JobControlRequest` (`job_id`) | Resumes paused video worker thread. |
| `POST` | `/api/v1/face-detection/stop` | `operator`, `dept_admin` | `JobControlRequest` (`job_id`) | Stops and terminates video worker thread. |
| `GET` | `/api/v1/face-detection/status/{job_id}` | any user | `job_id` (path) | Returns frame index, progress %, processing FPS, faces detected, and total matches. |
| `GET` | `/api/v1/face-detection/alerts` | any user | `limit` (default: 25), `offset` | Paginated list of confirmed person alerts with match distance and thumbnail crop paths. |
| `GET` | `/api/v1/face-detection/crops/{filename}`| any user | `filename` (path) | Serves face match image crops with strict path-traversal validation. |
| `WS` | `/api/v1/face-detection/ws/{job_id}` | public / token | `job_id` (path) | WebSocket streaming annotated video frames, progress updates, and match alerts. |

---

## IX. Operational Boundaries — What Model 2 Deliberately Does NOT Do

To maintain architectural purity and rock-solid reliability in high-throughput surveillance environments, Model 2 draws five strict operational boundaries:

### 1. Zero Centralized Raw Video Archival (No SAN/NAS Bloat)
Model 2 is an **edge analytics and telemetry extraction engine**, not an NVR or long-term video repository. Ingested video frames are evaluated in volatile memory and discarded immediately after inference. The database retains only structured telemetry rows (`timestamp`, `detected_plate`, `confidence`, `vehicle_type`, `vehicle_track_id`) and small, highly compressed thumbnail crops. Centralizing petabytes of raw video from hundreds of departmental cameras is explicitly out of scope.

### 2. Direct Connection Independence — Zero Dependency on Model 3
Model 2's live video ingestion (`RTSPAdapter`, `IngestionSupervisor`, `MultiStreamPipelineRunner`, `/grid` streaming wall) connects **DIRECTLY** to department VMS edge endpoints via standard RTSP over TCP. 

> [!IMPORTANT]
> **Architectural Independence Notice**: Model 2 does **NOT** route video feeds through Model 3, nor does it require Model 3 to be online to ingest, display, or run AI inference on live camera feeds. Model 3 is a specialized federation and vendor onboarding subsystem designed for remote camera discovery and vendor SDK protocol bridging. Model 2's direct streaming and analytics pipeline operates completely self-contained with zero intermediate middleware in its hot path. If Model 3 is offline, under maintenance, or undergoing schema upgrades, Model 2's control room grid wall, vehicle detection, ANPR, and alerting pipelines continue streaming without interruption.

### 3. No Multi-Camera Cross-Tracking (Re-ID) in Model 2
Model 2's `InFrameTracker` tracks vehicles and persons strictly within the field of view of a single camera (`camera_id`). It does not compute multi-camera spatio-temporal Re-Identification (Re-ID) trajectories across different geographical junctions. Cross-camera movement synthesis and departmental federation queries belong to downstream analytical consumers querying Model 2's published `detections` and `alerts` tables.

### 4. No Direct Camera Firmware or PTZ Motor Control
Model 2 reads camera connectivity attributes from the shared schema and external catalog endpoints (`/api/ingest`), but never sends actuator commands (Pan/Tilt/Zoom motor movement, lens focus adjustments, or firmware upgrades) back to physical camera hardware. It functions strictly as an analytical observer and stream consumer, ensuring that existing departmental CCTV infrastructure remains entirely undisturbed.

### 5. No Indiscriminate Face Storage (Privacy Preservation)
Unlike unconstrained surveillance systems that archive every passing pedestrian, Model 2 does **NOT** store embeddings or photographs of non-matching faces. If a detected face does not match an active target in `persons_watchlist` ($\text{distance} \le 0.30$), the vector embedding and temporary crop are instantly purged from memory. Only confirmed, actionable matches against authorized law enforcement watchlists generate persistent audit records in `person_alerts`.




