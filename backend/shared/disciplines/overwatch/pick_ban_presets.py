"""Overwatch's built-in pick/ban rulesets (``DisciplineSpec.pick_ban_presets``).

The preset schema and the game-neutral map presets live in ``shared.domain.pick_ban_rules.presets``; the hero
rulesets below only make sense against a hero pool whose ``attrs.class`` is one of this module's
``character_classes`` (``tank``/``damage``/``support``), so they travel with the module. A class is a hero's
class, never a player's assigned role. The map ruleset reads a map's gamemode, which only this game's maps have.

Each one validates clean for its kind and modes; ``test_pick_ban_rules_presets`` is the guard.
"""

from __future__ import annotations

from typing import Any

from shared.domain.pick_ban_rules.presets import Preset
from shared.domain.pick_ban_rules.schema import parse_ruleset


def _step(
    step_id: str,
    *,
    action: str = "ban",
    actors: str = "first",
    count: int = 1,
    blind: bool = False,
    target: str | None = None,
    lifetime: int | None = 1,
    dispute: bool = False,
    eligible: dict[str, Any] | None = None,
    constraints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "action": action,
        "actors": actors,
        "count": count,
        "min": None,
        "blind": blind,
        "target": target,
        "lifetime": lifetime if action == "ban" else None,
        "timer_seconds": None,
        "on_timeout": None,
        "dispute": {"enabled": dispute, "max": 1 if dispute else 0},
        "eligible": eligible or {},
        "constraints": constraints or [],
    }


def _one_phase(steps: list[dict[str, Any]], *, timer_seconds: int | None = 90) -> dict[str, Any]:
    return {
        "version": 2,
        "timer_seconds": timer_seconds,
        "on_timeout": "random_fill",
        "phases": [{"id": "main", "name": None, "when": {}, "pool_filter": {}, "generator": None, "steps": steps}],
    }


HERO_CLASSIC = _one_phase([_step("ban1"), _step("ban2", actors="second")])

HERO_PROTECT_BAN = _one_phase(
    [
        _step("protect1", action="protect"),
        _step("protect2", action="protect", actors="second"),
        _step("ban1"),
        _step("ban2", actors="second"),
        _step("ban3", actors="second"),
        _step("ban4"),
    ]
)

HERO_BLIND_2 = _one_phase([_step("blind2", actors="both", count=2, blind=True, lifetime=1, dispute=True)])

HERO_ROLE_BANS = _one_phase(
    [
        _step(
            "blind3",
            actors="both",
            count=3,
            blind=True,
            lifetime=1,
            dispute=True,
            constraints=[{"type": "max_per_group", "params": {"max": 1, "scope": "step", "group": None}}],
        )
    ]
)

#: A published tournament ruleset, verbatim.
HERO_ANTI_ONE_TRICK: dict[str, Any] = {
    "version": 2,
    "timer_seconds": 90,
    "on_timeout": "random_fill",
    "phases": [
        {
            "id": "map1",
            "name": "Map 1",
            "when": {"type": "map_index", "params": {"op": "==", "value": 1}},
            "pool_filter": {},
            "generator": None,
            "steps": [
                {
                    "id": "blind2",
                    "action": "ban",
                    "actors": "both",
                    "count": 2,
                    "min": None,
                    "blind": True,
                    "target": None,
                    "lifetime": 1,
                    "timer_seconds": None,
                    "on_timeout": None,
                    "dispute": {"enabled": True, "max": 1},
                    "eligible": {},
                    "constraints": [],
                }
            ],
        },
        {
            "id": "map2plus",
            "name": "Map 2+",
            "when": {"type": "map_index", "params": {"op": ">=", "value": 2}},
            "pool_filter": {},
            "generator": None,
            "steps": [
                {
                    "id": "perplayer5",
                    "action": "ban",
                    "actors": "both",
                    "count": 5,
                    "min": None,
                    "blind": True,
                    "target": "opponent_player",
                    "lifetime": 2,
                    "timer_seconds": None,
                    "on_timeout": None,
                    "dispute": {"enabled": True, "max": 1},
                    "eligible": {"type": "target_role_match", "params": {}},
                    "constraints": [{"type": "one_per_target", "params": {}}],
                }
            ],
        },
    ],
}

#: Map 1: the sides ban in turn until one map is left, and that map is played. Every later map: the previous game's
#: loser picks it, never on a gamemode the series already played. Map-1 bans last that map only.
MAP_VETO_LOSER_PICKS_NEW_MODE: dict[str, Any] = {
    "version": 2,
    "timer_seconds": 60,
    "on_timeout": "random_fill",
    "phases": [
        {
            "id": "first_map",
            "name": None,
            "when": {"type": "map_index", "params": {"op": "==", "value": 1}},
            "pool_filter": {},
            "generator": "slot_veto",
            "steps": [],
        },
        {
            "id": "next_maps",
            "name": None,
            "when": {},
            "pool_filter": {"NOT": {"type": "group_picked_by", "params": {"by": "any", "scope": "series"}}},
            "generator": None,
            "steps": [{"id": "pick_loser", "action": "pick", "actors": "loser_prev"}],
        },
    ],
}

PRESETS: tuple[Preset, ...] = (
    Preset("hero_classic", "hero", ("pool",), parse_ruleset(HERO_CLASSIC)),
    Preset("hero_protect_ban", "hero", ("pool",), parse_ruleset(HERO_PROTECT_BAN)),
    Preset("hero_blind_2", "hero", ("pool",), parse_ruleset(HERO_BLIND_2)),
    Preset("hero_role_bans", "hero", ("pool",), parse_ruleset(HERO_ROLE_BANS)),
    Preset("hero_anti_one_trick", "hero", ("pool",), parse_ruleset(HERO_ANTI_ONE_TRICK)),
    Preset("map_veto_loser_new_mode", "map", ("progressive",), parse_ruleset(MAP_VETO_LOSER_PICKS_NEW_MODE)),
)


def pick_ban_presets() -> tuple[Preset, ...]:
    return PRESETS
