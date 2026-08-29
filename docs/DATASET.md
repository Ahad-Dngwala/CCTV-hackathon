# Dataset

**Status: not yet decided.** Owner: TBD.

## What we need

- A recorded feed we control, for two purposes:
  1. The "Own-Feed Demonstration" deliverable (see `HackathonPortal.md`).
  2. A hand-labeled test set to run the precision/recall/F1 eval harness
     against, per `Project_Context.md` §5 — needed for plate detection,
     OCR, watchlist alerting, and (if built) cross-camera tracking.
- Enough labeled vehicle/plate instances to get a meaningful confusion
  matrix, not just a handful of clips.

## Options on the table (none decided yet)

- Synthesize: record our own footage (parking lot, street-facing window,
  etc.) and hand-label plates.
- Source an existing Indian-plate ANPR dataset and re-label/subset it to
  match our schema (`detected_plate`, `confidence`, bounding boxes).
- Some mix — real footage for the demo video, an existing dataset for
  the eval harness numbers, since those don't have to come from the same
  source.

## Constraints to keep in mind whenever this gets decided

- Plate detectors trained on US/EU plates underperform on Indian plate
  proportions/fonts (`Project_Context.md` §4) — whatever we use has to
  actually reflect that, or the eval numbers won't mean anything for the
  real government feed at evaluation time.
- The live government feed at Step 4 is the actual scored test — this
  dataset is for building/validating the pipeline beforehand, not a
  substitute for handling live RTSP per `model2-analytics/README.md`.

Fill this file in once a direction is picked — what was chosen, how many
clips/plates, labeling method, where it lives (not committed to git if
it's large — note the actual storage location here instead).
