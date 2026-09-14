# OCR Engine Benchmark Harness (ocr_eval/)

Isolated benchmark for comparing license-plate OCR engines on the SAME fixed crop set.
Work branch: `feat/ocr-benchmark-awiros-fastplate` (branched from
`feat/model2-anpr-alerts-v2` @ `d06a766`). Production code is NOT modified here.

## Files
- `extract_crops.py` — extracts plate crops from videos with coordinates mapped back
  to the ORIGINAL full-resolution frame (not the resized YOLO inference image).
- `compare_engines.py` — runs every engine over the same crops, measures exact-plate
  accuracy, character accuracy, abstentions, and avg latency per crop.
- `crops/` — fixed crop set. Naming: `vidX_fNNNNN_pN_cNN.jpg` = video, frame index,
  plate index, confidence.

## Crop set
- `vid1R_*`, `vid1_*`, `vid2_*` — real plate crops from project test videos (28 crops).
- `dbg_*` — debug crops retained for reference.
- `ds_*.jpg` — larger dataset images (1–10 MB each, ~75 MB total) are **local-only**
  (excluded via `ocr_eval/.gitignore`); regenerate with `extract_crops.py` if needed.

## Rules
- Same crops for all engines (Awiros anpr-ocr, fast-plate-ocr/fast-alpr, PP-OCRv4/v5,
  EasyOCR baselines).
- Confidences are NOT compared across engines (not calibrated identically).
- Preprocessing variants (pad / perspective / enlarge / grayscale / sharpen) are
  measured, never assumed.
