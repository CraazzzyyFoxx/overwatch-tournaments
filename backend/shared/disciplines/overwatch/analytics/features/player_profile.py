"""Player-level feature loaders shared by anomaly detectors."""

from __future__ import annotations

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import LogStatsName
from shared.domain.analytics import PERFORMANCE_MODEL
from shared.repository.stats_queries import player_facts
from shared.services.workspace_scope import workspace_filter

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
        .join(models.AnalyticsAlgorithm, models.AnalyticsAlgorithm.id == models.AnalyticsPerformance.algorithm_id)
        .where(
            models.AnalyticsPerformance.tournament_id == tournament_id,
            models.Tournament.discipline == "overwatch",
            models.AnalyticsAlgorithm.name == PERFORMANCE_MODEL.algorithm_name,
            *workspace_filter(workspace_id),
        )
    )
    base_df = pd.DataFrame((await session.execute(base_query)).mappings().all())
    if base_df.empty:
        return base_df

    user_ids = [int(u) for u in base_df["user_id"].unique().tolist() if u is not None]
    facts = player_facts(discipline="overwatch")
    stats_query = (
        sa.select(
            facts.c.player_id.label("user_id"),
            sa.func.coalesce(
                sa.func.avg(sa.case((facts.c.stat_code == LogStatsName.KD.value, facts.c.value))),
                0.0,
            ).label("kd"),
            sa.func.coalesce(
                sa.func.avg(
                    sa.case(
                        (
                            facts.c.stat_code == LogStatsName.WeaponAccuracy.value,
                            facts.c.value,
                        )
                    )
                ),
                0.0,
            ).label("weapon_accuracy"),
            sa.func.coalesce(
                sa.func.avg(
                    sa.case(
                        (
                            facts.c.stat_code == LogStatsName.FinalBlows.value,
                            facts.c.value,
                        )
                    )
                ),
                0.0,
            ).label("final_blows_p10"),
        )
        .select_from(facts)
        .where(
            facts.c.tournament_id == tournament_id,
            facts.c.player_id.in_(user_ids),
            facts.c.segment == 0,
            facts.c.entity_id.is_(None),
        )
        .group_by(facts.c.player_id)
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

    # The window is the evaluated tournament plus the ``history_depth`` tournaments before it in the same scope, by
    # chronology ``(coalesce(start_date, created_at), id)``: ids are global and not chronological. Like the id range it
    # replaces, it counts every tournament of the scope, hidden ones included.
    chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
    evaluated_key = (
        await session.execute(sa.select(chrono, models.Tournament.id).where(models.Tournament.id == tournament_id))
    ).one()
    window_ids = (
        await session.scalars(
            sa.select(models.Tournament.id)
            .where(
                sa.tuple_(chrono, models.Tournament.id) <= sa.tuple_(*evaluated_key),
                models.Tournament.discipline == "overwatch",
                *workspace_filter(workspace_id),
            )
            .order_by(chrono.desc(), models.Tournament.id.desc())
            .limit(history_depth + 1)
        )
    ).all()
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
        .join(models.AnalyticsAlgorithm, models.AnalyticsAlgorithm.id == models.AnalyticsPerformance.algorithm_id)
        .where(
            models.Tournament.discipline == "overwatch",
            models.AnalyticsAlgorithm.name == PERFORMANCE_MODEL.algorithm_name,
            models.AnalyticsPerformance.tournament_id.in_(window_ids),
            models.WorkspaceMember.player_id.in_(user_ids),
            *workspace_filter(workspace_id),
        )
        .order_by(
            models.WorkspaceMember.player_id,
            models.Player.role,
            chrono,
            models.AnalyticsPerformance.tournament_id,
        )
    )
    history_df = pd.DataFrame((await session.execute(history_query)).mappings().all())
    histories: dict[tuple[int, str], dict[str, list[float]]] = {}
    if not history_df.empty:
        for (uid, role), grp in history_df.groupby(["user_id", "role"]):
            histories[(int(uid), str(role))] = {
                "raw_value_history": [float(v) for v in grp["raw_value"].tolist() if v is not None],
                "local_residual_history": [float(v) for v in grp["local_residual"].tolist() if v is not None],
                "local_zscore_history": [float(v) for v in grp["local_zscore"].tolist() if v is not None],
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
