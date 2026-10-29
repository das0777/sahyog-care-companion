from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
