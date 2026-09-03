"""
Shim: re-exports from model2-analytics/app/ingestion/supervisor.py
"""
import sys, os, logging
logger = logging.getLogger(__name__)

_real_app = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'model2-analytics', 'app'))
if _real_app not in sys.path:
    sys.path.insert(0, _real_app)
logger.debug(f"[model2_analytics.app.ingestion.supervisor] Resolved _real_app path: {_real_app}")

from ingestion.supervisor import IngestionSupervisor  # noqa: F401, E402

__all__ = ['IngestionSupervisor']
