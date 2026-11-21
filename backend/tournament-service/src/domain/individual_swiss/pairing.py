"""Lobby formation, team splits and pairing for individual Swiss. Every random choice goes through ``rng``."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import combinations, product

from src.domain.individual_swiss.pool import PoolError, PoolPlayer


def score_lobbies(order: Mapping[str, Sequence[PoolPlayer]], shape: Mapping[str, int]) -> list[list[PoolPlayer]]:
    lobbies = min(len(order[role]) // (2 * n) for role, n in shape.items())
    return [[p for role, n in shape.items() for p in order[role][i * 2 * n : (i + 1) * 2 * n]] for i in range(lobbies)]


def _by_role(players: Sequence[PoolPlayer], shape: Mapping[str, int], per_team: int) -> dict[str, list[PoolPlayer]]:
    groups: dict[str, list[PoolPlayer]] = defaultdict(list)
    for p in players:
        groups[p.role].append(p)
    if set(groups) - set(shape) or any(len(groups[role]) != n * per_team for role, n in shape.items()):
        raise PoolError("role_count_mismatch", "Состав лобби не соответствует составу команды")
    return {role: groups[role] for role in shape}


def split_two(
    lobby: Sequence[PoolPlayer], shape: Mapping[str, int], rng: random.Random
) -> tuple[list[PoolPlayer], list[PoolPlayer]]:
    """Exact: every split with ``shape[role]`` per role per team, the smallest rank-sum gap, ties by ``rng``."""
    # shortcut: no teammate/opponent history penalty; upgrade when the backlog item lands
    groups = _by_role(lobby, shape, 2)
    total = sum(p.rank for p in lobby)
    # per role: the index sets team A takes (team B gets the rest)
    options = [list(combinations(range(len(groups[role])), n)) for role, n in shape.items()]
    best_gap: int | None = None
    best: list[tuple[tuple[int, ...], ...]] = []
    for pick in product(*options):
        a_sum = sum(groups[role][i].rank for role, idx in zip(shape, pick, strict=True) for i in idx)
        gap = abs(2 * a_sum - total)
        if best_gap is None or gap < best_gap:
            best_gap, best = gap, [pick]
        elif gap == best_gap:
            best.append(pick)
    chosen = rng.choice(best)
    team_a: list[PoolPlayer] = []
    team_b: list[PoolPlayer] = []
    for role, idx in zip(shape, chosen, strict=True):
        taken = set(idx)
        for i, p in enumerate(groups[role]):
            (team_a if i in taken else team_b).append(p)
    return team_a, team_b


def teams_from_ids(
    team_ids: Sequence[Sequence[int]], players: Sequence[PoolPlayer], shape: Mapping[str, int], team_count: int
) -> list[list[PoolPlayer]]:
    """The balancer's teams as pool players: ``team_count`` teams of ``shape``, every player exactly once."""
    by_member = {p.member_id: p for p in players}
    seated = [member for team in team_ids for member in team]
    if len(team_ids) != team_count or sorted(seated) != sorted(by_member):
        raise PoolError("balancer_invalid_result", "Балансер вернул составы не на весь пул раунда")
    teams = [[by_member[member] for member in team] for team in team_ids]
    for team in teams:
        _by_role(team, shape, 1)
    return teams


def pair_closest(teams: Sequence[list[PoolPlayer]]) -> list[tuple[list[PoolPlayer], list[PoolPlayer]]]:
    """Teams ordered by rank total, neighbours paired: the smallest total gap per match. Ties by member ids."""
    if len(teams) % 2:
        raise PoolError("odd_team_count", f"Нужно чётное число команд: сейчас {len(teams)}")
    ordered = sorted(teams, key=lambda team: (sum(p.rank for p in team), sorted(p.member_id for p in team)))
    return [(ordered[i], ordered[i + 1]) for i in range(0, len(ordered), 2)]


def round_captain(team: Sequence[PoolPlayer]) -> PoolPlayer:
    return min(team, key=lambda p: (-p.rank, p.member_id))
