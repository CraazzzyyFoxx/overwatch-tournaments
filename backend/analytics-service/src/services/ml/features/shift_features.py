"""Shift v2 feature frame builder.

Joins:

- per-(player, tournament) tournament features (rates, mu features)
- v1 OpenSkill shift map (``os_shift``) from ``compute_openskill_shift_map``
- v1 linear metrics as the conservative baseline
- per-player tournament chronology to derive ``prior_div``,
  ``tournaments_played``, ``tournaments_at_current_div``,
  ``next_tournament_div``
- per-player Performance v2 row (``raw_value``, ``confidence``) if already
  materialised

The result is the input to :func:`train_shift_v2` and
:meth:`ShiftModelV2.predict`.
"""

from __future__ import annotations

import logging
import typing

import numpy as np
import pandas as pd
import sqlalchemy as sa
from shared.division_grid import DEFAULT_GRID, division_case_expr
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.workspace import workspace_scope_filter
from src.services.analytics.flows import (
    compute_linear_metrics,
    compute_openskill_shift_map,
    get_data_frame,
)

from .aggregations import build_tournament_feature_frame
from .cache import get_or_build_dataframe, scope_cache_params

__all__ = ("build_shift_feature_frame",)

logger = logging.getLogger(__name__)


async def _player_rank_history(
    session: AsyncSession,
    tournament_ids: typing.Sequence[int],
    *,
    history_through_tournament_id: int | None = None,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return ``(user_id, role, tournament_id, rank, div, prior_*, next_*)`` rows.

    ``history_through_tournament_id`` lets training include the known future
    rows needed to label the last tournament in ``tournament_ids``. This must be
    an actual tournament horizon, not a numeric-id lookahead, because tournament
    IDs can be sparse.
    """
    if not tournament_ids:
        return pd.DataFrame()

    history_max_tid = max(
        max(tournament_ids),
        history_through_tournament_id or max(tournament_ids),
    )

    div_expr = division_case_expr(models.Player.rank, DEFAULT_GRID)
    query = (
        sa.select(
            models.Player.id.label("player_id"),
            models.Player.user_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.tournament_id.label("tournament_id"),
            models.Player.rank.label("rank"),
            models.Player.is_newcomer.label("is_newcomer"),
            div_expr.label("div"),
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.Player.tournament_id <= history_max_tid,
            models.Player.is_substitution.is_(False),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Player.user_id, models.Player.role, models.Tournament.id)
    )
    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return df

    df["tournament_id"] = df["tournament_id"].astype(int)
    df = df.sort_values(["user_id", "role", "tournament_id"]).reset_index(drop=True)

    grouped = df.groupby(["user_id", "role"], sort=False)
    df["prior_div"] = grouped["div"].shift(1)
    df["next_tournament_div"] = grouped["div"].shift(-1)
    df["tournaments_played"] = grouped.cumcount() + 1

    # tournaments_at_current_div: streak of consecutive tournaments with same div.
    same_as_prior = df["div"] == df["prior_div"]
    streak_id = (~same_as_prior.fillna(False)).cumsum()
    df["tournaments_at_current_div"] = df.groupby(["user_id", "role", streak_id]).cumcount() + 1

    return df


async def _performance_features(
    session: AsyncSession,
    tournament_ids: typing.Sequence[int],
) -> pd.DataFrame:
    """Return already-materialised Performance v2 rows for shift enrichment."""
    if not tournament_ids:
        return pd.DataFrame()

    query = sa.select(
        models.AnalyticsPerformance.player_id.label("player_id"),
        models.AnalyticsPerformance.tournament_id.label("tournament_id"),
        models.AnalyticsPerformance.raw_value.label("performance_v2_raw"),
        models.AnalyticsPerformance.confidence.label("performance_v2_confidence"),
        models.AnalyticsPerformance.local_residual.label("performance_v2_local_residual"),
        models.AnalyticsPerformance.local_zscore.label("performance_v2_local_zscore"),
        models.AnalyticsPerformance.local_percentile.label("performance_v2_local_percentile"),
        models.AnalyticsPerformance.local_reference_n.label("performance_v2_local_reference_n"),
    ).where(models.AnalyticsPerformance.tournament_id.in_(tournament_ids))
    result = await session.execute(query)
    return pd.DataFrame(result.mappings().all())


async def _linear_history_frame(
    session: AsyncSession,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    params = scope_cache_params(workspace_id=workspace_id, workspace_ids=workspace_ids)

    async def _build() -> pd.DataFrame:
        df = await get_data_frame(
            session,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        return compute_linear_metrics(df) if not df.empty else df

    return await get_or_build_dataframe("shift_linear_history", params, _build)


async def _openskill_shift_frame(
    session: AsyncSession,
    tournament_id: int,
    df_history: pd.DataFrame,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    params = {
        "tournament_id": int(tournament_id),
        **scope_cache_params(workspace_id=workspace_id, workspace_ids=workspace_ids),
    }

    async def _build() -> pd.DataFrame:
        shift_map, _ = await compute_openskill_shift_map(
            session,
            tournament_id,
            df_history,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        return pd.DataFrame(
            [
                {"player_id": int(player_id), "os_shift": float(shift)}
                for player_id, shift in shift_map.items()
            ],
            columns=["player_id", "os_shift"],
        )

    return await get_or_build_dataframe("shift_openskill_map", params, _build)


async def build_shift_feature_frame(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    history_through_tournament_id: int | None = None,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return the per-(player, tournament) shift training frame.

    For each tournament in ``tournament_ids``:
    - compute v1 OpenSkill shift map (``compute_openskill_shift_map``)
    - compute tournament-level feature aggregates
    - join the player rank chronology to produce ``prior_div``,
      ``next_tournament_div``, ``tournaments_played``,
      ``tournaments_at_current_div``
    """
    tournament_ids = sorted({int(t) for t in tournament_ids})
    if not tournament_ids:
        return pd.DataFrame()

    rank_history = await _player_rank_history(
        session,
        tournament_ids,
        history_through_tournament_id=history_through_tournament_id,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if rank_history.empty:
        return pd.DataFrame()

    performance_features = await _performance_features(session, tournament_ids)
    df_history = await _linear_history_frame(
        session,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if df_history.empty:
        return pd.DataFrame()

    all_frames: list[pd.DataFrame] = []
    for tid in tournament_ids:
        tournament_features = await build_tournament_feature_frame(
            session,
            tid,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        if tournament_features.empty:
            continue

        # ``get_data_frame`` takes no range — it loads every analytics row;
        # ``compute_openskill_shift_map`` slices internally via ``tournament_id``.
        try:
            shift_frame = await _openskill_shift_frame(
                session,
                tid,
                df_history,
                workspace_id=workspace_id,
                workspace_ids=workspace_ids,
            )
            shift_map = {
                int(row.player_id): float(row.os_shift)
                for row in shift_frame.itertuples(index=False)
            }
        except Exception:
            logger.exception(
                "Failed to compute OpenSkill shift map for tournament_id=%d",
                tid,
            )
            shift_map = {}

        ranks_t = rank_history[rank_history["tournament_id"] == tid]
        merged = tournament_features.merge(
            ranks_t[
                [
                    "player_id",
                    "prior_div",
                    "next_tournament_div",
                    "tournaments_played",
                    "tournaments_at_current_div",
                    "div",
                ]
            ],
            on="player_id",
            how="left",
        )
        linear_t = df_history[df_history["tournament_id"] == tid][
            [
                "player_id",
                "linear_stable_shift",
                "linear_trend_shift",
                "confidence",
                "effective_evidence",
                "sample_tournaments",
                "sample_matches",
            ]
        ].rename(
            columns={
                "confidence": "linear_confidence",
                "effective_evidence": "linear_effective_evidence",
                "sample_tournaments": "linear_sample_tournaments",
                "sample_matches": "linear_sample_matches",
            }
        )
        merged = merged.merge(linear_t, on="player_id", how="left")
        merged["current_div"] = merged["div"]
        merged["os_shift"] = (
            merged["player_id"]
            .map(lambda pid, lookup=shift_map: lookup.get(int(pid)))
            .astype(float)
        )
        if not performance_features.empty:
            merged = merged.merge(
                performance_features[performance_features["tournament_id"] == tid],
                on=["player_id", "tournament_id"],
                how="left",
            )
        merged["confidence_v1"] = 0.0  # filled if/when v1 shift rows are joined
        for column in (
            "performance_v2_raw",
            "performance_v2_confidence",
            "performance_v2_local_residual",
            "performance_v2_local_zscore",
            "performance_v2_local_percentile",
            "performance_v2_local_reference_n",
            "linear_stable_shift",
            "linear_trend_shift",
            "linear_confidence",
            "linear_effective_evidence",
            "linear_sample_tournaments",
            "linear_sample_matches",
        ):
            if column not in merged.columns:
                merged[column] = 0.0
            merged[column] = merged[column].fillna(0.0)
        all_frames.append(merged)

    if not all_frames:
        return pd.DataFrame()
    df = pd.concat(all_frames, ignore_index=True)
    # Replace inf/-inf so LightGBM doesn't complain.
    df = df.replace([np.inf, -np.inf], np.nan)
    return df
