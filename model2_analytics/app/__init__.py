"""
model2_analytics.app — sub-package shim.

Delegates to model2-analytics/app/ via sys.path manipulation.
The actual source files live in model2-analytics/app/ingestion/.
"""
import sys
import os
import logging

logger = logging.getLogger(__name__)

# Add model2-analytics/app to sys.path so sub-imports resolve correctly
_m2_app = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'model2-analytics', 'app')
)
if _m2_app not in sys.path:
    sys.path.insert(0, _m2_app)
logger.debug(f"[model2_analytics.app] Resolved _m2_app path: {_m2_app}")
