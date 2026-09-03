"""
Shim: re-exports CameraWorker from the real implementation in model2-analytics/app/ingestion/worker.py.
Allows `from model2_analytics.app.ingestion.worker import CameraWorker` to work.
"""
import sys
import os
import logging

logger = logging.getLogger(__name__)

# Add model2-analytics/app to path if not already there
_real_app = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'model2-analytics', 'app')
)
if _real_app not in sys.path:
    sys.path.insert(0, _real_app)
logger.debug(f"[model2_analytics.app.ingestion.worker] Resolved _real_app path: {_real_app}")

# Now import from the real location
from ingestion.worker import CameraWorker, RECONNECT_BASE_SECONDS, RECONNECT_MAX_SECONDS  # noqa: E402, F401

__all__ = ['CameraWorker', 'RECONNECT_BASE_SECONDS', 'RECONNECT_MAX_SECONDS']
