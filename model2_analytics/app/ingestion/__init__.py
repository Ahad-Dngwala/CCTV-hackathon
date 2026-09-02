"""
model2_analytics.app.ingestion — shim package.

All actual source files live in model2-analytics/app/ingestion/.
This package re-imports them into the model2_analytics namespace
so both import paths work:

    from model2_analytics.app.ingestion.worker import CameraWorker
    # and internally within the real files:
    from ingestion.worker import CameraWorker  (when model2-analytics/app is on sys.path)
"""
import importlib
import sys
import os
import types

# Ensure model2-analytics/app is on sys.path for direct ingestion imports
_real_app = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', 'model2-analytics', 'app')
)
if _real_app not in sys.path:
    sys.path.insert(0, _real_app)
