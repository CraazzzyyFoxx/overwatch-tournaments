"""Points / Linear / OpenSkill rating math. No session."""

from __future__ import annotations

import math
import typing
from dataclasses import dataclass, replace
from datetime import datetime

import numpy as np
import pandas as pd
from openskill.models import PlackettLuce, PlackettLuceRating

from shared.division_grid import DivisionGrid, DivisionTier
from src.domain.linear import STABLE_SHIFT_SCALE, TournamentSignal, raw_signal_sd, score_history

__all__ = (
    "AnalyticsMatch",
    "COEF_NOVICE_FIRST",
    "COEF_NOVICE_SECOND",
    "COEF_REGULAR",
    "LINEAR",
    "OPENSKILL",
    "OPENSKILL_LOOKBACK",
    "POINTS",
    "compute_linear_metrics",
    "compute_points_shifts",
    "division_delta_points",
    "get_id_role",
    "get_plackett_luce",
    "get_player_rating",
    "prepare_openskill_data",
    "rank_sd_to_divisions",
)

COEF_NOVICE_FIRST = 1 / 0.15
COEF_NOVICE_SECOND = 1 / 0.11
COEF_REGULAR = 1 / 0.065
OPENSKILL_LOOKBACK = 10
LINEAR = "Linear"
OPENSKILL = "OpenSkill"
POINTS = "Points"
_MU = 1100


@dataclass(frozen=True)
class AnalyticsTeam:
    team_id: int
    name: str
    players: list[str]
    score: float
    placement: int


@dataclass(frozen=True)
class AnalyticsMatch:
    tournament_id: int
    #: Every live seat, in slot order.
    teams: list[AnalyticsTeam]
    time: datetime


def division_delta_points(
    previous_div: int | float | None,
    current_div: int | float | None,
) -> int | None:
    if previous_div is None or pd.isna(previous_div):
        return None
    if current_div is None or pd.isna(current_div):
        return None
    return int(round((float(previous_div) - float(current_div)) * 100))


def compute_points_shifts(df: pd.DataFrame) -> pd.DataFrame:
    """Write ``points_shift`` and its sd ``points_shift_sd`` per row of ``df``; return ``df``.

    A map adds ±1 to ``wins - losses``, so a row scored as ``delta · coef`` over ``maps`` maps has variance
    ``coef² · maps``; the sd sums that over the rows the shift accumulates. No maps in that window: NaN.
    """
    for _, rows in df.groupby("id_role", sort=False):
        rows = rows.sort_values(["started_at", "tournament_id"])
        is_novice = True
        previous_shift = 0.0
        previous_variance = 0.0
        for index, row in rows.iterrows():
            delta = row["wins"] - row["losses"]
            maps = row["wins"] + row["losses"]
            if is_novice:
                if row["is_changed"]:
                    shift = delta / COEF_NOVICE_FIRST
                    variance = maps / COEF_NOVICE_FIRST**2
                    is_novice = False
                else:
                    shift = delta / COEF_NOVICE_SECOND
                    variance = maps / COEF_NOVICE_SECOND**2
            else:
                shift = delta / COEF_REGULAR
                if row["is_changed"]:
                    shift += delta / COEF_REGULAR
                    variance = maps * (2 / COEF_REGULAR) ** 2
                else:
                    shift += previous_shift
                    variance = maps / COEF_REGULAR**2 + previous_variance
            previous_shift = shift
            previous_variance = variance
            df.at[index, "points_shift"] = round(float(shift), 2)
            df.at[index, "points_shift_sd"] = math.sqrt(variance) if variance > 0 else np.nan
    return df


def compute_linear_metrics(df: pd.DataFrame, *, shift_scale: float = STABLE_SHIFT_SCALE) -> pd.DataFrame:
    """Write the Linear columns per row of ``df``; return ``df``.

    A player's history restarts at their latest division change (``is_changed``; an unranked row never restarts it):
    the tournaments before the move describe the old division. ``linear_shift_sd`` comes from one raw-signal noise
    estimate for the whole frame (NaN when it is undefined).
    """
    if df.empty:
        return df

    signals = {
        index: TournamentSignal(
            map_diff=float(row["map_diff"]),
            placement_score=float(row["placement_score"]),
            recency_decay=1.0,
            coverage_weight=float(0.7 + 0.3 * row["log_available"]),
            maps=int(row["wins"] + row["losses"]) or int(row["match_count"] or 0),
            match_count=int(row["match_count"] or 0),
            log_available=float(row["log_available"]),
        )
        for index, row in zip(df.index, df.to_dict("records"), strict=True)
    }
    noise_sd = raw_signal_sd(list(signals.values()))

    for _, group in df.groupby("id_role", sort=False):
        group = group.sort_values(["started_at", "tournament_id"])
        start = 0
        for position, (index, is_changed) in enumerate(zip(group.index, group["is_changed"], strict=True)):
            if is_changed:
                start = position
            history = [
                replace(signals[history_index], recency_decay=float(0.85 ** (position - history_position)))
                for history_position, history_index in enumerate(group.index[start : position + 1], start)
            ]

            metrics = score_history(history, noise_sd=noise_sd, shift_scale=shift_scale)
            df.at[index, "linear_shift_sd"] = metrics.shift_sd if metrics.shift_sd is not None else np.nan
            df.at[index, "effective_evidence"] = metrics.effective_evidence
            df.at[index, "sample_tournaments"] = metrics.sample_tournaments
            df.at[index, "sample_matches"] = metrics.sample_matches
            df.at[index, "log_coverage"] = metrics.log_coverage
            df.at[index, "linear_stable_shift"] = metrics.stable_shift
            df.at[index, "linear_trend_shift"] = metrics.trend_shift

    return df


def _tier_width(grid: DivisionGrid, tier: DivisionTier) -> int:
    """Rank span of ``tier`` (bounds inclusive); an open-ended edge tier takes its neighbour's."""
    if tier.rank_max is not None:
        return tier.rank_max - tier.rank_min + 1
    by_rank = sorted(grid.tiers, key=lambda candidate: candidate.rank_min)
    position = by_rank.index(tier)
    neighbour = by_rank[position - 1] if position > 0 else by_rank[position + 1]
    return _tier_width(grid, neighbour)


def rank_sd_to_divisions(grid: DivisionGrid, ladder: DivisionGrid, rank: float, sd: float) -> float:
    """``sd`` in ``grid`` rank units at ``rank`` as canonical divisions on ``ladder``.

    Through the width of the tier ``rank`` falls in, then the canonical divisions that tier spans: its native range
    over the ladder tier at the range's midpoint, else the proportional placement ``canonical_tier_number`` uses. On
    the canonical grid itself that is ``sd / 100``.
    """
    tier = grid.resolve_division(int(round(rank)))
    if tier.native_rank_min is not None and tier.native_rank_max is not None:
        low = min(tier.native_rank_min, tier.native_rank_max)
        high = max(tier.native_rank_min, tier.native_rank_max)
        canonical_per_tier = (high - low + 1) / _tier_width(ladder, ladder.resolve_division((low + high) // 2))
    else:
        source_span = grid.max_division - grid.min_division
        ladder_span = ladder.max_division - ladder.min_division
        canonical_per_tier = ladder_span / source_span if source_span > 0 else 0.0
    return sd / _tier_width(grid, tier) * canonical_per_tier


def get_plackett_luce() -> PlackettLuce:
    return PlackettLuce(mu=_MU, sigma=_MU / 6, beta=_MU / 2.75, tau=_MU / 300.0, balance=True)


def get_id_role(player: typing.Any) -> str:
    """``user_id-role`` key. Callers must eager-load ``Player.workspace_member``."""
    return f"{player.workspace_member.player_id}-{player.role}"


def get_player_rating(pl: PlackettLuce, player: typing.Any) -> PlackettLuceRating:
    """Seed rating from the roster rank; an unranked player (``rank`` None) starts at the model's default mu."""
    if player.is_newcomer or player.is_newcomer_role:
        return pl.rating(mu=player.rank, sigma=_MU / 4.25)
    return pl.rating(mu=player.rank)


def prepare_openskill_data(
    df: pd.DataFrame,
    pl: PlackettLuce,
    teams: typing.Sequence[typing.Any],
    encounters: typing.Sequence[typing.Any],
    rosters: typing.Mapping[int, typing.Any],
) -> tuple[set[str], dict[str, PlackettLuceRating], list[AnalyticsMatch]]:
    """Seed ratings from the rosters, then replay ``encounters`` in order.

    An encounter rates its live seats as N teams, ranked by ``placement``; ``rosters`` maps a
    source ``team_id`` to its ``Team`` (with players). An encounter with no result yet, fewer than
    two seats, or a seat without a roster is not replayed.
    """
    del df  # replay is seeded from rosters + encounters, not the frame
    agents: set[str] = set()
    players_rating: dict[str, PlackettLuceRating] = {}
    analytics_matches: list[AnalyticsMatch] = []

    for encounter in encounters:
        seats = sorted((seat for seat in encounter.teams if seat.active), key=lambda seat: seat.slot)
        replay: list[tuple[typing.Any, list[typing.Any]]] = []
        for seat in seats:
            team = rosters.get(seat.team_id) if seat.team_id is not None else None
            players = list(team.players or ()) if team is not None else []
            if not players:
                break
            replay.append((seat, players))
        if len(replay) < 2 or len(replay) != len(seats) or any(seat.placement is None for seat, _ in replay):
            continue

        for _, players in replay:
            for player in players:
                id_role = get_id_role(player)
                agents.add(id_role)
                if players_rating.get(id_role) is None:
                    players_rating[id_role] = get_player_rating(pl, player)

        analytics_matches.append(
            AnalyticsMatch(
                tournament_id=encounter.tournament_id,
                teams=[
                    AnalyticsTeam(
                        team_id=seat.team_id,
                        name=seat.name,
                        players=[get_id_role(player) for player in players],
                        score=seat.score,
                        placement=seat.placement,
                    )
                    for seat, players in replay
                ],
                time=encounter.tournament.start_date,
            )
        )

    for team in teams:
        for player in team.players:
            id_role = get_id_role(player)
            if id_role not in players_rating:
                players_rating[id_role] = get_player_rating(pl, player)

    for match in analytics_matches:
        sides = [[players_rating[i] for i in side.players] for side in match.teams]
        rated = pl.rate(sides, ranks=[side.placement for side in match.teams])
        for side, rated_side in zip(match.teams, rated, strict=True):
            for id_role, rating in zip(side.players, rated_side, strict=True):
                players_rating[id_role] = rating

    return agents, players_rating, analytics_matches
