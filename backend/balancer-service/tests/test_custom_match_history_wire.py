"""The mix history wire speaks slots (D78): ``teams[]`` and ``winner_slot``, no home/away, no ``winner``."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_BACKEND_ROOT), str(REPO_BACKEND_ROOT / "balancer-service")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.rpc import custom  # noqa: E402

AT = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
STARTED = datetime(2026, 10, 1, 19, 20, tzinfo=UTC)


def _round(scores: tuple[float, float]) -> SimpleNamespace:
    return SimpleNamespace(
        lobby_index=1,
        points_per_win_applied=25,
        encounter=SimpleNamespace(
            id=501,
            created_at=STARTED,
            confirmed_at=AT,
            teams=[
                SimpleNamespace(slot=2, name="Bravo", score=scores[1]),
                SimpleNamespace(slot=1, name="Alpha", score=scores[0]),
            ],
            games=[SimpleNamespace(map_id=3)],
            result_audit=[SimpleNamespace(actor_user_id=70)],
        ),
    )


def test_a_decided_round_names_its_winning_slot() -> None:
    assert custom._dump_round(
        _round((1.0, 0.0)),
        {3: ("Busan", "/busan.png")},
        [{"slot": 1, "item_id": 40}],
        [],
        (None, "processing", "searching"),
    ) == {
        "id": 501,
        "lobby_index": 1,
        "teams": [{"slot": 1, "name": "Alpha", "score": 1}, {"slot": 2, "name": "Bravo", "score": 0}],
        "winner_slot": 1,
        "bans": [{"slot": 1, "item_id": 40}],
        "picks": [],
        "map_id": 3,
        "map_name": "Busan",
        "map_image_path": "/busan.png",
        "points_per_win_applied": 25,
        "recorded_by": 70,
        "recorded_at": AT.isoformat(),
        "stats_match_id": None,
        "log_state": "processing",
        "match_search": "searching",
    }


def test_a_draw_has_no_winning_slot() -> None:
    assert custom._dump_round(_round((0.0, 0.0)), {}, [], [], (None, None, None))["winner_slot"] is None


def test_a_round_carries_its_match_log() -> None:
    row = custom._dump_round(_round((1.0, 0.0)), {}, [], [], (9, None, None))
    assert (row["stats_match_id"], row["log_state"]) == (9, None)
    row = custom._dump_round(_round((1.0, 0.0)), {}, [], [], (None, "failed", "not_found"))
    assert (row["stats_match_id"], row["log_state"], row["match_search"]) == (None, "failed", "not_found")
