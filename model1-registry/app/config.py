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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
