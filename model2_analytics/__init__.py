"""
model2_analytics — Python-importable package alias for model2-analytics/.

The repository directory is named 'model2-analytics' (with a hyphen) which
Python cannot import directly. This package re-exports all submodules from
the actual source location so the architecture's import paths work:

    from model2_analytics.app.ingestion.worker import CameraWorker

Works because sys.path includes the repo root (added by main.py and workers).
"""
