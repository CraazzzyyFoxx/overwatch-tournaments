"""Impact-scoring baseline recompute (spec 2026-07-10).

``build_baseline_rows`` is the pure, unit-tested aggregator: it turns a
per-(match, user) stat-rate frame into ``StatBaseline`` row dicts. Everything
else here is IO — loading that frame from the DB and atomically replacing the
version's rows — and is exercised at rollout (see Task 10 runbook), not by
unit tests, since it needs a live database.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.impact import (
    BASELINE_MIN_MINUTES,
    EVENT_STATS,
    FORMULA_VERSION,
    IMPACT_WEIGHTS,
    RANK_BUCKETS,
)
from src import models
from src.core import enums

from . import service

__all__ = ("build_baseline_rows", "recompute")

logger = logging.getLogger(__name__)

_STAT_NAMES = tuple(IMPACT_WEIGHTS)


def build_baseline_rows(stats: pd.DataFrame) -> list[dict]:
    """Aggregate per-(match, user) stat rates into ``StatBaseline`` row dicts.

    ``stats`` columns: ``role`` (str, lowercase), ``rank`` (int), ``minutes``
    (float), ``has_killfeed`` (bool), and ``f"{stat}_rate"`` for every
    ``IMPACT_WEIGHTS`` key. Pure and DB-free.

    Rules: rows with ``minutes < BASELINE_MIN_MINUTES`` are dropped before
    anything else. Rank buckets are league-wide terciles (``numpy.quantile``
    on the filtered ``rank`` column) — the SAME two cut points are reused for
    every role, matching ``impact.BaselineSet.bucket_for`` (which is
    role-agnostic). Event stats (``EVENT_STATS``) are aggregated only over
    ``has_killfeed`` rows (a match with no kill-feed contributes nothing to
    those baselines, rather than dragging the mean toward zero). Every
    (role, stat) pair emits 4 rows: bucket ``-1`` (role-wide) plus one row per
    rank bucket ``0..RANK_BUCKETS-1``, even if a bucket has zero matching rows
    (mean/std default to 0.0 in that case).
    """
    df = stats[stats["minutes"] >= BASELINE_MIN_MINUTES].copy()
    if df.empty:
        return []

    ranks = df["rank"].to_numpy(dtype=float)
    bucket_bounds = [float(b) for b in np.quantile(ranks, [1 / 3, 2 / 3])]
    meta = {"bucket_bounds": bucket_bounds, "n": len(df)}

    def _bucket_for(rank: float) -> int:
        for i, bound in enumerate(bucket_bounds):
            if rank <= bound:
                return i
        return len(bucket_bounds)

    df["rank_bucket"] = df["rank"].map(_bucket_for)

    rows: list[dict] = []
    for role, role_df in df.groupby("role"):
        for stat in _STAT_NAMES:
            col = f"{stat}_rate"
            is_event = stat in EVENT_STATS
            base_df = role_df[role_df["has_killfeed"]] if is_event else role_df
            rows.append(_baseline_row(role, -1, stat, base_df[col], meta))
            for bucket in range(RANK_BUCKETS):
                bucket_df = role_df[role_df["rank_bucket"] == bucket]
                if is_event:
                    bucket_df = bucket_df[bucket_df["has_killfeed"]]
                rows.append(_baseline_row(role, bucket, stat, bucket_df[col], meta))
    return rows


def _baseline_row(role: str, rank_bucket: int, stat: str, series: pd.Series, meta: dict) -> dict:
    mean = float(series.mean()) if len(series) else 0.0
    if pd.isna(mean):
        mean = 0.0
    std = float(series.std(ddof=1)) if len(series) > 1 else 0.0
    if pd.isna(std):
        std = 0.0
    return {
        "role": role,
        "rank_bucket": rank_bucket,
        "stat": stat,
        "mean": mean,
        "std": std,
        "meta": dict(meta),
    }


async def _load_stats_frame(session: AsyncSession) -> pd.DataFrame:
    """Per-(match, user) rate frame for every historical stat row.

    UNTESTED here (needs a live DB) — verified at rollout, see Task 10
    runbook. Schema assumptions (flagged for rollout verification):

    * ``matches.statistics`` round-0 / hero-NULL rows are the per-match
      totals for the ``IMPACT_WEIGHTS`` stats + ``HeroTimePlayed``.
    * "Dominant role" per (match, user) = the ``overwatch.hero.type`` with
      the most summed round-0 per-hero ``HeroTimePlayed`` seconds (mirrors
      ``impact.dominant_roles`` — NOT ``tournament.player.role``, so it
      matches what Task 5 scores against). Ties are broken arbitrarily by
      ``row_number()`` (same non-determinism ``dominant_roles`` already has).
    * ``rank`` comes from the ``tournament.player`` row for that exact
      ``(team_id, user_id)`` pair (``user_id`` = ``workspace_member.player_id``,
      the auth-identity id also used as ``matches.statistics.user_id`` and
      ``matches.kill_feed.killer_id/victim_id``). If more than one ``Player``
      row exists for the same team+identity (e.g. a substitution edge case),
      the non-substitute / most-recent row wins — unverified against
      production data.
    * ``has_killfeed`` = the match has >=1 ``matches.kill_feed`` row.
    """
    stat_columns = [
        sa.func.max(models.MatchStatistics.value)
        .filter(models.MatchStatistics.name == enums.LogStatsName[name])
        .label(name)
        for name in _STAT_NAMES
    ]
    totals = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.user_id.label("user_id"),
            models.MatchStatistics.team_id.label("team_id"),
            sa.func.max(models.MatchStatistics.value)
            .filter(models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed)
            .label("seconds"),
            *stat_columns,
        )
        .where(models.MatchStatistics.round == 0, models.MatchStatistics.hero_id.is_(None))
        .group_by(models.MatchStatistics.match_id, models.MatchStatistics.user_id, models.MatchStatistics.team_id)
        .cte("impact_baseline_totals")
    )

    hero_playtime = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.user_id.label("user_id"),
            models.Hero.type.label("hero_type"),
            sa.func.sum(models.MatchStatistics.value).label("seconds"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Hero, models.Hero.id == models.MatchStatistics.hero_id)
        .where(
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_not(None),
            models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
        )
        .group_by(models.MatchStatistics.match_id, models.MatchStatistics.user_id, models.Hero.type)
        .cte("impact_baseline_hero_playtime")
    )
    hero_playtime_ranked = sa.select(
        hero_playtime.c.match_id,
        hero_playtime.c.user_id,
        hero_playtime.c.hero_type,
        sa.func.row_number()
        .over(
            partition_by=(hero_playtime.c.match_id, hero_playtime.c.user_id),
            order_by=hero_playtime.c.seconds.desc(),
        )
        .label("role_rank"),
    ).subquery("impact_baseline_hero_playtime_ranked")
    dominant_role = (
        sa.select(
            hero_playtime_ranked.c.match_id,
            hero_playtime_ranked.c.user_id,
            hero_playtime_ranked.c.hero_type,
        )
        .where(hero_playtime_ranked.c.role_rank == 1)
        .cte("impact_baseline_dominant_role")
    )

    roster_ranked = (
        sa.select(
            models.Player.team_id.label("team_id"),
            models.WorkspaceMember.player_id.label("user_id"),
            models.Player.rank.label("rank"),
            sa.func.row_number()
            .over(
                partition_by=(models.Player.team_id, models.WorkspaceMember.player_id),
                order_by=(models.Player.is_substitution.asc(), models.Player.id.desc()),
            )
            .label("roster_rank"),
        )
        .select_from(
            sa.join(
                models.Player, models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id
            )
        )
        .subquery("impact_baseline_roster_ranked")
    )
    roster = (
        sa.select(roster_ranked.c.team_id, roster_ranked.c.user_id, roster_ranked.c.rank)
        .where(roster_ranked.c.roster_rank == 1)
        .cte("impact_baseline_roster")
    )

    killfeed_matches = sa.select(models.MatchKillFeed.match_id).distinct().cte("impact_baseline_killfeed_matches")

    query = (
        sa.select(
            dominant_role.c.hero_type,
            roster.c.rank,
            totals.c.seconds,
            killfeed_matches.c.match_id.is_not(None).label("has_killfeed"),
            *[totals.c[name] for name in _STAT_NAMES],
        )
        .select_from(totals)
        .join(
            dominant_role,
            sa.and_(dominant_role.c.match_id == totals.c.match_id, dominant_role.c.user_id == totals.c.user_id),
        )
        .join(roster, sa.and_(roster.c.team_id == totals.c.team_id, roster.c.user_id == totals.c.user_id))
        .outerjoin(killfeed_matches, killfeed_matches.c.match_id == totals.c.match_id)
        .where(totals.c.seconds.is_not(None))
    )

    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return pd.DataFrame(columns=["role", "rank", "minutes", "has_killfeed", *(f"{s}_rate" for s in _STAT_NAMES)])

    df["minutes"] = df.pop("seconds").astype(float) / 60.0
    df["role"] = df.pop("hero_type").map(lambda t: str(getattr(t, "value", t)).lower())
    df["has_killfeed"] = df["has_killfeed"].fillna(False).astype(bool)
    df["rank"] = df["rank"].astype(int)

    # Exclude non-positive-minute rows before computing rates: dividing by
    # zero minutes yields inf/nan and raises a RuntimeWarning on every real
    # recompute() run. Safe — build_baseline_rows already drops everything
    # below BASELINE_MIN_MINUTES (> 0), so no currently-kept row is lost.
    df = df[df["minutes"] > 0].copy()

    # rate unit MUST match impact.py: rate = value / seconds * 600 (per-10-min).
    # seconds/600 == minutes/10, so value / (minutes/10) is the same rate.
    ten_minute_units = df["minutes"] / 10.0
    for name in _STAT_NAMES:
        value = df.pop(name).fillna(0.0).astype(float)
        df[f"{name}_rate"] = value / ten_minute_units

    return df


async def recompute(session: AsyncSession) -> int:
    """Recompute the active ``FORMULA_VERSION`` baselines and replace them atomically."""
    stats = await _load_stats_frame(session)
    rows = build_baseline_rows(stats)
    if not rows:
        raise RuntimeError("impact baseline recompute produced 0 rows; refusing to wipe existing baselines")

    await session.execute(sa.delete(models.StatBaseline).where(models.StatBaseline.formula_version == FORMULA_VERSION))
    session.add_all(
        models.StatBaseline(
            formula_version=FORMULA_VERSION,
            role=enums.HeroClass(row["role"].capitalize()),
            rank_bucket=row["rank_bucket"],
            stat=enums.LogStatsName[row["stat"]],
            mean=row["mean"],
            std=row["std"],
            meta=row["meta"],
        )
        for row in rows
    )
    await session.commit()
    await service.invalidate_cache()
    return len(rows)
