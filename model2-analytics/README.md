# Model 2 — Live Multi-Camera Grid & Vehicle Analytics

Model 2 handles live CCTV stream viewing (30-camera control-room grid), vehicle detection, license plate recognition (ANPR), cross-camera tracking, watchlist correlation, and real-time alert generation.

Full specification: `Project_Context.md` §4 and `HackathonPortal.md`.

---

## 🚀 Implemented Features

### 1. Live Multi-Camera Grid (Control Room Video Wall)

- **Web UI**: Control-room style video wall at `http://localhost:8000/grid`
- **Matrix Views**: Switch between 2×2, 3×3, and 4×4 camera tile layouts
- **Hover Overlay**: Per-camera details (location, codec, FPS, bitrate) on hover
- **Spotlight Modal**: Click any tile to open full-screen player with copyable RTSP/WHEP/HLS URLs
- **Filters**: Filter camera tiles by department or district
- **REST Endpoints** (`app/routers/grid.py`):
  - `GET /grid` — Serves the live video wall HTML page
  - `GET /api/ingest` — **Hackathon ingestion contract**: returns all 30 cameras with stream properties and RTSP/WHEP/HLS URLs
  - `GET /api/v1/grid/streams` — JSON: active camera list with stream URLs (used by grid UI JavaScript)
  - `POST /api/v1/grid/sync` — Sync external catalogue entries into the local DB

### 2. Vehicle Watchlist System (API & Web UI)

- **Web Dashboard**: Interactive portal at `http://localhost:8000/watchlist`
- **Validation**: Strict Indian license plate normalization & regex (`GJ01AB1234`, `22BH1234AA` BH-series)
- **REST Endpoints** (`app/routers/watchlist.py`):
  - `GET /api/v1/watchlist/vehicles` — Search by plate, category, status, department
  - `POST /api/v1/watchlist/vehicles` — Add target with duplicate protection
  - `GET /api/v1/watchlist/vehicles/{id}` — Fetch watchlist record
  - `PATCH /api/v1/watchlist/vehicles/{id}` — Update status or notes
  - `DELETE /api/v1/watchlist/vehicles/{id}` — Remove target and cascade alerts

---

## 📡 Live Stream Architecture

All 30 camera feeds are provided by the hackathon media gateway. Stream URLs come **dynamically from `/api/ingest`** — never hard-coded.

```
Browser opens /grid
      ↓
JavaScript: fetch('/api/v1/grid/streams')
      ↓
30 camera RTSP/WHEP/HLS URLs from DB
      ↓
<video> per tile → HLS.js attaches HLS stream URL
      ↓
Browser connects DIRECTLY to hackathon gateway:
  http://live.corp8.cloud:8889/stream/<id>/whep   (WebRTC WHEP)
  http://live.corp8.cloud/live/stream/<id>/index.m3u8  (HLS)
```

| Protocol | Endpoint Pattern | Used By |
|----------|-----------------|---------|
| RTSP | `rtsp://live.corp8.cloud:8554/stream/<id>` | AI pipeline (OpenCV) |
| WebRTC WHEP | `http://live.corp8.cloud:8889/stream/<id>/whep` | Browser live preview |
| HLS | `http://live.corp8.cloud/live/stream/<id>/index.m3u8` | Grid video player (HLS.js) |

> **Note**: `live.corp8.cloud` is the hackathon evaluation gateway. One problem that it is not accessible right now using the home wifi network maybe it can be accessible by the jury network at the event jus a guess please check this first 
---

## RTSP Ingestion Client (`pipeline/ingest.py`)

Used by the **AI inference pipeline** (not browser). Connects to RTSP feeds, reads frames, yields `(frame, pts_ms)` for YOLO detection.

**Hackathon Portal Compliance:**
| Rule | Implementation |
|------|---------------|
| Force RTSP TCP | `os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"` |
| PTS-driven timing only | `pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)` — no wall clock, no FPS |
| Exponential backoff reconnect | Start 2s → doubles → capped at 30s |
| Scene discontinuity recovery | PTS reset detection without crashing tracker state |
| Decoder warnings tolerated | Mid-stream IDR waits logged, not fatal |
| Dynamic catalogue | `fetch_ingest_catalogue()` reads `/api/ingest` — no hardcoded camera IDs |

**Usage (for YOLO pipeline):**
```python
from pipeline.ingest import StreamIngestClient

client = StreamIngestClient(
    camera_id="12",
    rtsp_url="rtsp://live.corp8.cloud:8554/stream/12"
)

for frame, pts_ms in client.read_frames():
    # frame  → numpy BGR image (OpenCV format)
    # pts_ms → camera presentation timestamp in milliseconds
    detections = yolo_detector.detect(frame, pts_ms)
    matched_plates = watchlist_correlator.check(detections)
```

---

## 🗄️ Database Tables (`shared/db/`)

| Table | Purpose |
|-------|---------|
| `cameras` | Camera registry with RTSP/WHEP/HLS URLs, codec, resolution, FPS |
| `vehicles_watchlist` | Target plates with category and status |
| `vehicle_tracks` | Cross-camera global vehicle identities |
| `detections` | Individual sightings with camera timestamp and confidence |
| `alerts` | Real-time alerts on watchlist match with severity grading |

---

## 📂 Directory Structure

```
model2-analytics/
├── app/
│   └── routers/
│       ├── grid.py             # Live Grid API: /grid, /api/ingest, /api/v1/grid/streams
│       └── watchlist.py        # Vehicle Watchlist REST API
└── pipeline/
    ├── ingest.py               # RTSP StreamIngestClient — frame reader for AI pipeline
    ├── detection/              # YOLOv8 vehicle detector (WIP)
    ├── plate/                  # Plate localizer (WIP)
    ├── ocr/                    # PaddleOCR / EasyOCR engine (WIP)
    └── tracking/               # ByteTrack & cross-camera trajectory (WIP)
```

---

## 🔜 Next Steps (AI Pipeline)

1. **YOLOv8 Vehicle Detector** (`pipeline/detection/yolo_detector.py`): Detect cars, trucks, bikes from RTSP frames
2. **Plate Localizer** (`pipeline/plate/`): Crop plate regions from vehicle bounding boxes
3. **OCR Engine** (`pipeline/ocr/`): Extract plate text using PaddleOCR or EasyOCR
4. **Real-Time Watchlist Correlator**: Match OCR output → push alert via WebSocket (`/ws/alerts`)
5. **Vehicle Movement Trajectory** (`/tracking`): Reconstruct cross-camera travel paths

