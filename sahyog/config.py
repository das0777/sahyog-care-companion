from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sahyog:sahyog-dev@localhost:5433/sahyog"
    test_database_url: str = "postgresql+psycopg://sahyog:sahyog-dev@localhost:5433/sahyog_test"
    redis_url: str = "redis://localhost:6380/0"

    minio_endpoint: str = "localhost:9100"
    minio_root_user: str = "sahyog"
    minio_root_password: str = "sahyog-dev-secret"  # noqa: S105 - local dev default
    minio_secure: bool = False
    report_bucket: str = "reports"
    audio_bucket: str = "audio"
    audio_retention_days: int = 1  # E6.3: consultation audio gone within 24 h

    jwt_secret: str = "local-dev-only-secret-replace-for-any-shared-env"  # noqa: S105 - local dev default
    jwt_ttl_minutes: int = 480

    seed_random_seed: int = 42
    timezone: str = "Asia/Kolkata"

    # Model gateway. "fake" needs no key or network and is what tests and `make eval` use.
    llm_provider: Literal["fake", "anthropic", "openrouter"] = "fake"
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_small_model: str = "anthropic/claude-haiku-5.5"
    openrouter_large_model: str = "anthropic/claude-sonnet-5.5"
    llm_small_model: str = "claude-haiku-5-5"
    llm_large_model: str = "claude-sonnet-5-5"
    llm_in_region_model: str = "llama3.1:8b"
    ollama_url: str = "http://host.docker.internal:11434"
    llm_timeout_s: float = 20.0
    prices_file: str = "config/prices.yaml"

    # Ingest. Embeddings run locally: report text never leaves the boundary for this
    embedder: Literal["local", "hash"] = "local"
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_threads: int = 4
    model_cache_dir: str = "/models"
    ingest_workers: int = 2
    ingest_lease_s: int = 180
    whisper_model: str = "small"
    dev_login: bool = False  # /dev/login makes anyone anyone: local demo only
    stock_csv: str = "config/stock.csv"

    @property
    def has_real_model(self) -> bool:
        return (self.llm_provider == "anthropic" and bool(self.anthropic_api_key)) or (
            self.llm_provider == "openrouter" and bool(self.openrouter_api_key)
        )

    @property
    def outside_models(self) -> tuple[str, str]:
        """The (small, large) models for the configured outside provider."""
        if self.llm_provider == "openrouter":
            return self.openrouter_small_model, self.openrouter_large_model
        return self.llm_small_model, self.llm_large_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
