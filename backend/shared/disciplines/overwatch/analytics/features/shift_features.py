"""Shift v2 feature columns.

Joins, per tournament:

- per-(player, tournament) tournament features (rates, mu features)
- the v1 OpenSkill shift map (``os_shift``)
- the v1 linear metrics as the conservative baseline
- per-player tournament chronology to derive ``prior_div``, ``tournaments_played``, ``tournaments_at_current_div``,
  ``next_tournament_div`` on the canonical Overwatch division scale
- per-player Performance v2 row (``raw_value``, ``confidence``) if already materialised
- raw match-log MVP dominance

The service loads the cache/history/OpenSkill frames and passes them in; this module owns the module SQL, the
canonical division chronology and the column construction. The result is the input to :func:`train_shift_v2` and
:meth:`ShiftModelV2.predict`.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.division_grid import DEFAULT_GRID
from shared.domain.analytics import PERFORMANCE_MODEL
from shared.services.division_grid.access import load_division_grids
from shared.services.workspace_scope import workspace_scope_filter

from ..canonical import assign_canonical_division

__all__ = (
    "assemble_shift_tournament_frame",
    "concat_shift_frames",
    "load_performance_features",
    "load_player_rank_history",
)


async def load_player_rank_history(
    session: AsyncSession,
    tournament_ids: typing.Sequence[int],
    *,
    history_through_tournament_id: int | None = None,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return ``(user_id, role, tournament_id, started_at, rank, div, prior_*, next_*)`` rows.

    Each player's chronology is tournament start order ``(coalesce(start_date, created_at), id)``: ids are not
    chronological. The history runs through the chronologically latest of ``tournament_ids`` and
    ``history_through_tournament_id``; the latter lets training include the known future rows needed to label the
    last tournament in ``tournament_ids``.
    """
    if not tournament_ids:
        return pd.DataFrame()

    chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
    horizon_ids = [*tournament_ids, *([history_through_tournament_id] if history_through_tournament_id else [])]
    horizon = (
        sa.select(chrono.label("started_at"), models.Tournament.id.label("tournament_id"))
        .where(models.Tournament.id.in_(horizon_ids))
        .order_by(chrono.desc(), models.Tournament.id.desc())
        .limit(1)
        .subquery("horizon")
    )

    query = (
        sa.select(
            models.Player.id.label("player_id"),
            models.WorkspaceMember.player_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.tournament_id.label("tournament_id"),
            chrono.label("started_at"),
            models.Player.rank.label("rank"),
            models.Player.is_newcomer.label("is_newcomer"),
            models.Tournament.division_grid_version_id.label("version_id"),
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .join(
            horizon,
            sa.tuple_(chrono, models.Tournament.id) <= sa.tuple_(horizon.c.started_at, horizon.c.tournament_id),
        )
        .where(
            models.Player.is_substitution.is_(False),
            models.Tournament.discipline == "overwatch",
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.WorkspaceMember.player_id, models.Player.role, models.Tournament.id)
    )
    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return df

    df["tournament_id"] = df["tournament_id"].astype(int)
    df = df.sort_values(["user_id", "role", "started_at", "tournament_id"]).reset_index(drop=True)

    # Resolve every player's division on the canonical OW grid so
    # div/prior_div/next_tournament_div are comparable across workspaces.
    grids = await load_division_grids(session, df["version_id"].dropna().unique())
    assign_canonical_division(df, grids, rank_col="rank")

    # Workspace grid size (division count) per row — shift v2 scales the
    # top-of-ladder output clamp by it so the same cap means the same real rank
    # distance regardless of granularity. Missing grid → the canonical grid's size.
    def _grid_div_count(version_id: object) -> int:
        if pd.isna(version_id):
            return DEFAULT_GRID.max_division
        grid = grids.get(int(version_id))
        return grid.max_division if grid is not None else DEFAULT_GRID.max_division

    df["grid_n_div"] = [_grid_div_count(v) for v in df["version_id"]]

    grouped = df.groupby(["user_id", "role"], sort=False)
    df["tournaments_played"] = grouped.cumcount() + 1

    # The division chronology runs over ranked rows only: an unranked tournament has no division (NaN div, prior/next
    # and streak) and does not break the link between the ranked tournaments around it.
    ranked = df[df["div"].notna()]
    by_role = ranked.groupby(["user_id", "role"], sort=False)
    df["prior_div"] = by_role["div"].shift(1)
    df["next_tournament_div"] = by_role["div"].shift(-1)

    # tournaments_at_current_div: streak of consecutive ranked tournaments with same div.
    streak_id = (ranked["div"] != df.loc[ranked.index, "prior_div"]).cumsum()
    df["tournaments_at_current_div"] = ranked.groupby(["user_id", "role", streak_id]).cumcount() + 1

    return df


async def load_performance_features(
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
    )
    query = (
        query.join(models.Tournament, models.Tournament.id == models.AnalyticsPerformance.tournament_id)
        .join(models.AnalyticsAlgorithm, models.AnalyticsAlgorithm.id == models.AnalyticsPerformance.algorithm_id)
        .where(
            models.AnalyticsPerformance.tournament_id.in_(tournament_ids),
            models.Tournament.discipline == "overwatch",
            models.AnalyticsAlgorithm.name == PERFORMANCE_MODEL.algorithm_name,
        )
    )
    result = await session.execute(query)
    return pd.DataFrame(result.mappings().all())


def assemble_shift_tournament_frame(
    tournament_id: int,
    *,
    tournament_features: pd.DataFrame,
    rank_history: pd.DataFrame,
    history: pd.DataFrame,
    shift_map: Mapping[int, tuple[float, float]],
    performance_features: pd.DataFrame,
    dominance: pd.DataFrame,
) -> pd.DataFrame:
    """One tournament's shift frame from its already-loaded parts.

    ``history`` is the v1 linear-metrics frame, ``shift_map`` the v1 OpenSkill ``{player_id: (os_shift, os_shift_sd)}``
    map (empty when the replay failed), ``dominance`` the per-player :func:`compute_mvp_dominance` frame. The sd columns
    (``linear_shift_sd``, ``os_shift_sd``) stay NaN where unknown: an sd of 0 would claim certainty.
    """
    ranks_t = rank_history[rank_history["tournament_id"] == tournament_id]
    merged = tournament_features.merge(
        ranks_t[
            [
                "player_id",
                "prior_div",
                "next_tournament_div",
                "tournaments_played",
                "tournaments_at_current_div",
                "div",
                "grid_n_div",
            ]
        ],
        on="player_id",
        how="left",
    )
    linear_t = history[history["tournament_id"] == tournament_id][
        [
            "player_id",
            "linear_stable_shift",
            "linear_trend_shift",
            "linear_shift_sd",
            "effective_evidence",
            "sample_tournaments",
            "sample_matches",
            "overall_position",
            "team_count",
        ]
    ].rename(
        columns={
            "effective_evidence": "linear_effective_evidence",
            "sample_tournaments": "linear_sample_tournaments",
            "sample_matches": "linear_sample_matches",
        }
    )
    merged = merged.merge(linear_t, on="player_id", how="left")
    merged["current_div"] = merged["div"]
    os_pairs = merged["player_id"].map(lambda pid, lookup=shift_map: lookup.get(int(pid), (np.nan, np.nan)))
    merged["os_shift"] = os_pairs.map(lambda pair: pair[0]).astype(float)
    merged["os_shift_sd"] = os_pairs.map(lambda pair: pair[1]).astype(float)
    if not performance_features.empty:
        merged = merged.merge(
            performance_features[performance_features["tournament_id"] == tournament_id],
            on=["player_id", "tournament_id"],
            how="left",
        )
    # Raw match-log MVP dominance — a secondary individual-skill signal that
    # lifts a consistent scoreboard-topper the expectation-adjusted impact
    # under-credits. Neutral (0.5) where there is no match log.
    if not dominance.empty:
        merged = merged.merge(dominance, on="player_id", how="left")
    merged["mvp_dominance"] = pd.to_numeric(
        merged.get("mvp_dominance", pd.Series(index=merged.index, dtype=float)),
        errors="coerce",
    ).fillna(0.5)
    # Flag rows that actually carry a Performance v2 row BEFORE the fillna
    # below masks missing perf as 0.0 — the merit target trains only on these
    # (treating "no perf data" as "average performance" would poison it).
    merged["has_perf_v2"] = (
        merged["performance_v2_local_zscore"].notna()
        if "performance_v2_local_zscore" in merged.columns
        else pd.Series(False, index=merged.index)
    )
    for column in (
        "performance_v2_raw",
        "performance_v2_confidence",
        "performance_v2_local_residual",
        "performance_v2_local_zscore",
        "performance_v2_local_percentile",
        "performance_v2_local_reference_n",
        "linear_stable_shift",
        "linear_trend_shift",
        "linear_effective_evidence",
        "linear_sample_tournaments",
        "linear_sample_matches",
    ):
        if column not in merged.columns:
            merged[column] = 0.0
        merged[column] = merged[column].fillna(0.0)
    return merged


def concat_shift_frames(frames: typing.Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Stack the per-tournament frames; ``inf`` becomes NaN so LightGBM doesn't complain."""
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df.replace([np.inf, -np.inf], np.nan)
