from functools import lru_cache

from minio import Minio
from minio.commonconfig import ENABLED, Filter
from minio.lifecycleconfig import Expiration, LifecycleConfig, Rule

from sahyog.config import get_settings


@lru_cache
def get_minio() -> Minio:
    s = get_settings()
    return Minio(
        s.minio_endpoint,
        access_key=s.minio_root_user,
        secret_key=s.minio_root_password,
        secure=s.minio_secure,
    )


def ensure_buckets() -> None:
    """Create the buckets and the audio expiry rule (E6.3). Safe to run on every start."""
    s = get_settings()
    client = get_minio()
    for bucket in (s.report_bucket, s.audio_bucket):
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
    client.set_bucket_lifecycle(
        s.audio_bucket,
        LifecycleConfig(
            [
                Rule(
                    ENABLED,
                    rule_filter=Filter(prefix=""),
                    rule_id="audio-expiry",
                    expiration=Expiration(days=s.audio_retention_days),
                )
            ]
        ),
    )
