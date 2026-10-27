"""Feature extractors: SQL → pandas DataFrames at four granularities.

All extractors pivot native ``stats.fact`` rows from long-format (one row per
``(member, match, segment, entity, stat_code)``) into wide-format DataFrames using a
single SQL query with ``CASE`` expressions per stat. This keeps the database
round-trip cost to one query per granularity regardless of how many stats are
materialised.

Granularities:

- :func:`extract_match_features` — one row per ``(player_id, match_id)``,
  aggregated over ``segment = 0`` and ``entity_id IS NULL`` rows (these are
  already-summed per-match totals produced upstream by the parser).
- :func:`extract_tournament_features` — roll-up of match features to
  ``(player_id, tournament_id)`` weighted by ``hero_time_played``.
- :func:`extract_encounter_features` — pairwise team matchup vector per
  ``Encounter`` (input to the Stage-A win-probability classifier).

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
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import LogStatsName
from shared.repository.stats_queries import player_facts, team_scores
from shared.services.workspace_scope import workspace_scope_filter

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


def _stat_col(facts: sa.Subquery, stat: LogStatsName, column_name: str) -> sa.Label[typing.Any]:
    """Pivot the unique native whole-match, non-character player fact."""
    return sa.func.max(sa.case((facts.c.stat_code == stat.value, facts.c.value))).label(column_name)


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

    Source ``stats.fact`` rows with ``segment = 0`` and ``entity_id IS NULL``
    are already-aggregated per-match totals (one row per member and stat).
    The pivot below turns one such row-set per
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

    facts = player_facts(discipline="overwatch")
    # Pivot first: the score/roster joins and the per-row role subquery then run once per (player, match), not once
    # per stat fact — grouping by ``Player.role`` evaluated its correlated lookup for every fact row.
    keys = (
        facts.c.tournament_id,
        facts.c.encounter_id,
        facts.c.match_id,
        facts.c.map_entity_id,
        facts.c.duration_s,
        facts.c.player_id,
        facts.c.tournament_team_id,
        facts.c.workspace_member_id,
    )
    pivot = (
        sa.select(*keys, *[_stat_col(facts, stat, name) for stat, name in STAT_COLUMNS])
        .where(facts.c.tournament_id.in_(tournament_ids), facts.c.segment == 0, facts.c.entity_id.is_(None))
        .group_by(*keys)
        .subquery()
    )

    def side(position: int, name: str) -> sa.Lateral:
        # A per-row index lookup: as a plain join the planner under-estimates both sides and nest-loops the score
        # subquery unparameterized, rescanning every match's score facts per row. LIMIT keeps PostgreSQL from
        # flattening the LATERAL back into that join; (match, source position) holds at most one score fact anyway.
        scores = team_scores(discipline="overwatch", stat_code="score")
        return (
            sa.select(scores.c.tournament_team_id, sa.cast(scores.c.value, sa.Integer).label("score"))
            .where(scores.c.match_id == pivot.c.match_id, scores.c.source_position == position)
            .limit(1)
            .lateral(name)
        )

    # Observation order, not encounter slots, is part of the trained input boundary.
    home, away = side(1, "home"), side(2, "away")
    query = (
        sa.select(
            models.Tournament.id.label("tournament_id"),
            pivot.c.encounter_id,
            pivot.c.match_id,
            pivot.c.map_entity_id.label("map_id"),
            home.c.tournament_team_id.label("home_team_id"),
            away.c.tournament_team_id.label("away_team_id"),
            home.c.score.label("home_score"),
            away.c.score.label("away_score"),
            pivot.c.duration_s.label("match_time"),
            pivot.c.player_id.label("user_id"),
            pivot.c.tournament_team_id.label("team_id"),
            models.Player.id.label("player_id"),
            models.Player.role.label("role"),
            models.Player.rank.label("rank"),
            models.Player.is_newcomer.label("is_newcomer"),
            *[pivot.c[name] for _, name in STAT_COLUMNS],
        )
        .select_from(pivot)
        .join(models.Tournament, models.Tournament.id == pivot.c.tournament_id)
        .join(home, sa.true())
        .join(away, sa.true())
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == pivot.c.tournament_team_id,
                models.Player.tournament_id == pivot.c.tournament_id,
                models.Player.workspace_member_id == pivot.c.workspace_member_id,
            ),
        )
        .where(models.Player.is_substitution.is_(False), *workspace_scope_filter(workspace_id, workspace_ids))
        .order_by(models.Tournament.id, pivot.c.encounter_id, pivot.c.match_id, pivot.c.player_id, models.Player.id)
    )

    result = await session.execute(query)
    df = pd.DataFrame(result.mappings().all())
    if df.empty:
        return df

    # ---- derived columns ----
    # An all-unranked frame comes back as ``object`` ``None``s; numeric NaN keeps ``rank`` a LightGBM-legal feature.
    df["rank"] = pd.to_numeric(df["rank"])
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
    :mod:`analytics-service.src.services.ml.features.opponent_strength` (it needs the
    historical replay machinery). This extractor only
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

    # Only a duel -- exactly two active seats, slot 1 and slot 2 -- has two-team features.
    first_seat = sa.orm.aliased(models.EncounterTeam, name="first_seat")
    second_seat = sa.orm.aliased(models.EncounterTeam, name="second_seat")
    query = (
        sa.select(
            models.Encounter.id.label("encounter_id"),
            models.Encounter.tournament_id.label("tournament_id"),
            first_seat.team_id.label("home_team_id"),
            second_seat.team_id.label("away_team_id"),
            first_seat.score.label("home_score"),
            second_seat.score.label("away_score"),
            first_seat.placement.label("home_placement"),
            second_seat.placement.label("away_placement"),
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
        .join(
            first_seat,
            sa.and_(
                first_seat.encounter_id == models.Encounter.id,
                first_seat.slot == 1,
                first_seat.active.is_(True),
            ),
        )
        .join(
            second_seat,
            sa.and_(
                second_seat.encounter_id == models.Encounter.id,
                second_seat.slot == 2,
                second_seat.active.is_(True),
            ),
        )
        .join(home_stats, home_stats.c.team_id == first_seat.team_id, isouter=True)
        .join(away_stats, away_stats.c.team_id == second_seat.team_id, isouter=True)
        .where(
            models.Encounter.slot_count == 2,
            models.Encounter.discipline == "overwatch",
            models.Encounter.tournament_id.in_(tournament_ids),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        # Stated, not left to the plan: newest first, the order the frozen feature goldens hold.
        .order_by(models.Encounter.id.desc())
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

    # home_won (slot 1 won): 1 if slot 1 placed ahead, 0 if behind, 0.5 for a shared place,
    # NaN while there is no result.
    def _outcome(row: pd.Series) -> float:
        first, second = row["home_placement"], row["away_placement"]
        if pd.isna(first) or pd.isna(second):
            return float("nan")
        if first < second:
            return 1.0
        if first > second:
            return 0.0
        return 0.5

    df["home_won"] = df.apply(_outcome, axis=1)
    df = df.drop(columns=["home_placement", "away_placement"])

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
    df = df.sort_values(["player_id", "encounter_id", "match_id", "source_round"]).reset_index(drop=True)
    df["round"] = df.groupby(["player_id", "encounter_id"], sort=False).cumcount() + 1

    player_group = df.groupby(["player_id", "encounter_id"], sort=False)["performance_points"]
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
    facts = player_facts(discipline="overwatch")
    query = (
        sa.select(
            facts.c.encounter_id.label("encounter_id"),
            facts.c.match_id.label("match_id"),
            facts.c.segment.label("source_round"),
            models.Player.id.label("player_id"),
            models.Player.team_id.label("team_id"),
            facts.c.value.label("performance_points"),
        )
        .select_from(facts)
        .join(models.Tournament, models.Tournament.id == facts.c.tournament_id)
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == facts.c.tournament_team_id,
                models.Player.tournament_id == facts.c.tournament_id,
                models.Player.workspace_member_id == facts.c.workspace_member_id,
            ),
        )
        .where(
            facts.c.tournament_id == tournament_id,
            facts.c.segment > 0,
            facts.c.entity_id.is_(None),
            facts.c.stat_code == LogStatsName.PerformancePoints.value,
            models.Player.is_substitution.is_(False),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Player.id, facts.c.encounter_id, facts.c.match_id, facts.c.segment)
    )
    rows = (await session.execute(query)).mappings().all()
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = _normalise_round_residuals(df)
    return df[["player_id", "encounter_id", "round", "y_perf"]]
