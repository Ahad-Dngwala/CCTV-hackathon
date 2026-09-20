"""
Model 2 - ByteTrack Multi-Object Vehicle Tracker
Assigns persistent track IDs to detected vehicles across frames.
"""

import logging
import numpy as np
from collections import deque
from typing import List, Dict, Any, Optional, Tuple

from pipeline.config import TRACK_BUFFER, MAX_TIME_LOST

logger = logging.getLogger("sentinel.tracking")
logger.setLevel(logging.INFO)

# -- Geometric plausibility: expected bbox area ranges (pixels) --------
# Derived from empirical observation of Step 1 comparison data.
# Used as a tie-breaker when class votes are close.
# Format: class_name -> (min_reasonable_area, max_reasonable_area)
GEOMETRIC_AREA_RANGES = {
    "Motorcycle": (500, 15000),
    "Bicycle": (500, 10000),
    "Auto Rickshaw": (3000, 35000),
    "Car": (8000, 50000),
    "Mini-Truck": (15000, 45000),
    "Truck": (25000, 120000),
    "Bus": (30000, 420000),
    "Van": (8000, 40000),
}


class Track:
    """Single vehicle track state."""

    _next_id = 0

    def __init__(self, detection: Dict[str, Any]):
        Track._next_id += 1
        self.track_id = Track._next_id
        self.bbox = detection["bbox"]
        self.class_id = detection["class_id"]
        self.class_name = detection["class_name"]
        self.confidence = detection["confidence"]
        self.hit_streak = 1
        self.time_since_update = 0
        self.history: List[List[float]] = [detection["bbox"]]
        self.color = self._generate_color()
        # Rolling class vote: store (class_name, class_id, confidence) per update
        self._class_votes: deque = deque(maxlen=12)
        self._class_votes.append((detection["class_name"], detection["class_id"], detection["confidence"]))

    def _generate_color(self) -> Tuple[int, int, int]:
        """Generate a unique color per track ID for visualization."""
        rng = np.random.default_rng(self.track_id * 42)
        return tuple(int(c) for c in rng.integers(100, 255, size=3))

    def _avg_bbox_area(self) -> float:
        """Compute mean bbox area from track history."""
        if not self.history:
            return 0.0
        areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in self.history]
        return float(np.mean(areas))

    def _geometric_score(self, class_name: str, avg_area: float) -> float:
        """
        Return a plausibility score in [0, 1] for `class_name` given the
        track's average bbox area. 1.0 = perfectly plausible, 0.0 = impossible.
        """
        lo, hi = GEOMETRIC_AREA_RANGES.get(class_name, (0, float("inf")))
        if lo <= avg_area <= hi:
            return 1.0
        # Penalize proportionally to distance outside the range
        if avg_area < lo:
            ratio = avg_area / lo if lo > 0 else 0.0
        else:
            ratio = hi / avg_area if avg_area > 0 else 0.0
        return max(0.0, min(1.0, ratio))

    def _refresh_class_from_votes(self):
        """Recompute authoritative class from confidence-weighted rolling vote + geometry.

        Geometry weight is 20% (was 30%) so vote confidence dominates on correct tracks.
        EXTRA RULE: if avg_area < Bus minimum range (30 000 px^2), apply an additional
        x0.30 penalty to Bus votes -- the Indian traffic model mislabels Cars as Bus on
        this camera angle; geometry corrects this for tracks whose bbox area is solidly
        in Car territory (< 30 000 px^2).
        """
        if not self._class_votes:
            return
        # Confidence-weighted vote scores
        scores: Dict[Tuple[str, int], float] = {}
        for cname, cid, conf in self._class_votes:
            key = (cname, cid)
            scores[key] = scores.get(key, 0.0) + conf

        # Apply geometric plausibility as a soft penalty
        avg_area = self._avg_bbox_area()
        if avg_area > 0:
            bus_lo = GEOMETRIC_AREA_RANGES.get("Bus", (30000, 200000))[0]
            bus_hi = GEOMETRIC_AREA_RANGES.get("Bus", (30000, 200000))[1]
            adjusted: Dict[Tuple[str, int], float] = {}
            for key, vote_score in scores.items():
                cname = key[0]
                geo = self._geometric_score(cname, avg_area)
                # Weight: 80% vote, 20% geometry
                adj = vote_score * (0.8 + 0.2 * geo)
                # Hard downweight: if area is below Bus minimum AND this is a Bus vote,
                # apply extra penalty to correct model mislabels on this camera angle
                if cname == "Bus" and avg_area < bus_lo:
                    adj *= 0.30
                adjusted[key] = adj
            scores = adjusted

        best = max(scores, key=lambda k: scores[k])
        # Minimal Car->Bus fix: this camera yields unanimous but low-confidence
        # Bus votes (conf 0.35-0.66) on tracks whose bbox area is solidly inside
        # Car's geometric range (8000-50000 px^2). Accept a Bus label only if the
        # area is plausible for a Bus OR the Bus votes are strongly confident;
        # otherwise the detector's weak unanimous Bus prediction is treated as a
        # mislabel and the track falls back to Car.
        if best[0] == "Bus" and avg_area > 0:
            bus_conf_avg = (
                sum(conf for cname, _cid, conf in self._class_votes if cname == "Bus")
                / max(1, sum(1 for cname, _c, _conf in self._class_votes if cname == "Bus"))
            )
            if (avg_area < bus_lo or avg_area > bus_hi) and bus_conf_avg < 0.65:
                best = ("Car", 99)  # class_id sentinel; name is what downstream uses

        self.class_name, self.class_id = best

    def update(self, detection: Dict[str, Any]):
        """Update track with new detection, refresh class from rolling vote."""
        self.bbox = detection["bbox"]
        self.confidence = detection["confidence"]
        self.hit_streak += 1
        self.time_since_update = 0
        self.history.append(detection["bbox"])
        if len(self.history) > TRACK_BUFFER:
            self.history.pop(0)
        # Record the new detection's class for the rolling vote
        self._class_votes.append((detection["class_name"], detection["class_id"], detection["confidence"]))
        self._refresh_class_from_votes()

    def mark_missed(self):
        """Mark track as not detected in current frame."""
        self.time_since_update += 1
        self.hit_streak = 0

    def is_confirmed(self) -> bool:
        return self.hit_streak >= 3

    def is_deleted(self) -> bool:
        return self.time_since_update > MAX_TIME_LOST
