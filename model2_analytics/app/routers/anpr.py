"""
ANPR Pipeline API Router — REMOVED
====================================
The standalone ANPR page and API have been removed per the product
decision to integrate ANPR/OCR directly into the Live Detection and
Recorded Detection pages.

This file is kept as an empty router stub to avoid ImportError in
environments that may still import it. All routes have been removed.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/anpr", tags=["anpr"])


@router.get("/health")
async def anpr_health():
    """Retained health check — used by infra monitoring."""
    return {
        "status": "ok",
        "service": "anpr-integrated",
        "note": "ANPR now runs inside the detection pipeline. "
                "There is no standalone ANPR endpoint.",
    }