"""What a discipline module offers analytics: the type-only surface of its analytics package.

``DisciplineSpec.analytics`` returns the package module itself (``shared.disciplines.<slug>.analytics``), so there is no
adapter object, factory or second registry. No pandas/scikit-learn/SQLAlchemy import happens at runtime: the frames and
sessions below are forward references, so the registry stays importable by services that never run analytics.
"""

from __future__ import annotations

import typing
from collections.abc import Callable, Iterable, Mapping, Sequence

if typing.TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from openskill.models import PlackettLuceRating
    from sqlalchemy.ext.asyncio import AsyncSession

    from shared.division_grid import DivisionGrid
    from shared.domain.analytics import (
        MLTrainDevice,
        ModelDeclaration,
        PerformanceTrainingResult,
        ShiftTrainingResult,
        StandingsTrainingResult,
    )
    from shared.models import Player, Team

__all__ = ("AnalyticsExports",)


class AnalyticsExports(typing.Protocol):
    """The existing operations a service consumes from a discipline's analytics package.

    Implemented by the package module itself (``shared.disciplines.<slug>.analytics``): each member below is a function
    or class defined there with this exact contract. Declarations are explicit; nothing is looked up by string.
    """

    # --- Model declarations -----------------------------------------------------------------------------------
    MODELS: Mapping[str, ModelDeclaration]
    INFERENCE_KINDS: tuple[str, ...]

    # --- Core extractors ---------------------------------------------------------------------------------------
    async def extract_match_features(
        self,
        session: AsyncSession,
        tournament_ids: Iterable[int],
        *,
        workspace_id: int | None = None,
        workspace_ids: Sequence[int] | None = None,
    ) -> pd.DataFrame: ...

    async def extract_tournament_features(
        self,
        session: AsyncSession,
        tournament_ids: Iterable[int],
        *,
        workspace_id: int | None = None,
        workspace_ids: Sequence[int] | None = None,
    ) -> pd.DataFrame: ...

    async def extract_encounter_features(
        self,
        session: AsyncSession,
        tournament_ids: Iterable[int],
        *,
        workspace_id: int | None = None,
        workspace_ids: Sequence[int] | None = None,
    ) -> pd.DataFrame: ...

    async def extract_round_residuals(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        workspace_id: int | None = None,
        workspace_ids: Sequence[int] | None = None,
    ) -> pd.DataFrame: ...

    # --- Enrichment --------------------------------------------------------------------------------------------
    async def compute_mvp_dominance(self, session: AsyncSession, tournament_id: int) -> pd.DataFrame: ...

    async def load_player_signal_profile(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        history_depth: int = 5,
        workspace_id: int | None = None,
    ) -> pd.DataFrame: ...

    def attach_local_performance(
        self,
        per_player: pd.DataFrame,
        *,
        initial_radius: int = 2,
        max_radius: int = 3,
        min_reference_n: int = 20,
        prior_strength: float = 20.0,
    ) -> pd.DataFrame: ...

    async def team_synergy_features(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        workspace_id: int | None = None,
        workspace_ids: Sequence[int] | None = None,
    ) -> pd.DataFrame: ...

    def summarize_team_strength(
        self,
        teams: Sequence[Team],
        ratings: Mapping[str, PlackettLuceRating],
        *,
        rating_key: Callable[[Player], str],
    ) -> pd.DataFrame: ...

    # --- Frame assembly (pure; the service supplies the already-loaded cache/history/OpenSkill frames) ---------------
    def attach_encounter_strength(self, matches: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame: ...

    def attach_tournament_strength(self, tournament_features: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame: ...

    async def load_player_rank_history(
        self,
        session: AsyncSession,
        tournament_ids: Sequence[int],
        *,
        history_through_tournament_id: int | None = None,
        workspace_id: int | None = None,
        workspace_ids: Sequence[int] | None = None,
    ) -> pd.DataFrame: ...

    async def load_performance_features(self, session: AsyncSession, tournament_ids: Sequence[int]) -> pd.DataFrame: ...

    def assemble_shift_tournament_frame(
        self,
        tournament_id: int,
        *,
        tournament_features: pd.DataFrame,
        rank_history: pd.DataFrame,
        history: pd.DataFrame,
        shift_map: Mapping[int, tuple[float, float]],
        performance_features: pd.DataFrame,
        dominance: pd.DataFrame,
    ) -> pd.DataFrame: ...

    def concat_shift_frames(self, frames: Sequence[pd.DataFrame]) -> pd.DataFrame: ...

    async def team_rank_stats(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        workspace_id: int | None = None,
        workspace_ids: Sequence[int] | None = None,
    ) -> pd.DataFrame: ...

    async def team_performance_mean(self, session: AsyncSession, tournament_ids: Sequence[int]) -> pd.DataFrame: ...

    def team_strength_frame(self, mu: pd.DataFrame, synergy: pd.DataFrame, *, tournament_id: int) -> pd.DataFrame: ...

    def standings_forecast_frame(
        self,
        rank_stats: pd.DataFrame,
        mu: pd.DataFrame,
        synergy: pd.DataFrame,
        *,
        tournament_id: int,
    ) -> pd.DataFrame: ...

    def standings_training_frame(
        self,
        encounters: pd.DataFrame,
        team_frames: Sequence[pd.DataFrame],
        performance: pd.DataFrame,
    ) -> pd.DataFrame: ...

    # --- Models ------------------------------------------------------------------------------------------------
    def features_for_role(self, role: str) -> list[str]: ...

    def train_performance_v2(
        self,
        df: pd.DataFrame,
        *,
        role: str,
        val_df: pd.DataFrame | None = None,
        devices: Sequence[MLTrainDevice],
    ) -> PerformanceTrainingResult: ...

    def train_standings_v2(
        self,
        df: pd.DataFrame,
        *,
        val_df: pd.DataFrame | None = None,
        devices: Sequence[MLTrainDevice],
    ) -> StandingsTrainingResult: ...

    def train_shift_v2(
        self,
        df: pd.DataFrame,
        *,
        val_df: pd.DataFrame | None = None,
        w_team: float,
        w_os: float,
        indiv_scale_top: float,
        indiv_scale_bottom: float,
        indiv_clamp_top: float,
        indiv_clamp_bottom: float,
        dominance_gain: float,
        dominance_cap: float,
        placement_floor: float,
        clamp_top_grid_ref: float,
    ) -> ShiftTrainingResult: ...

    def aggregate_to_tournament(
        self, match_df: pd.DataFrame, y_hat: pd.Series, y_q10: pd.Series, y_q90: pd.Series
    ) -> pd.DataFrame: ...

    def impact_score_within_role(self, per_player: pd.DataFrame) -> pd.Series: ...

    def stabilize_small_cohort_impact(self, per_player: pd.DataFrame, *, min_cohort: int = 8) -> pd.DataFrame: ...

    def simulate_standings(
        self,
        matchups: pd.DataFrame,
        team_ids: Sequence[int],
        *,
        n_iter: int = 5000,
        rng: np.random.Generator | None = None,
        prob_sharpening: float = 1.0,
    ) -> pd.DataFrame: ...

    # --- Scale -------------------------------------------------------------------------------------------------
    def canonical_div_for(
        self, grids: dict[int, DivisionGrid], version_id: int | float | None, rank: int | float | None
    ) -> int | None: ...

    def assign_canonical_division(
        self,
        df: pd.DataFrame,
        grids: dict[int, DivisionGrid],
        *,
        rank_col: str,
        version_col: str = "version_id",
        out_col: str = "div",
    ) -> pd.DataFrame: ...

    # --- Nonserialized outputs -----------------------------------------------------------------------------------
    def compute_match_quality(
        self,
        encounters: pd.DataFrame,
        match_scores: pd.DataFrame,
        *,
        competitiveness_weight: float = ...,
        predictability_weight: float = ...,
        skill_balance_weight: float = ...,
        sigma_pool: float | None = None,
    ) -> pd.DataFrame: ...

    def detect_smurfs(
        self,
        df: pd.DataFrame,
        *,
        contamination: float = 0.05,
        impact_threshold: float = 80.0,
        rank_threshold: float = 35.0,
        local_z_threshold: float = 0.9,
        local_percentile_threshold: float = 80.0,
        strong_local_z_threshold: float = 1.5,
        mvp_dominance_threshold: float = 0.75,
        min_role_size: int = 3,
    ) -> list[dict[str, typing.Any]]: ...

    def detect_trolls(
        self,
        df: pd.DataFrame,
        *,
        window: int = 3,
        z_threshold: float = -1.35,
        single_tournament_z_threshold: float = -1.9,
        single_tournament_impact_threshold: float = 18.0,
    ) -> list[dict[str, typing.Any]]: ...

    def detect_sandbags(
        self,
        df: pd.DataFrame,
        *,
        min_history: int = 2,
        min_current_z: float = -1.25,
        min_drop_z: float = 1.45,
        prior_mean_floor: float = -0.25,
    ) -> list[dict[str, typing.Any]]: ...

    def detect_throws(
        self,
        round_residuals: pd.DataFrame,
        *,
        drop_threshold: float = 1.45,
        min_pre_mean: float = 0.65,
        max_post_mean: float = -0.75,
        min_post_negative_fraction: float = 0.65,
        pelt_penalty: float = 2.5,
    ) -> list[dict[str, typing.Any]]: ...
