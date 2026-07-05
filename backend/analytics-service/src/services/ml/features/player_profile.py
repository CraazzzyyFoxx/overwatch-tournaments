"""Player-level feature loaders shared by anomaly detectors."""

from __future__ import annotations

import pandas as pd
import sqlalchemy as sa
from shared.core.enums import LogStatsName
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.workspace import workspace_filter

from .mvp_dominance import compute_mvp_dominance

__all__ = ("load_player_signal_profile",)


async def load_player_signal_profile(
    session: AsyncSession,
    tournament_id: int,
    *,
    history_depth: int = 5,
    workspace_id: int | None = None,
) -> pd.DataFrame:
    """Return current-tournament player rows plus recent personal histories."""
    base_query = (
        sa.select(
            models.AnalyticsPerformance.player_id.label("player_id"),
            models.AnalyticsPerformance.tournament_id.label("tournament_id"),
            models.AnalyticsPerformance.impact_score.label("impact_score"),
            models.AnalyticsPerformance.raw_value.label("raw_value"),
            models.AnalyticsPerformance.confidence.label("confidence"),
            models.AnalyticsPerformance.log_coverage.label("log_coverage"),
            models.AnalyticsPerformance.local_residual.label("local_residual"),
            models.AnalyticsPerformance.local_zscore.label("local_zscore"),
            models.AnalyticsPerformance.local_percentile.label("local_percentile"),
            models.AnalyticsPerformance.local_reference_n.label("local_reference_n"),
            models.Player.role.label("role"),
            models.Player.rank.label("rank"),
            models.WorkspaceMember.player_id.label("user_id"),
        )
        .join(models.Player, models.Player.id == models.AnalyticsPerformance.player_id)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.AnalyticsPerformance.tournament_id == tournament_id,
            *workspace_filter(workspace_id),
        )
    )
    base_df = pd.DataFrame((await session.execute(base_query)).mappings().all())
    if base_df.empty:
        return base_df

    user_ids = [int(u) for u in base_df["user_id"].unique().tolist() if u is not None]
    stats_query = (
        sa.select(
            models.MatchStatistics.user_id.label("user_id"),
            sa.func.coalesce(
                sa.func.avg(
                    sa.case(
                        (models.MatchStatistics.name == LogStatsName.KD, models.MatchStatistics.value)
                    )
                ),
                0.0,
            ).label("kd"),
            sa.func.coalesce(
                sa.func.avg(
                    sa.case(
                        (
                            models.MatchStatistics.name == LogStatsName.WeaponAccuracy,
                            models.MatchStatistics.value,
                        )
                    )
                ),
                0.0,
            ).label("weapon_accuracy"),
            sa.func.coalesce(
                sa.func.avg(
                    sa.case(
                        (
                            models.MatchStatistics.name == LogStatsName.FinalBlows,
                            models.MatchStatistics.value,
                        )
                    )
                ),
                0.0,
            ).label("final_blows_p10"),
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .where(
            models.Encounter.tournament_id == tournament_id,
            models.MatchStatistics.user_id.in_(user_ids),
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
        )
        .group_by(models.MatchStatistics.user_id)
    )
    stats_df = pd.DataFrame((await session.execute(stats_query)).mappings().all())
    if not stats_df.empty:
        for col in ("kd", "weapon_accuracy", "final_blows_p10"):
            stats_df[col] = pd.to_numeric(stats_df[col], errors="coerce").astype(float)
        base_df = base_df.merge(stats_df, on="user_id", how="left")
    else:
        base_df["kd"] = 0.0
        base_df["weapon_accuracy"] = 0.0
        base_df["final_blows_p10"] = 0.0

    # Raw match-log MVP dominance (separate from expectation-adjusted impact):
    # catches a consistent scoreboard-topper that impact under-credits.
    dominance_df = await compute_mvp_dominance(session, tournament_id)
    if not dominance_df.empty:
        base_df = base_df.merge(dominance_df, on="player_id", how="left")
    else:
        base_df["mvp_dominance"] = float("nan")
        base_df["mvp_matches"] = 0

    history_query = (
        sa.select(
            models.WorkspaceMember.player_id.label("user_id"),
            models.Player.role.label("role"),
            models.AnalyticsPerformance.tournament_id.label("tournament_id"),
            models.AnalyticsPerformance.raw_value.label("raw_value"),
            models.AnalyticsPerformance.local_residual.label("local_residual"),
            models.AnalyticsPerformance.local_zscore.label("local_zscore"),
        )
        .select_from(models.AnalyticsPerformance)
        .join(models.Player, models.Player.id == models.AnalyticsPerformance.player_id)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(
            models.AnalyticsPerformance.tournament_id <= tournament_id,
            models.AnalyticsPerformance.tournament_id >= max(1, tournament_id - history_depth),
            models.WorkspaceMember.player_id.in_(user_ids),
            *workspace_filter(workspace_id),
        )
        .order_by(
            models.WorkspaceMember.player_id,
            models.Player.role,
            models.AnalyticsPerformance.tournament_id,
        )
    )
    history_df = pd.DataFrame((await session.execute(history_query)).mappings().all())
    histories: dict[tuple[int, str], dict[str, list[float]]] = {}
    if not history_df.empty:
        for (uid, role), grp in history_df.groupby(["user_id", "role"]):
            histories[(int(uid), str(role))] = {
                "raw_value_history": [
                    float(v) for v in grp["raw_value"].tolist() if v is not None
                ],
                "local_residual_history": [
                    float(v) for v in grp["local_residual"].tolist() if v is not None
                ],
                "local_zscore_history": [
                    float(v) for v in grp["local_zscore"].tolist() if v is not None
                ],
            }

    def _history(row: pd.Series, key: str) -> list[float]:
        return histories.get((int(row["user_id"]), str(row["role"])), {}).get(
            key,
            [float(row[key.replace("_history", "")])],
        )

    for key in (
        "raw_value_history",
        "local_residual_history",
        "local_zscore_history",
    ):
        base_df[key] = base_df.apply(lambda row, key=key: _history(row, key), axis=1)

    return base_df
