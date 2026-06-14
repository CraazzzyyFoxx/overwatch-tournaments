import typing

from pydantic import RedisDsn
from shared.core.config import BaseServiceSettings


class AppConfig(BaseServiceSettings):
    project_name: str = "Anak Tournaments — Analytics"
    debug: bool = False
    port: int = 8006

    redis_url: RedisDsn

    # RabbitMQ
    rabbitmq_url: str | None = None

    # ML artifact storage root (filesystem path or s3:// URI). Used by v2 model registry.
    analytics_models_dir: str = "/opt/anak/models"

    # File-backed feature cache for expensive ML frame builders. This is not a
    # source of truth; bump the namespace or clear the directory after changing
    # feature logic or reprocessing historical logs.
    analytics_feature_cache_enabled: bool = True
    analytics_feature_cache_dir: str = "/cache/analytics/features"
    analytics_feature_cache_namespace: str = "v1"
    analytics_feature_cache_ttl_seconds: int = 60 * 60 * 24 * 7

    # ML training accelerator. ``auto`` tries GPU backends first and falls back
    # to CPU; ``cuda`` targets NVIDIA CUDA; ``gpu`` targets LightGBM OpenCL
    # and maps to CUDA for XGBoost; ``cpu`` is the portable baseline.
    ml_train_device: typing.Literal["auto", "cpu", "cuda", "gpu"] = "auto"
    ml_gpu_fallback: bool = True

    # Standings v2 Monte-Carlo win-probability sharpening exponent. ``1.0``
    # disables it; ``>1`` pushes calibrated P(home wins) away from 0.5 before the
    # simulation so predicted places spread across the field instead of
    # collapsing toward the median rank. Applied at inference (no retrain).
    standings_prob_sharpening: float = 1.5

    # Shift v2 merit calibration: divisions of suggested shift per 1 std-dev of
    # context-adjusted individual over/under-performance (Performance v2
    # local_zscore). Default +2σ ≈ +1 division. Used as the supervised target
    # when training Shift v2 — retrain to take effect.
    shift_merit_scale: float = 0.5

    # Read-side cache TTL (matches the app-service default).
    tournaments_cache_ttl: int = 60 * 5

    @property
    def broker_url(self) -> str | None:
        return self.rabbitmq_url


settings = AppConfig()
