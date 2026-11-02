"""Pool shape validation for individual Swiss: who plays, in which role, how many teams a round has."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PoolPlayer:
    member_id: int
    registration_id: int | None
    display_name: str
    role: str
    rank: int


class PoolError(ValueError):
    """A pool the format cannot play; ``code`` is machine-readable, ``str(exc)`` is shown to the organizer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def teams_per_round(players: Sequence[PoolPlayer], shape: Mapping[str, int]) -> int:
    counts = Counter(p.role for p in players)
    outside = sorted(set(counts) - set(shape))
    if outside:
        raise PoolError("role_outside_shape", f"Роли вне состава команды: {', '.join(outside)}")
    per_role = {role: counts[role] for role in shape}
    teams = {role: n // shape[role] for role, n in per_role.items()}
    if any(n % shape[role] for role, n in per_role.items()) or len(set(teams.values())) != 1:
        listing = ", ".join(f"{role}: {n} (нужно кратно {shape[role]})" for role, n in per_role.items())
        raise PoolError("role_count_mismatch", f"Число игроков по ролям не складывается в команды — {listing}")
    count = next(iter(teams.values()))
    if count % 2:
        raise PoolError("odd_team_count", f"Нужно чётное число команд: сейчас {count}")
    if count < 2:
        raise PoolError("too_few_players", "Для раунда нужно минимум две команды")
    return count


def check_playoff_team_count(k: int, teams_per_round: int, shape: Mapping[str, int]) -> None:
    # `shape` is part of the contract: the cut takes k * shape[role] per role, which fits whenever k <= teams.
    del shape
    if k > teams_per_round:
        raise PoolError(
            "playoff_too_large",
            f"В плей-офф не может быть больше команд, чем играет в раунде: {k} > {teams_per_round}",
        )
