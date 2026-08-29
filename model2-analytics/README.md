# Model 2 — Unified Viewing & Analytics (ANPR + Watchlist)

Full spec: `Project_Context.md` §4. This is the model that Step 4's
scored test actually exercises — trace a designated vehicle by plate
across the network with timestamped movement history, and demonstrate
live watchlist cross-referencing with real-time alerts. Everything here
should be checked against that test, not just the feature checklist.

## Pipeline (in order)

1. **Vehicle detection** — localize vehicles in-frame; feeds both plate
   detection and cross-camera tracking.
2. **Plate detection** — localize plate region within the vehicle crop.
   YOLO-family, fine-tuned on Indian plate proportions/fonts — generic
   pretrained detectors underperform here (usually trained on US/EU
   plates).
3. **OCR** — PaddleOCR / EasyOCR / small CRNN. Separate failure mode
   from detection: finding the plate ≠ reading it right, eval these
   separately (see below).
4. **Cross-camera tracking / route reconstruction** — this *is* the
   scored test. Primary: join detections into a track by plate string +
   timestamp. Fallback when OCR fails at one camera: appearance-based
   re-id (color, vehicle type, rough embedding) so one bad read doesn't
   break the route.
5. **Bonus / stretch, not core path**: face recognition vs.
   person-watchlist, generic anomaly detection. Cut unless everything
   above is done with days to spare (`Project_Context.md` §8).

## Directory layout

```
model2-analytics/
├── app/
│   └── routers/     FastAPI routers — detections, vehicle-tracks,
│                    watchlist, alerts, ws/alerts
└── pipeline/
    ├── detection/   Vehicle detection stage
    ├── plate/       Plate localization stage
    ├── ocr/         Plate OCR stage
    └── tracking/    Cross-camera track stitching
```

## Endpoints

See `docs/API_Contract.md` §2 — authoritative list, including the
`/ws/alerts` WebSocket contract. Update it in the same PR if you change
a shape here.

## Data model

`vehicles_watchlist`, `detections`, `alerts`, `vehicle_tracks` — defined
in `shared/db/`, sketch in `Project_Context.md` §4. `persons_watchlist`
is bonus scope, likely cut.

## Evaluation discipline — read this before building any stage

Every stage reports **precision, recall, F1 — never bare accuracy.**
This is deliberate, not pedantic (`Project_Context.md` §5): watchlist
hits are rare events, so "always say no match" scores misleadingly high
on accuracy while being useless.

- Plate detection: precision/recall/F1 on IoU-thresholded boxes.
- OCR: character-level accuracy *and* full-plate exact-match rate,
  reported separately — a 90% character-correct read is a 0% useful
  match.
- Watchlist alerting (the headline number): precision/recall/F1 on
  generated alerts. False positives flood the operator; false negatives
  miss the wanted vehicle.
- Cross-camera tracking: track-continuity precision/recall.

Test set: hand-labeled from our own recorded feed — see
`docs/DATASET.md` (not yet decided, needs an owner).

## Connecting to camera streams

The camera grid is **live-only** — RTP/RTSP, no seeking, no byte-range
fetching, no downloadable copies. Treat every endpoint like a physical
camera. Full detail in the resource doc; the constraints that actually
bite if ignored:

- **Force RTSP over TCP** in every client
  (`rtsp_transport;tcp` / `protocols=tcp` / `select-rtp-protocol=4`).
  UDP fails across NAT/firewalls and produces corrupt frames that look
  like model bugs.
- **Read the camera list from `GET /api/ingest`**, never hard-code
  URLs — ids and the available set can change. This is the grid's own
  catalogue endpoint, unrelated to our `docs/API_Contract.md`.
- **Drive all timing from PTS**, never wall-clock arrival time
  (`CAP_PROP_POS_MSEC` in OpenCV, buffer PTS in GStreamer). On connect,
  the gateway replays a buffered GOP so the decoder can start at a
  keyframe — the first second or two arrives faster than real time, and
  arrival-time-based tracking will compute impossible velocities.
- **Don't trust reported frame rate** (`CAP_PROP_FPS` is often wrong) —
  measure the real delivery rate or work off PTS deltas.
- **Reconnect with exponential backoff** (~2s → cap ~30s), never a
  tight loop. Feeds are supervised and restart.
- **Don't treat join-time decoder warnings as fatal** — normal until
  the first IDR frame arrives, self-corrects.
- **Expect a scene discontinuity at loop points** — each feed is a
  looping recording; long-lived state (background models, re-id
  galleries, track ids) should recover from a hard cut, not assume
  infinite continuity.
- **No downloading footage** — `/stream/<id>` is a browser-playback
  fallback that answers range requests; pulling it with `curl`/`wget`
  yields a partial file that *looks* complete but isn't. Build against
  a live capture from the start.
- Mixed grid: H.264 and H.265, mixed resolutions — read per-camera
  properties from `/api/ingest` rather than assuming a uniform shape.

Streaming bridge: MediaMTX (prebuilt binary, not custom Pion glue —
decided in `Project_Context.md` §2, don't relitigate).

## Explicitly not building

Face recognition, generic anomaly detection (intrusion/crowding) — cut
unless the core vehicle pipeline is done early
(`Project_Context.md` §4, §8).

## Status

Not yet started — this is the frame. Depends on `shared/db/` having the
watchlist/detections/alerts tables and `docs/DATASET.md` having a real
answer before eval numbers mean anything.
