"""
App configuration via pydantic-settings.

Reads from environment variables (or a .env file if present).
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://sentinel:sentinel_dev@127.0.0.1:5432/sentinel"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True
    SECRET_KEY: str = "sentinel-secret-key-hackathon-2026-secure"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours

    # VMS ingestion settings
    GRID_HOST: str = "cctv.corp8.cloud"
    MEDIAMTX_API: str = "localhost:9997"

    # Operational Sentinel Camera Grid gateway settings (configurable via env vars)
    GRID_RTSP_HOST: str = "103.250.160.189"  # Public static IP for direct RTSP & WebRTC
    GRID_RTSP_PORT: int = 8554               # Gateway RTSP port (TCP forced)
    GRID_RTSP_USER: str = os.getenv("GRID_RTSP_USER", "")
    GRID_RTSP_PASS: str = os.getenv("GRID_RTSP_PASS", "")
    GRID_WHEP_PORT: int = 8889               # Gateway WHEP WebRTC signaling port
    GRID_CDN_HOST: str = "cctv.corp8.cloud"  # CDN host for HLS

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
