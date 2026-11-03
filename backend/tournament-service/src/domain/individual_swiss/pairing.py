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


def split_pool(
    players: Sequence[PoolPlayer], shape: Mapping[str, int], team_count: int, rng: random.Random
) -> list[list[PoolPlayer]]:
    """Random start, then first-improvement same-role swaps while the rank totals get more even."""
    # shortcut: no teammate/opponent history penalty; upgrade when the backlog item lands
    groups = _by_role(players, shape, team_count)
    teams: list[list[PoolPlayer]] = [[] for _ in range(team_count)]
    for role, n in shape.items():
        pool = groups[role]
        rng.shuffle(pool)
        for t in range(team_count):
            teams[t].extend(pool[t * n : (t + 1) * n])
    totals = [sum(p.rank for p in team) for team in teams]
    improved = True
    while improved:
        improved = False
        for i, j in combinations(range(team_count), 2):
            for x, a in enumerate(teams[i]):
                for y, b in enumerate(teams[j]):
                    d = b.rank - a.rank
                    # change of the sum of squared deviations (the mean is fixed): 2d(Ti - Tj) + 2d^2
                    if a.role == b.role and d * (totals[i] - totals[j]) + d * d < 0:
                        teams[i][x], teams[j][y] = b, a
                        totals[i] += d
                        totals[j] -= d
                        improved = True
                        break
                else:
                    continue
                break
    return teams


def pair_randomly(
    teams: Sequence[list[PoolPlayer]], rng: random.Random
) -> list[tuple[list[PoolPlayer], list[PoolPlayer]]]:
    if len(teams) % 2:
        raise PoolError("odd_team_count", f"Нужно чётное число команд: сейчас {len(teams)}")
    shuffled = list(teams)
    rng.shuffle(shuffled)
    return [(shuffled[i], shuffled[i + 1]) for i in range(0, len(shuffled), 2)]


def round_captain(team: Sequence[PoolPlayer]) -> PoolPlayer:
    return min(team, key=lambda p: (-p.rank, p.member_id))
