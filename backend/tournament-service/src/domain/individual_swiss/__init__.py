"""Pure rules of the individual Swiss format: pool shape, lobbies, team splits, personal table."""

from src.domain.individual_swiss.pairing import pair_randomly, round_captain, score_lobbies, split_pool, split_two
from src.domain.individual_swiss.pool import PoolError, PoolPlayer, check_playoff_team_count, teams_per_round
from src.domain.individual_swiss.table import (
    MatchResult,
    PlayerTotals,
    SeatResult,
    StandingLine,
    compute_totals,
    order_role,
    pick_captains,
    qualify,
)

__all__ = (
    "MatchResult",
    "PlayerTotals",
    "PoolError",
    "PoolPlayer",
    "SeatResult",
    "StandingLine",
    "check_playoff_team_count",
    "compute_totals",
    "order_role",
    "pair_randomly",
    "pick_captains",
    "qualify",
    "round_captain",
    "score_lobbies",
    "split_pool",
    "split_two",
    "teams_per_round",
)
