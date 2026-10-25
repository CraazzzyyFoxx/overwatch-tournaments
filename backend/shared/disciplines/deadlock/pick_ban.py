"""Deadlock's built-in pick/ban rulesets (``DisciplineSpec.pick_ban_presets``): per-game hero bans.

Each game: 2 bans per team, A-B-A-B, 30 s per turn, a random hero on timeout. The first ban rotates to the previous
game's loser (``result_loser_first``); game 1 is opened by the higher seed (bracket slot 1 when unseedable). No side
pick: ``SPEC.sides`` are labels only. Organizers edit count/order in the rules editor. Validates clean for
``kind="hero"`` ``mode="pool"``; ``test_pick_ban_rules_presets`` is the guard.

``deadlock_bans_pick`` (pickup mixes only, spec §11.6 R4-7): the same bans, then every player of both teams picks one
hero at once; a hero taken is gone for everyone. ``deadlock_bans_pick_turns`` (pickup mixes only too): the same bans,
then one player at a time in snake order (A-BB-AA-BB-AA-B, A the team that banned first), 30 s each -- a team's k-th
pick is its k-th seat's, as the lineup lists them. ``deadlock_two_phase_draft`` (pickup mixes only too): those picks in
two halves -- a ban each (A, B), picks A-BB-AA-B, a ban each (B, A), picks B-AA-BB-A.
"""

from __future__ import annotations

from typing import Any

from shared.domain.pick_ban_rules.presets import Preset
from shared.domain.pick_ban_rules.schema import parse_ruleset


def _ban(step_id: str, actors: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "action": "ban",
        "actors": actors,
        "count": 1,
        "min": None,
        "blind": False,
        "target": None,
        "lifetime": 1,
        "timer_seconds": None,
        "on_timeout": None,
        "dispute": {"enabled": False, "max": 0},
        "eligible": {},
        "constraints": [],
    }


HERO_BANS: dict[str, Any] = {
    "version": 2,
    "timer_seconds": 30,
    "on_timeout": "random_fill",
    "phases": [
        {
            "id": "main",
            "name": None,
            "when": {},
            "pool_filter": {},
            "generator": None,
            "steps": [_ban("ban1", "first"), _ban("ban2", "second"), _ban("ban3", "first"), _ban("ban4", "second")],
        }
    ],
}

#: Model (b): the four bans, then one open pick in which every member of both teams answers at once.
BANS_PICK: dict[str, Any] = {
    **HERO_BANS,
    "phases": [
        {
            **HERO_BANS["phases"][0],
            "steps": [
                *HERO_BANS["phases"][0]["steps"],
                {
                    **_ban("pick", "both"),
                    "action": "pick",
                    "lifetime": None,
                    "timer_seconds": 60,
                    "member": "each",
                },
            ],
        }
    ],
}

#: The snake the turn-by-turn picks follow, six each: A-BB-AA-BB-AA-B, A the team that banned first.
_SNAKE = "ABBAABBAABBA"
_ACTORS = {"A": "first", "B": "second"}


def _picks(order: str, *, start: int) -> list[dict[str, Any]]:
    """One pick per letter of ``order`` (``A`` = the team that banned first), each the next player's of that team."""
    return [
        {**_ban(f"pick{index}", _ACTORS[team]), "action": "pick", "lifetime": None, "member": "next"}
        for index, team in enumerate(order, start=start)
    ]


def _one_phase(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """``HERO_BANS``'s clock and timeout over ``steps``."""
    return {**HERO_BANS, "phases": [{**HERO_BANS["phases"][0], "steps": steps}]}


#: Model (a): the four bans, then every pick the next player's of that team.
BANS_PICK_TURNS = _one_phase([*HERO_BANS["phases"][0]["steps"], *_picks(_SNAKE, start=1)])

#: Model (a) in two halves: a ban each (A, B), the snake's first six picks, a ban each (B first: A had the first pick),
#: its last six.
TWO_PHASE_DRAFT = _one_phase(
    [
        _ban("ban1", "first"),
        _ban("ban2", "second"),
        *_picks(_SNAKE[:6], start=1),
        _ban("ban3", "second"),
        _ban("ban4", "first"),
        *_picks(_SNAKE[6:], start=7),
    ]
)

PRESETS: tuple[Preset, ...] = (
    Preset("deadlock_hero_bans", "hero", ("pool",), parse_ruleset(HERO_BANS), first_ban_rotation="result_loser_first"),
    Preset("deadlock_bans_pick", "hero", ("pool",), parse_ruleset(BANS_PICK), first_ban_rotation="result_loser_first"),
    Preset(
        "deadlock_bans_pick_turns",
        "hero",
        ("pool",),
        parse_ruleset(BANS_PICK_TURNS),
        first_ban_rotation="result_loser_first",
    ),
    Preset(
        "deadlock_two_phase_draft",
        "hero",
        ("pool",),
        parse_ruleset(TWO_PHASE_DRAFT),
        first_ban_rotation="result_loser_first",
    ),
)
