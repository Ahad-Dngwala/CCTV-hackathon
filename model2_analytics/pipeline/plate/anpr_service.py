"""
ANPR Service — Provider Factory
=================================
Single point of truth for which ANPR recognizer is used in production.
Both the live pipeline runner and the recorded video worker call
get_plate_recognizer() here; tests inject their own mock directly.

Environment variables:
    ANPR_PROVIDER=awiros   (default) — use AwirosPlateRecognizer
    ANPR_PROVIDER=none     — disable ANPR (no plates will be read)

To add a new provider (e.g. HTTP-based):
    1. Implement PlateRecognizerInterface in a new file.
    2. Add a branch here.
    3. No other code needs changing.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from pipeline.plate.interface import PlateRecognizerInterface

logger = logging.getLogger("sentinel.anpr_service")
# Read environment variable exactly once at module load
_PROVIDER_ENV = os.getenv("ANPR_PROVIDER", "parseq").lower().strip()

# Module-level cache — shared across the process lifetime
_recognizer: Optional[PlateRecognizerInterface] = None


def get_plate_recognizer() -> Optional[PlateRecognizerInterface]:
    """
    Return the configured ANPR recognizer (singleton per process).

    Defaults to 'parseq' (Fine-Tuned Indian PARSeq Vision Transformer).
    Returns None if ANPR_PROVIDER=none or if the provider fails to load.
    Callers must handle None gracefully (no plate read, not an error).
    """
    global _recognizer

    if _recognizer is not None:
        return _recognizer

    provider_env = os.getenv("ANPR_PROVIDER", _PROVIDER_ENV).lower().strip()

    if _PROVIDER_ENV == "none" or provider_env == "none":
        logger.info("ANPR disabled via ANPR_PROVIDER=none")
        return None

    if provider_env in ("parseq", "indian_parseq"):
        try:
            from pipeline.plate.parseq_provider import IndianPARSeqProvider
            _recognizer = IndianPARSeqProvider.get_instance()
            logger.info("ANPR provider loaded: IndianPARSeqProvider (Fine-Tuned)")
            return _recognizer
        except Exception as e:
            logger.error(f"Failed to load IndianPARSeqProvider: {e}")
            return None

    if provider_env == "fastalpr":
        try:
            from pipeline.plate.fastalpr_provider import FastALPRProvider
            _recognizer = FastALPRProvider.get_instance()
            logger.info("ANPR provider loaded: FastALPRProvider")
            return _recognizer
        except Exception as e:
            logger.error(f"Failed to load FastALPRProvider: {e}")
            return None

    if provider_env in ("awiros", "local", "onnx"):
        try:
            from pipeline.plate.awiros_provider import AwirosPlateRecognizer
            _recognizer = AwirosPlateRecognizer.get_instance()
            logger.info("ANPR provider loaded: AwirosPlateRecognizer (local OCR stack)")
            return _recognizer
        except Exception as e:
            logger.error(f"Failed to load AwirosPlateRecognizer: {e}")
            return None

    logger.warning(f"Unknown ANPR_PROVIDER='{provider_env}' — ANPR disabled")
    return None


def reset_recognizer():
    """Reset cached instance (test helper)."""
    global _recognizer
    _recognizer = None
