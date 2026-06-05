from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.core.enums import DraftAutopickStrategy, DraftRole  # noqa: E402
from src.services.draft import suggestions as sug  # noqa: E402

T, D, SUP = DraftRole.TANK, DraftRole.DPS, DraftRole.SUPPORT


def fp(pid, rank, playable, prefs=(), is_flex=False):
    return sug.FitPlayer(
        player_id=pid,
        rank_value=rank,
        playable_roles=frozenset(playable),
        preference_order=tuple(prefs),
        is_flex=is_flex,
    )


# ---- discomfort heuristic (mirrors balancer entities.py) ----


def test_discomfort_flex_playable_is_zero() -> None:
    p = fp(1, 3000, {T}, prefs=(), is_flex=True)
    assert sug.role_discomfort(p, T) == 0


def test_discomfort_preference_index_times_100() -> None:
    p = fp(1, 3000, {D, SUP}, prefs=(D, SUP))
    assert sug.role_discomfort(p, D) == 0  # index 0
    assert sug.role_discomfort(p, SUP) == 100  # index 1


def test_discomfort_playable_not_preferred_is_1000() -> None:
    p = fp(1, 3000, {T}, prefs=())
    assert sug.role_discomfort(p, T) == 1000


def test_discomfort_unplayable_is_5000() -> None:
    p = fp(1, 3000, {T}, prefs=())
    assert sug.role_discomfort(p, D) == 5000


# ---- role impact weights ----


def test_role_impact_defaults() -> None:
    cfg = sug.FitConfig()
    assert cfg.role_impact[T] == 1.4
    assert cfg.role_impact[D] == 1.0
    assert cfg.role_impact[SUP] == 1.1


# ---- BEST_FIT ----


def test_best_fit_weighs_rank_against_discomfort() -> None:
    # P1 comfortable but lower rank; P2 higher rank but uncomfortable.
    p1 = fp(1, 3000, {T}, prefs=(T,))  # disc 0  -> 3000*1.4        = 4200
    p2 = fp(2, 4000, {T}, prefs=())  # disc 1000 -> 4000*1.4-1000 = 4600
    res = sug.best_fit([p1, p2], {T: 1}, DraftAutopickStrategy.BEST_FIT, sug.FitConfig())
    assert res is not None
    assert res.player_id == 2
    assert res.role == T


def test_best_fit_vs_best_available_differ() -> None:
    p1 = fp(1, 5000, {T}, prefs=())  # disc 1000
    p2 = fp(2, 4900, {T}, prefs=(T,))  # disc 0
    cfg = sug.FitConfig()
    best_fit = sug.best_fit([p1, p2], {T: 1}, DraftAutopickStrategy.BEST_FIT, cfg)
    best_avail = sug.best_fit([p1, p2], {T: 1}, DraftAutopickStrategy.BEST_AVAILABLE, cfg)
    assert best_fit.player_id == 2  # comfort wins on fit
    assert best_avail.player_id == 1  # raw rank wins on availability


# ---- ROLE_NEED ----


def test_role_need_fills_most_needed_role_first() -> None:
    tank = fp(1, 5000, {T}, prefs=(T,))
    supp = fp(2, 3000, {SUP}, prefs=(SUP,))
    # SUPPORT has 2 open slots, TANK only 1 -> role-need favours support.
    res = sug.best_fit([tank, supp], {T: 1, SUP: 2}, DraftAutopickStrategy.ROLE_NEED, sug.FitConfig())
    assert res.role == SUP
    assert res.player_id == 2


# ---- legality / empties ----


def test_returns_none_when_no_open_capacity() -> None:
    p = fp(1, 3000, {T}, prefs=(T,))
    assert sug.best_fit([p], {T: 0}, DraftAutopickStrategy.BEST_FIT, sug.FitConfig()) is None


def test_returns_none_when_player_cannot_play_open_role() -> None:
    p = fp(1, 3000, {T}, prefs=(T,))
    assert sug.best_fit([p], {SUP: 1}, DraftAutopickStrategy.BEST_FIT, sug.FitConfig()) is None


def test_returns_none_when_no_players() -> None:
    assert sug.best_fit([], {T: 1}, DraftAutopickStrategy.BEST_FIT, sug.FitConfig()) is None


# ---- determinism ----


def test_deterministic_tiebreak_prefers_lower_player_id() -> None:
    # identical rank/role/discomfort -> lower player_id wins
    a = fp(7, 3000, {T}, prefs=(T,))
    b = fp(3, 3000, {T}, prefs=(T,))
    res = sug.best_fit([a, b], {T: 1}, DraftAutopickStrategy.BEST_FIT, sug.FitConfig())
    assert res.player_id == 3


# ---- suggestions ranking ----


def test_rank_suggestions_returns_sorted_topn() -> None:
    players = [
        fp(1, 2000, {T}, prefs=(T,)),
        fp(2, 4000, {T}, prefs=(T,)),
        fp(3, 3000, {T}, prefs=(T,)),
    ]
    out = sug.rank_suggestions(players, {T: 1}, sug.FitConfig(), limit=2)
    assert len(out) == 2
    assert [s.player_id for s in out] == [2, 3]  # highest fit first
    assert out[0].fit_score >= out[1].fit_score
