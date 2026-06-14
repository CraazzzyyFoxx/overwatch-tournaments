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

    # Linear shift signal scale (the v1 "Linear" algorithm and the v2 baseline).
    # Maps the EMA-weighted per-tournament team-result signal to division units.
    # Applied at read time — recompute v1 shifts to refresh stored rows.
    linear_shift_scale: float = 6.25

    # OpenSkill + ML (shift v2) blend. The team-result backbone is a
    # team-dominant convex mix of the Linear team signal and the OpenSkill mu
    # shift; the individual skill term is ADDED on top (so a player far above
    # their rank/role cohort moves even if the team result doesn't capture it).
    # Retrain shift v2 to snapshot changes into the artifact.
    shift_w_team: float = 0.7
    shift_w_os: float = 0.3
    # Individual skill modifier: divisions per std-dev of Performance v2
    # local_zscore (vs same role + nearby division), additive, clamped.
    shift_indiv_scale: float = 0.5
    shift_indiv_clamp: float = 1.5

    # Read-side cache TTL (matches the app-service default).
    tournaments_cache_ttl: int = 60 * 5

    @property
    def broker_url(self) -> str | None:
        return self.rabbitmq_url


settings = AppConfig()
