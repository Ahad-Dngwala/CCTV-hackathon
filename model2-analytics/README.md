# Model 2 — Unified Viewing & Analytics (ANPR + Watchlist)

Full specification: `Project_Context.md` §4. Model 2 handles vehicle re-identification, license plate recognition (ANPR), cross-camera tracking, watchlist correlation, live CCTV stream viewing, and real-time alert generation.

---

## 🚀 Implemented Features

### Vehicle Watchlist System (API & Web UI)
- **Web Dashboard**: Interactive management portal at `http://localhost:8000/watchlist`.
- **Validation**: Strict Indian license plate normalization & regex verification (Standard State e.g. `GJ01AB1234` and Bharat Series `22BH1234AA`), plus mandatory 10+ char incident descriptions.
- **REST Endpoints** (`app/routers/watchlist.py`):
  - `GET /api/v1/watchlist/vehicles` — Search and filter by plate, category (`stolen`, `wanted`, `blacklisted`), status (`active`, `resolved`), and department.
  - `POST /api/v1/watchlist/vehicles` — Add new vehicle target with duplicate protection.
  - `GET /api/v1/watchlist/vehicles/{id}` — Fetch specific watchlist record.
  - `PATCH /api/v1/watchlist/vehicles/{id}` — Update target status (e.g. resolve case) or notes.
  - `DELETE /api/v1/watchlist/vehicles/{id}` — Remove target and cascade associated alerts.

---

## 🗄️ Database Tables (`shared/db/`)

- `vehicles_watchlist`: Target plates with category tagging (`stolen`, `wanted`, `blacklisted`) and status.
- `persons_watchlist`: Face recognition watchlist with `VECTOR(512)` embedding support.
- `vehicle_tracks`: Cross-camera global vehicle identities with appearance embeddings.
- `detections`: Individual sightings with camera timestamp, confidence, and cropped image reference.
- `alerts`: Real-time alerts generated on watchlist match with severity grading (`low`, `medium`, `high`, `critical`).

---

## 📂 Directory Structure

```
model2-analytics/
├── app/
│   └── routers/
│       └── watchlist.py        # Vehicle Watchlist REST API endpoints
└── pipeline/
    ├── detection/              # Live stream ingestion & YOLO vehicle detector
    ├── plate/                  # Number plate localizer (Step 2)
    ├── ocr/                    # PaddleOCR / EasyOCR plate text engine (Step 3)
    └── tracking/               # ByteTrack & cross-camera trajectory engine (Step 4)
```

---

## 🔜 Next Steps

1. **Plate Localizer & OCR Pipeline** (`pipeline/plate/` & `pipeline/ocr/`): Crop plates from vehicle bounding boxes and extract alphanumeric text.
2. **Real-Time Watchlist Correlator**: Match OCR outputs against `vehicles_watchlist` and push alerts.
3. **Vehicle Movement Route Tracer** (`/tracking`): Query `detections` to reconstruct timestamped travel trajectories across cameras.
