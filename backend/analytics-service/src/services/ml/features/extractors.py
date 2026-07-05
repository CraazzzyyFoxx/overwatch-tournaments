"""Feature extractors: SQL → pandas DataFrames at four granularities.

All extractors pivot ``matches.statistics`` rows from long-format (one row per
``(user, match, round, hero, stat_name)``) into wide-format DataFrames using a
single SQL query with ``CASE`` expressions per stat. This keeps the database
round-trip cost to one query per granularity regardless of how many stats are
materialised.

Granularities provided in Phase 1:

- :func:`extract_match_features` — one row per ``(player_id, match_id)``,
  aggregated over ``round = 0`` and ``hero_id IS NULL`` rows (these are
  already-summed per-match totals produced upstream by the parser).
- :func:`extract_tournament_features` — roll-up of match features to
  ``(player_id, tournament_id)`` weighted by ``hero_time_played``.
- :func:`extract_encounter_features` — pairwise team matchup vector per
  ``Encounter`` (input to the Stage-A win-probability classifier in Phase 3).

Round-level and per-hero granularities are intentionally separate from the
match/tournament feature frames. The round-level extractor below exists for
the ``throw`` detector, which needs within-encounter changepoints rather than
whole-tournament aggregates.
"""

from __future__ import annotations

import typing

import numpy as np
import pandas as pd
import sqlalchemy as sa
from shared.core.enums import LogStatsName
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.workspace import workspace_scope_filter

__all__ = (
    "STAT_COLUMNS",
    "RATE_COLUMNS",
    "extract_match_features",
    "extract_tournament_features",
    "extract_encounter_features",
    "extract_round_residuals",
)


# ---------------------------------------------------------------------------
# Stat catalogue
# ---------------------------------------------------------------------------

# (LogStatsName, snake_case column name in the output DataFrame)
# Listed in a stable order so feature vectors are reproducible.
STAT_COLUMNS: tuple[tuple[LogStatsName, str], ...] = (
    (LogStatsName.Eliminations, "eliminations"),
    (LogStatsName.FinalBlows, "final_blows"),
    (LogStatsName.Deaths, "deaths"),
    (LogStatsName.AllDamageDealt, "all_damage"),
    (LogStatsName.BarrierDamageDealt, "barrier_damage"),
    (LogStatsName.HeroDamageDealt, "hero_damage"),
    (LogStatsName.HealingDealt, "healing"),
    (LogStatsName.HealingReceived, "healing_received"),
    (LogStatsName.SelfHealing, "self_healing"),
    (LogStatsName.DamageTaken, "damage_taken"),
    (LogStatsName.DamageBlocked, "damage_blocked"),
    (LogStatsName.DefensiveAssists, "defensive_assists"),
    (LogStatsName.OffensiveAssists, "offensive_assists"),
    (LogStatsName.UltimatesEarned, "ults_earned"),
    (LogStatsName.UltimatesUsed, "ults_used"),
    (LogStatsName.MultikillBest, "multikill_best"),
    (LogStatsName.Multikills, "multikills"),
    (LogStatsName.SoloKills, "solo_kills"),
    (LogStatsName.ObjectiveKills, "objective_kills"),
    (LogStatsName.EnvironmentalKills, "environmental_kills"),
    (LogStatsName.EnvironmentalDeaths, "environmental_deaths"),
    (LogStatsName.CriticalHits, "critical_hits"),
    (LogStatsName.CriticalHitAccuracy, "critical_hit_accuracy"),
    (LogStatsName.ScopedAccuracy, "scoped_accuracy"),
    (LogStatsName.ScopedCriticalHitAccuracy, "scoped_critical_hit_accuracy"),
    (LogStatsName.ScopedCriticalHitKills, "scoped_critical_hit_kills"),
    (LogStatsName.ShotsFired, "shots_fired"),
    (LogStatsName.ShotsHit, "shots_hit"),
    (LogStatsName.ShotsMissed, "shots_missed"),
    (LogStatsName.WeaponAccuracy, "weapon_accuracy"),
    (LogStatsName.HeroTimePlayed, "hero_time_played"),
    # Pre-computed derived stats (kept as features, not as residual targets).
    (LogStatsName.Performance, "performance"),
    (LogStatsName.PerformancePoints, "performance_points"),
    (LogStatsName.KD, "kd"),
    (LogStatsName.KDA, "kda"),
    (LogStatsName.DamageDelta, "damage_delta"),
)


# Columns that should be normalised by ``hero_time_played / 600`` to produce
# per-10-min rate columns (``<col>_p10``). Accuracies / KD / KDA / multikill
# bests are intensive ratios already and stay as-is.
RATE_COLUMNS: tuple[str, ...] = (
    "eliminations",
    "final_blows",
    "deaths",
    "all_damage",
    "barrier_damage",
    "hero_damage",
    "healing",
    "healing_received",
    "self_healing",
    "damage_taken",
    "damage_blocked",
    "defensive_assists",
    "offensive_assists",
    "ults_earned",
    "ults_used",
    "multikills",
    "solo_kills",
    "objective_kills",
    "environmental_kills",
    "environmental_deaths",
    "critical_hits",
    "shots_fired",
    "shots_hit",
    "shots_missed",
    "damage_delta",
)


def _stat_col(stat: LogStatsName, column_name: str) -> sa.Label[typing.Any]:
    """Build a ``MAX(CASE WHEN name = X THEN value END) AS column_name`` expression.

    Using ``MAX`` rather than ``SUM`` because each ``(user, match, round=0,
    hero_id NULL, stat_name)`` row is unique in the source table; ``MAX`` is
    equivalent to picking the single row and avoids accidental duplication.
    """
    return sa.func.max(
        sa.case((models.MatchStatistics.name == stat, models.MatchStatistics.value))
    ).label(column_name)


# ---------------------------------------------------------------------------
# Match-level extractor
# ---------------------------------------------------------------------------


async def extract_match_features(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return per-(player, match) feature DataFrame for the given tournaments.

    Rows in the source ``matches.statistics`` table with ``round = 0`` and
    ``hero_id IS NULL`` are already-aggregated per-match totals (one row per
    ``(user, match, stat_name)``). The pivot below turns one such row-set per
    match into a single wide row with one column per stat.

    Output columns (always present, NaN if missing):

    - **Identity**: ``tournament_id``, ``encounter_id``, ``match_id``,
      ``player_id``, ``user_id``, ``team_id``, ``home_team_id``, ``away_team_id``.
    - **Player context**: ``role``, ``rank``, ``is_newcomer``, ``is_home`` (bool).
    - **Match context**: ``home_score``, ``away_score``, ``score_delta``, ``won``,
      ``map_id``, ``time`` (seconds).
    - **Raw stats** (one column per :data:`STAT_COLUMNS` entry).
    - **Per-10-min rates** (``<col>_p10`` for each entry in :data:`RATE_COLUMNS`).

    Workspace filtering: when ``workspace_id`` is provided, only matches whose
    tournament belongs to that workspace are returned.
    """
    tournament_ids = list(tournament_ids)
    if not tournament_ids:
        return pd.DataFrame()

    stat_columns = [_stat_col(stat, name) for stat, name in STAT_COLUMNS]

    query = (
        sa.select(
            models.Tournament.id.label("tournament_id"),
            models.Encounter.id.label("encounter_id"),
            models.Match.id.label("match_id"),
            models.Match.map_id.label("map_id"),
            models.Match.home_team_id.label("home_team_id"),
            models.Match.away_team_id.label("away_team_id"),
            models.Match.home_score.label("home_score"),
            models.Match.away_score.label("away_score"),
            models.Match.time.label("match_time"),
            models.MatchStatistics.user_id.label("user_id"),
            models.MatchStatistics.team_id.label("team_id"),
            models.Player.id.label("player_id"),
            models.Player.role.label("role"),
            models.Player.rank.label("rank"),
            models.Player.is_newcomer.label("is_newcomer"),
            *stat_columns,
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == models.MatchStatistics.team_id,
                models.Player.tournament_id == models.Tournament.id,
            ),
        )
        .join(
            models.WorkspaceMember,
            sa.and_(
                models.WorkspaceMember.id == models.Player.workspace_member_id,
                models.WorkspaceMember.player_id == models.MatchStatistics.user_id,
            ),
        )
        .where(
            models.Tournament.id.in_(tournament_ids),
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
            models.Player.is_substitution.is_(False),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .group_by(
            models.Tournament.id,
            models.Encounter.id,
            models.Match.id,
            models.Match.map_id,
            models.Match.home_team_id,
            models.Match.away_team_id,
            models.Match.home_score,
            models.Match.away_score,
            models.Match.time,
            models.MatchStatistics.user_id,
            models.MatchStatistics.team_id,
            models.Player.id,
            models.Player.role,
            models.Player.rank,
            models.Player.is_newcomer,
        )
    )

    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return df

    # ---- derived columns ----
    df["is_home"] = df["team_id"] == df["home_team_id"]
    df["score_delta"] = df.apply(
        lambda r: (r["home_score"] - r["away_score"]) if r["is_home"] else (r["away_score"] - r["home_score"]),
        axis=1,
    )
    df["won"] = (df["score_delta"] > 0).astype(int)

    # Per-10-min rates: htp in seconds → divide by 600 to get per-10-min.
    # Guard against zero / NaN htp by mapping zero to NaN so the rate becomes NaN
    # (preferable to ``inf`` for downstream LightGBM training).
    htp_minutes = df["hero_time_played"].astype(float).replace(0, np.nan) / 600.0
    for col in RATE_COLUMNS:
        if col in df.columns:
            df[f"{col}_p10"] = df[col].astype(float) / htp_minutes

    # Ult economy: used / earned. NaN-safe.
    if "ults_earned" in df.columns and "ults_used" in df.columns:
        denom = df["ults_earned"].astype(float).replace(0, np.nan)
        df["ult_economy"] = df["ults_used"].astype(float) / denom

    return df


# ---------------------------------------------------------------------------
# Tournament-level extractor (roll-up of match features)
# ---------------------------------------------------------------------------


# Columns aggregated by weighted mean (weights = hero_time_played).
_WEIGHTED_MEAN_COLS = tuple(f"{c}_p10" for c in RATE_COLUMNS) + (
    "weapon_accuracy",
    "critical_hit_accuracy",
    "scoped_accuracy",
    "scoped_critical_hit_accuracy",
    "ult_economy",
    "performance_points",
    "performance",
    "kd",
    "kda",
)

# Columns summed across the tournament.
_SUM_COLS = (
    "won",
    "home_score",
    "away_score",
)


async def extract_tournament_features(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Aggregate per-match features into per-(player, tournament) rows.

    Aggregation rules:

    - Rate / accuracy / derived stats — **weighted mean** (weight =
      ``hero_time_played``).
    - Score / win counters — **sum**.
    - Player context (``role``, ``rank``, ``is_newcomer``) — **first**.

    Returns columns suitable as features for the Performance v2 LGBM model.
    """
    df = await extract_match_features(
        session,
        tournament_ids,
        workspace_id=workspace_id,
        workspace_ids=workspace_ids,
    )
    if df.empty:
        return df

    # Build weight column once. NaN htp → 0 weight → row contributes nothing.
    df["_weight"] = df["hero_time_played"].astype(float).fillna(0.0)

    by = ["tournament_id", "player_id", "user_id", "team_id"]
    grouped = df.groupby(by, sort=False, dropna=False)

    out_rows = []
    for keys, group in grouped:
        tournament_id, player_id, user_id, team_id = keys
        weights = group["_weight"].to_numpy()

        row: dict[str, typing.Any] = {
            "tournament_id": tournament_id,
            "player_id": player_id,
            "user_id": user_id,
            "team_id": team_id,
            "role": group["role"].iloc[0],
            "rank": group["rank"].iloc[0],
            "is_newcomer": group["is_newcomer"].iloc[0],
            "match_count": int(len(group)),
            "hero_time_played_total": float(group["hero_time_played"].fillna(0).sum()),
            "log_coverage": float((group["hero_time_played"].fillna(0) > 0).mean()),
        }

        for col in _WEIGHTED_MEAN_COLS:
            if col not in group.columns:
                continue
            values = group[col].astype(float).to_numpy()
            mask = ~np.isnan(values) & (weights > 0)
            if mask.any():
                w = weights[mask]
                v = values[mask]
                row[col] = float(np.average(v, weights=w))
            else:
                row[col] = float("nan")

        for col in _SUM_COLS:
            if col in group.columns:
                row[col] = float(group[col].fillna(0).sum())

        out_rows.append(row)

    return pd.DataFrame(out_rows)


# ---------------------------------------------------------------------------
# Encounter-level pairwise extractor
# ---------------------------------------------------------------------------


async def extract_encounter_features(
    session: AsyncSession,
    tournament_ids: typing.Iterable[int],
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return one row per ``Encounter`` with pairwise team matchup features.

    Output columns:

    - Identity: ``encounter_id``, ``tournament_id``, ``home_team_id``, ``away_team_id``.
    - Aggregate ratings: ``home_avg_rank``, ``away_avg_rank``, ``rank_gap``,
      ``home_std_rank``, ``away_std_rank``.
    - Result (only filled for completed encounters): ``home_score``, ``away_score``,
      ``home_won`` (1/0/0.5 for draw).

    Note: opponent **OpenSkill mu** features are populated by
    :mod:`src.services.ml.features.opponent_strength` (it needs the
    historical replay machinery from the v1 flows). This extractor only
    materialises the rank-based features that come straight from the DB.
    """
    tournament_ids = list(tournament_ids)
    if not tournament_ids:
        return pd.DataFrame()

    Player_h = sa.orm.aliased(models.Player)
    Player_a = sa.orm.aliased(models.Player)

    home_stats = (
        sa.select(
            Player_h.team_id.label("team_id"),
            sa.func.avg(Player_h.rank).label("avg_rank"),
            sa.func.coalesce(sa.func.stddev_samp(Player_h.rank), 0).label("std_rank"),
            sa.func.count(Player_h.id).label("player_count"),
        )
        .where(Player_h.is_substitution.is_(False))
        .group_by(Player_h.team_id)
        .subquery("home_stats")
    )
    away_stats = (
        sa.select(
            Player_a.team_id.label("team_id"),
            sa.func.avg(Player_a.rank).label("avg_rank"),
            sa.func.coalesce(sa.func.stddev_samp(Player_a.rank), 0).label("std_rank"),
            sa.func.count(Player_a.id).label("player_count"),
        )
        .where(Player_a.is_substitution.is_(False))
        .group_by(Player_a.team_id)
        .subquery("away_stats")
    )

    query = (
        sa.select(
            models.Encounter.id.label("encounter_id"),
            models.Encounter.tournament_id.label("tournament_id"),
            models.Encounter.home_team_id.label("home_team_id"),
            models.Encounter.away_team_id.label("away_team_id"),
            models.Encounter.home_score.label("home_score"),
            models.Encounter.away_score.label("away_score"),
            home_stats.c.avg_rank.label("home_avg_rank"),
            home_stats.c.std_rank.label("home_std_rank"),
            away_stats.c.avg_rank.label("away_avg_rank"),
            away_stats.c.std_rank.label("away_std_rank"),
        )
        .select_from(models.Encounter)
        .join(
            models.Tournament,
            models.Tournament.id == models.Encounter.tournament_id,
        )
        .join(home_stats, home_stats.c.team_id == models.Encounter.home_team_id, isouter=True)
        .join(away_stats, away_stats.c.team_id == models.Encounter.away_team_id, isouter=True)
        .where(
            models.Encounter.tournament_id.in_(tournament_ids),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
    )

    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return df

    # PostgreSQL ``AVG(...)`` / ``STDDEV_SAMP(...)`` return ``Decimal``; pandas
    # stores them as ``object`` dtype which XGBoost/LightGBM reject downstream.
    for col in ("home_avg_rank", "away_avg_rank", "home_std_rank", "away_std_rank"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    df["rank_gap"] = df["home_avg_rank"] - df["away_avg_rank"]

    # home_won: 1 home wins, 0 away wins, 0.5 draw, NaN if not yet played.
    def _outcome(row: pd.Series) -> float:
        hs, as_ = row["home_score"], row["away_score"]
        if hs is None or as_ is None:
            return float("nan")
        if hs > as_:
            return 1.0
        if hs < as_:
            return 0.0
        return 0.5

    df["home_won"] = df.apply(_outcome, axis=1)

    return df


# ---------------------------------------------------------------------------
# Round-level residual extractor (for throw detection)
# ---------------------------------------------------------------------------


def _normalise_round_residuals(df: pd.DataFrame) -> pd.DataFrame:
    """Attach peer-centred round residuals used by the throw detector.

    ``performance_points`` often move together for an entire team or match.
    A raw within-player z-score would therefore mark every player in a normal
    team-wide collapse as ``throw``. We first z-score each player's own series
    inside the encounter, then subtract the same-team same-round median. The
    resulting ``y_perf`` is a personal late-round deviation, not just a match
    trend.
    """
    if df.empty:
        return df

    df = df.copy()
    df["performance_points"] = pd.to_numeric(
        df["performance_points"],
        errors="coerce",
    ).astype(float)
    df = df.sort_values(
        ["player_id", "encounter_id", "match_id", "source_round"]
    ).reset_index(drop=True)
    df["round"] = (
        df.groupby(["player_id", "encounter_id"], sort=False).cumcount() + 1
    )

    player_group = df.groupby(["player_id", "encounter_id"], sort=False)[
        "performance_points"
    ]
    player_mean = player_group.transform("mean")
    player_std = player_group.transform(lambda values: values.std(ddof=0))
    df["_player_z"] = np.where(
        np.isfinite(player_std) & (player_std > 1e-9),
        (df["performance_points"] - player_mean) / player_std,
        0.0,
    ).astype(float)

    peer_keys = ["encounter_id", "round"]
    if "team_id" in df.columns:
        peer_keys.insert(1, "team_id")
    peer_group = df.groupby(peer_keys, sort=False)["_player_z"]
    peer_count = peer_group.transform("count")
    peer_median = peer_group.transform("median")
    df["y_perf"] = np.where(
        peer_count >= 3,
        df["_player_z"] - peer_median,
        df["_player_z"],
    ).astype(float)
    return df


async def extract_round_residuals(
    session: AsyncSession,
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> pd.DataFrame:
    """Return per-player round residual series for ``detect_throws``.

    The parser already materialises ``performance_points`` for every round.
    We standardise each player's within-encounter round series to z-scores so
    the detector can compare early vs late rounds on a stable scale even when
    absolute performance-point magnitudes differ sharply by role.
    """
    query = (
        sa.select(
            models.Encounter.id.label("encounter_id"),
            models.Match.id.label("match_id"),
            models.MatchStatistics.round.label("source_round"),
            models.Player.id.label("player_id"),
            models.Player.team_id.label("team_id"),
            models.MatchStatistics.value.label("performance_points"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == models.MatchStatistics.team_id,
                models.Player.tournament_id == models.Tournament.id,
            ),
        )
        .join(
            models.WorkspaceMember,
            sa.and_(
                models.WorkspaceMember.id == models.Player.workspace_member_id,
                models.WorkspaceMember.player_id == models.MatchStatistics.user_id,
            ),
        )
        .where(
            models.Encounter.tournament_id == tournament_id,
            models.MatchStatistics.round > 0,
            models.MatchStatistics.hero_id.is_(None),
            models.MatchStatistics.name == LogStatsName.PerformancePoints,
            models.Player.is_substitution.is_(False),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(
            models.Player.id,
            models.Encounter.id,
            models.Match.id,
            models.MatchStatistics.round,
        )
    )
    rows = (await session.execute(query)).mappings().all()
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = _normalise_round_residuals(df)
    return df[["player_id", "encounter_id", "round", "y_perf"]]
