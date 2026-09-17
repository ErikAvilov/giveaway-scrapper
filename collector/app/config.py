"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


class Settings(BaseSettings):
    """Runtime settings. Credentials come only from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr = Field(
        ...,
        description="Neon PostgreSQL pooled connection string",
    )
    # Optional: only required when instantiating GeminiClient.
    gemini_api_key: SecretStr | None = Field(
        default=None,
        description="Google Gemini API key (required for analyze/pipeline/worker)",
    )
    gemini_model: str = Field(
        default=DEFAULT_GEMINI_MODEL,
        description="Gemini model id",
    )
    gemini_batch_size: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max giveaways per generate_content call (micro-batch)",
    )
    gemini_max_requests_per_minute: int = Field(
        default=6,
        ge=1,
        le=60,
        description="Process-level cap on Gemini API request starts per rolling minute",
    )
    log_level: LogLevel = Field(default="INFO", description="Logging level")

    # --- Crawler (Raspberry Pi 5 friendly defaults) ---
    crawl_concurrent_requests: int = Field(default=2, ge=1, le=16)
    crawl_concurrent_requests_per_domain: int = Field(default=1, ge=1, le=8)
    crawl_download_delay: float = Field(default=1.0, ge=0.0)
    crawl_max_depth: int = Field(default=2, ge=0, le=5)
    crawl_max_pages_per_source: int = Field(default=40, ge=1, le=500)
    crawl_request_timeout: float = Field(default=20.0, ge=5.0, le=120.0)
    crawl_retries: int = Field(default=2, ge=0, le=5)
    crawl_autothrottle: bool = Field(default=True)
    crawl_autothrottle_start_delay: float = Field(default=1.0, ge=0.0)
    crawl_autothrottle_max_delay: float = Field(default=30.0, ge=1.0)
    crawl_candidate_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    crawl_raw_excerpt_max_chars: int = Field(default=3000, ge=500, le=20000)
    gleam_directory_max_pages: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Max Gleam.io /giveaways listing pages (sort×pagination) per crawl",
    )

    # --- Continuous worker (Pi) ---
    worker_idle_sleep_seconds: float = Field(default=60.0, ge=5.0, le=3600.0)
    worker_error_sleep_seconds: float = Field(default=30.0, ge=5.0, le=600.0)
    worker_analyze_limit: int = Field(default=25, ge=1, le=200)
    worker_heartbeat_path: str = Field(default="/tmp/collector_heartbeat")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings. Raises ValidationError if required env vars are missing."""
    return Settings()


def require_gemini_api_key(settings: Settings) -> str:
    """Return the Gemini API key or raise a clear error."""
    if settings.gemini_api_key is None:
        raise ValueError("GEMINI_API_KEY is required for Gemini analysis")
    key = settings.gemini_api_key.get_secret_value().strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is required for Gemini analysis")
    return key
