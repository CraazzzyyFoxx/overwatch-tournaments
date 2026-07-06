"""Standings v2 — pairwise encounter feature builder.

For every historical ``Encounter`` we want a feature row with home/away
strength summaries plus the realised label ``home_won``. The features are
re-derived from the lighter-weight ``extract_encounter_features`` extractor
and enriched with OpenSkill ``mu`` snapshots and per-team mean ``Performance v2
raw_value`` (when available).
"""

from __future__ import annotations

import typing

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.workspace import workspace_scope_filter

from .cache import get_or_build_dataframe, scope_cache_params
from .extractors import extract_encounter_features
from .opponent_strength import snapshot_pre_encounter_team_mu

__all__ = ("build_standings_training_frame",)


async def _h2h_history(
    session: AsyncSession,
    tournament_ids: typing.Sequence[int],
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    ids = tuple(sorted(int(t) for t in tournament_ids))
    params = {
        "tournament_ids": ids,
        **scope_cache_params(workspace_id=workspace_id, workspace_ids=workspace_ids),
    }

    async def _build() -> pd.DataFrame:
        return await _h2h_history_uncached(
            session,
            ids,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )

    return await get_or_build_dataframe("standings_h2h_history", params, _build)


async def _h2h_history_uncached(
    session: AsyncSession,
    tournament_ids: typing.Sequence[int],
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Compute head-to-head winrate and days-since-last-meet per encounter.

    For each encounter we look at all *prior* encounters between the same two
    teams (within ``tournament_ids``). ``h2h_winrate`` is the fraction of
    those that the current home team won historically; ``days_since_last_meet``
    is the number of tournaments since they last met (``NaN`` for first meet).
    """
    if not tournament_ids:
        return pd.DataFrame()

    # Pull every encounter from tournaments up to and including the most
    # recent target id — not just ``tournament_ids``. We need the historical
    # head-to-head record to compute a meaningful ``h2h_winrate`` for the
    # encounters being predicted; restricting to ``tournament_ids`` would
    # make the metric blind to prior meetings.
    max_tid = max(tournament_ids)
    query = (
        sa.select(
            models.Encounter.id.label("encounter_id"),
            models.Encounter.tournament_id.label("tournament_id"),
            models.Encounter.home_team_id.label("home_team_id"),
            models.Encounter.away_team_id.label("away_team_id"),
            models.Encounter.home_score.label("home_score"),
            models.Encounter.away_score.label("away_score"),
        )
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.Encounter.tournament_id <= max_tid,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Encounter.tournament_id, models.Encounter.id)
    )
    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return df

    def _pair_key(row: pd.Series) -> tuple[int, int]:
        a, b = int(row["home_team_id"] or 0), int(row["away_team_id"] or 0)
        return (a, b) if a <= b else (b, a)

    # NOTE: column name must NOT start with ``_`` — :meth:`pd.DataFrame.itertuples`
    # uses :class:`collections.namedtuple` which renames underscore-prefixed
    # attributes to positional ``_<n>``, making them inaccessible by name.
    df["pair_key"] = df.apply(_pair_key, axis=1)

    h2h_rows: list[dict[str, typing.Any]] = []
    seen: dict[tuple[int, int], list[dict[str, typing.Any]]] = {}
    for row in df.itertuples(index=False):
        pair = row.pair_key
        history = seen.get(pair, [])
        prior_home_wins = sum(
            1
            for h in history
            if h.get("home_team_id") == row.home_team_id and (h.get("home_score") or 0) > (h.get("away_score") or 0)
        ) + sum(
            1
            for h in history
            if h.get("away_team_id") == row.home_team_id and (h.get("away_score") or 0) > (h.get("home_score") or 0)
        )
        played = len(history)
        h2h_winrate = (prior_home_wins / played) if played > 0 else 0.5
        days_since = (
            int(row.tournament_id - history[-1]["tournament_id"])  # type: ignore[index]
            if history
            else None
        )
        h2h_rows.append(
            {
                "encounter_id": row.encounter_id,
                "h2h_winrate": float(h2h_winrate),
                "days_since_last_meet": float(days_since) if days_since is not None else np.nan,
            }
        )
        history.append(
            {
                "tournament_id": row.tournament_id,
                "home_team_id": row.home_team_id,
                "away_team_id": row.away_team_id,
                "home_score": row.home_score,
                "away_score": row.away_score,
            }
        )
        seen[pair] = history

    return pd.DataFrame(h2h_rows)


async def _team_performance_mean(
    session: AsyncSession,
    tournament_ids: typing.Sequence[int],
) -> pd.DataFrame:
    """Return ``(tournament_id, team_id, avg_perf)`` from ``analytics.performance``.

    Used to enrich the win-prob features. Returns empty DataFrame if v2
    Performance has not been materialised yet.
    """
    if not tournament_ids:
        return pd.DataFrame()
    query = (
        sa.select(
            models.AnalyticsPerformance.tournament_id.label("tournament_id"),
            models.Player.team_id.label("team_id"),
            sa.func.avg(models.AnalyticsPerformance.raw_value).label("avg_perf"),
        )
        .join(
            models.Player,
            models.Player.id == models.AnalyticsPerformance.player_id,
        )
        .where(models.AnalyticsPerformance.tournament_id.in_(tournament_ids))
        .group_by(
            models.AnalyticsPerformance.tournament_id,
            models.Player.team_id,
        )
    )
    result = await session.execute(query)
    return pd.DataFrame(result.mappings().all())


async def build_standings_training_frame(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return one row per historical encounter with ML features + ``home_won`` label."""
    tournament_ids = sorted({int(t) for t in tournament_ids})
    if not tournament_ids:
        return pd.DataFrame()

    encounters = await extract_encounter_features(
        session,
        tournament_ids,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if encounters.empty:
        return encounters

    h2h = await _h2h_history(
        session,
        tournament_ids,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    perf = await _team_performance_mean(session, tournament_ids)

    # OpenSkill mu snapshots — per tournament so the look-back window stays scoped.
    mu_snapshots: list[pd.DataFrame] = []
    for tid in tournament_ids:
        snap = await snapshot_pre_encounter_team_mu(
            session,
            tid,
            workspace_id=workspace_id,
            workspace_ids=workspace_ids,
        )
        if not snap.empty:
            mu_snapshots.append(snap)
    mu_df = (
        pd.concat(mu_snapshots, ignore_index=True)
        if mu_snapshots
        else pd.DataFrame(columns=["encounter_id", "team_id", "avg_mu", "max_mu", "min_mu", "std_mu"])
    )

    df = encounters.merge(
        mu_df.rename(columns={"avg_mu": "home_avg_mu"})[["encounter_id", "team_id", "home_avg_mu"]],
        left_on=["encounter_id", "home_team_id"],
        right_on=["encounter_id", "team_id"],
        how="left",
    ).drop(columns=["team_id"])
    df = df.merge(
        mu_df.rename(columns={"avg_mu": "away_avg_mu"})[["encounter_id", "team_id", "away_avg_mu"]],
        left_on=["encounter_id", "away_team_id"],
        right_on=["encounter_id", "team_id"],
        how="left",
    ).drop(columns=["team_id"])
    df["mu_gap"] = df["home_avg_mu"] - df["away_avg_mu"]

    if not h2h.empty:
        df = df.merge(h2h, on="encounter_id", how="left")
    else:
        df["h2h_winrate"] = 0.5
        df["days_since_last_meet"] = np.nan

    if not perf.empty:
        perf_h = perf.rename(columns={"team_id": "home_team_id", "avg_perf": "home_avg_perf"})
        perf_a = perf.rename(columns={"team_id": "away_team_id", "avg_perf": "away_avg_perf"})
        df = df.merge(perf_h, on=["tournament_id", "home_team_id"], how="left")
        df = df.merge(perf_a, on=["tournament_id", "away_team_id"], how="left")
        df["perf_gap"] = df["home_avg_perf"].fillna(0) - df["away_avg_perf"].fillna(0)
    else:
        df["home_avg_perf"] = 0.0
        df["away_avg_perf"] = 0.0
        df["perf_gap"] = 0.0

    # Coerce numeric columns from object → float64. PostgreSQL returns
    # ``AVG(...)`` / ``STDDEV_SAMP(...)`` as ``Decimal`` which pandas keeps as
    # ``object`` dtype. XGBoost / LightGBM both reject ``object`` columns.
    numeric_cols = (
        "home_avg_rank",
        "away_avg_rank",
        "home_std_rank",
        "away_std_rank",
        "home_avg_mu",
        "away_avg_mu",
        "mu_gap",
        "home_avg_perf",
        "away_avg_perf",
        "perf_gap",
        "h2h_winrate",
        "days_since_last_meet",
        "home_score",
        "away_score",
        "home_won",
    )
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    return df.replace([np.inf, -np.inf], np.nan)
