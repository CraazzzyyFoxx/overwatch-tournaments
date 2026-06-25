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
    # local_zscore (vs same role + nearby division), additive, clamped. The
    # scale AND clamp are RANK-DEPENDENT — they ramp linearly with the canonical
    # division number (1 = top … 40 = bottom): ``_top`` applies near the ceiling
    # (the same +N is a sparse, high-variance, capped claim there) and
    # ``_bottom`` at the lowest ranks (over-/under-ranking is common and cheap).
    shift_indiv_scale_top: float = 0.2
    shift_indiv_scale_bottom: float = 0.8
    shift_indiv_clamp_top: float = 0.75
    shift_indiv_clamp_bottom: float = 2.0
    # Output clamp: bottom-of-ladder (low rank) keeps the full ±3; the top is
    # squeezed to ``grid_n_div / shift_clamp_top_grid_ref`` divisions (a
    # 20-division grid → ±1 at the top, a 40-division grid → ±2) so no source
    # (team/OS backbone or individual term) can yank a high-rank player the full
    # range from one tournament. Retrain shift v2 to snapshot changes.
    shift_clamp_top_grid_ref: float = 20.0
    # Raw match-log MVP-dominance lift for the individual term: ``mvp_dominance``
    # ∈ [0,1] (0.5 = median) → ``(dom-0.5)*gain`` clamped to ``cap``, then bounded
    # by the rank/grid output clamp (not the softer local clamp) so a consistent
    # scoreboard-topper is pushed to their rank-appropriate ceiling. Retrain to snapshot.
    shift_dominance_gain: float = 6.0
    shift_dominance_cap: float = 3.0

    # Smurf flag: a local_zscore (skill vs same role + nearby division) at/above
    # this flags the player as a strong cohort outlier regardless of rank (in
    # addition to the classic low-rank smurf rule).
    smurf_strong_local_z: float = 1.5
    # Smurf flag: a raw match-log ``mvp_dominance`` (mean per-match MVP position,
    # 0.5 = median) at/above this flags a consistent scoreboard-topper that the
    # expectation-adjusted impact/local_zscore under-credit.
    smurf_mvp_dominance: float = 0.75

    # Read-side cache TTL (matches the app-service default).
    tournaments_cache_ttl: int = 60 * 5

    @property
    def broker_url(self) -> str | None:
        return self.rabbitmq_url


settings = AppConfig()
