FROM python:3.12-slim

# System deps for psycopg2, geoalchemy2, and OpenCV/FFmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev libgeos-dev ffmpeg libsm6 libxext6 libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps — model1 first, then model2 (VMS ingestion)
COPY model1-registry/requirements.txt /app/requirements.txt
COPY model2-analytics/requirements.txt /app/requirements-model2.txt
RUN pip install --no-cache-dir -r requirements.txt -r requirements-model2.txt

# Copy source
COPY shared/ /app/shared/
COPY model1-registry/app/ /app/app/
COPY model2-analytics/ /model2-analytics/
COPY model2-analytics/app/ /app/model2_analytics_src/
COPY model2_analytics/ /app/model2_analytics/

ENV PYTHONPATH=/app:/model2-analytics:/app/model2_analytics_src
# Runtime config defaults — override via docker-compose environment or .env
ENV GRID_HOST=cctv.corp8.cloud
ENV MEDIAMTX_API=mediamtx:9997
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
