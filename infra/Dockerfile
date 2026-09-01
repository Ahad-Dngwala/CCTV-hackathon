FROM python:3.12-slim

# System deps for psycopg2, geoalchemy2, and OpenCV/FFmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev libgeos-dev ffmpeg libsm6 libxext6 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY model1-registry/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY shared/ /app/shared/
COPY model1-registry/app/ /app/app/
COPY model2-analytics/ /model2-analytics/

ENV PYTHONPATH=/app:/model2-analytics
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

