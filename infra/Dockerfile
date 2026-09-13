# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

# System deps for psycopg2, geoalchemy2, and OpenCV/FFmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev libgeos-dev ffmpeg libsm6 libxext6 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps — model1, model2 (VMS ingestion + ANPR), model3 (federation).
# Previously this was two separate RUN steps, the second of which
# (`pip install ultralytics onnxruntime onnxocr`) re-installed ultralytics
# a SECOND time on top of the copy model2's own requirements.txt already
# pulls in, with none of the three pinned to a version -- so a fresh build
# re-resolved and re-downloaded the latest ultralytics/onnxruntime/onnxocr
# (and their transitive torch/torchvision) from PyPI every single time,
# with no way to know in advance if a new release would break something.
# onnxruntime/onnxocr are now pinned in model2_analytics/requirements.txt
# instead, and the duplicate ultralytics install is gone entirely.
#
# `--mount=type=cache,target=/root/.cache/pip` (BuildKit; on by default in
# Docker Compose v2) persists pip's downloaded/built wheels across builds
# in a cache that lives outside any image layer, so builds after the first
# one reuse cached wheels instead of re-downloading torch/torchvision/etc
# from the network every time. This is the fix for "docker compose doesn't
# use the cached python thingies at all" -- there was no cache mount here
# before, and `--no-cache-dir` was actively telling pip not to keep one.
# model3_federation's requirements.txt (redis/aioredis) is now installed
# too -- see the COPY note below for why that matters.
COPY model1-registry/requirements.txt /app/requirements.txt
COPY model2_analytics/requirements.txt /app/requirements-model2.txt
COPY model3_federation/requirements.txt /app/requirements-model3.txt

# This container has no GPU (no `deploy.devices`/nvidia runtime anywhere in
# docker-compose.yml, base image is plain python:3.12-slim) but
# facenet-pytorch and ultralytics both depend on torch with no build
# variant specified, so pip's default PyPI index resolves the default
# CUDA-enabled torch build -- which drags in ~10 `nvidia-*` wheels
# (cublas, cudnn, cusolver, nccl, etc) as transitive deps purely to
# support GPU hardware this container will never have. Verified locally:
# just 4 of those packages alone total ~1.9GB. Installing the CPU-only
# build from PyTorch's own CPU wheel index FIRST, pinned to the exact
# version facenet-pytorch/ultralytics need, satisfies their requirement
# before the default-index install ever runs -- pip sees torch already
# installed at a matching version and skips re-resolving/downloading it,
# so the CUDA wheels are never fetched at all. If you bump
# facenet-pytorch/ultralytics later, re-check what torch version they
# need and update this pin to match (a mismatch here just means this
# line's install goes unused and you're back to the CUDA download).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.2.2 torchvision==0.17.2

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt -r requirements-model2.txt -r requirements-model3.txt

# Copy source
COPY shared/ /app/shared/
COPY model1-registry/app/ /app/app/
COPY model2_analytics/ /app/model2_analytics/
# Previously missing entirely: model1-registry/app/main.py does
# `from model3_federation.api.router import ...` at import time, so
# without this the image is broken the instant it's run WITHOUT
# docker-compose.yml's `../model3_federation:/app/model3_federation` bind
# mount papering over the gap -- e.g. a plain `docker build` + `docker run`,
# or any deploy target that doesn't carry that specific compose file's
# volumes, crashes on startup with ModuleNotFoundError before serving a
# single request. The bind mount in docker-compose.yml still wins for
# local dev (so live-editing model3_federation/ still works without a
# rebuild); this line just makes the image correct on its own too.
COPY model3_federation/ /app/model3_federation/

# Standard hardening: run as a non-root user instead of the container
# default (root). Not urgent on its own (this app doesn't execute
# genuinely untrusted input), but cheap to do and limits the blast
# radius of any future RCE-class bug (AuditReport1.md finding 21 / 4.3).
# /app/model2_analytics/{detection-image,uploads} need to stay writable -
# the detection pipeline and uploads router write into them at runtime -
# so they're chowned explicitly rather than relying on a blanket
# `chown -R` catching everything by coincidence.
RUN useradd --system --create-home --uid 1000 --shell /usr/sbin/nologin appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /app/model2_analytics/detection-image /app/model2_analytics/uploads && \
    chown -R appuser:appuser /app/model2_analytics/detection-image /app/model2_analytics/uploads
USER appuser

# AuditReport2.md finding 5: model2_analytics/ used to be COPY'd into the
# image three separate times under three different names/paths (the full
# hyphenated package, an app/-only copy, and the underscored shim) so that
# each of its three import spellings (`pipeline.*`, `ingestion.*`,
# `model2_analytics.app.ingestion.*` — see supervisor.py and
# model1-registry/app/main.py) would resolve. There's now exactly one copy
# on disk at /app/model2_analytics/; these three PYTHONPATH entries are
# what make all three spellings still resolve to that single copy:
#   /app                      -> model2_analytics.app.ingestion.* (dotted)
#   /app/model2_analytics     -> pipeline.* (top-level)
#   /app/model2_analytics/app -> ingestion.* (top-level)
ENV PYTHONPATH=/app:/app/model2_analytics:/app/model2_analytics/app
# Runtime config defaults — override via docker-compose environment or .env
ENV GRID_HOST=cctv.corp8.cloud
ENV MEDIAMTX_API=mediamtx:9997
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
