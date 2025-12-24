from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # HMAC Secret for webhook signature validation
    hmac_secret: str = "dev-secret-key"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "webhook_system"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Downstream service
    downstream_url: str = "http://localhost:8001"

    # Application settings
    log_level: str = "INFO"
    worker_poll_interval: float = 1.0
    max_retry_attempts: int = 5

    # Retry backoff settings (in seconds)
    retry_base_delay: float = 1.0
    retry_max_delay: float = 16.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

