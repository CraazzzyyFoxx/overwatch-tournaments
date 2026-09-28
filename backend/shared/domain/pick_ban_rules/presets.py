"""Built-in rulesets the constructor offers as a starting point (§6, §12).

Each one validates clean for its own kind and modes — ``test_pick_ban_rules_presets``
is the guard, so a preset can never ship an unsavable ruleset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import Ruleset, parse_ruleset


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    kind: str
    #: Pool modes the preset fits (``pool``/``slots``).
    modes: tuple[str, ...]
    ruleset: Ruleset

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "modes": list(self.modes),
            "ruleset": self.ruleset.to_json(),
        }


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

#: The 2026-10-03 tournament rules, verbatim from the design (§12).
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

MAP_BRACKET: dict[str, Any] = {
    "version": 2,
    "timer_seconds": 60,
    "on_timeout": "random_fill",
    "phases": [{"id": "main", "name": None, "when": {}, "pool_filter": {}, "generator": "bracket", "steps": []}],
}

MAP_SLOT_VETO: dict[str, Any] = {
    "version": 2,
    "timer_seconds": 60,
    "on_timeout": "random_fill",
    "phases": [{"id": "main", "name": None, "when": {}, "pool_filter": {}, "generator": "slot_veto", "steps": []}],
}


PRESETS: list[Preset] = [
    Preset("hero_classic", "hero", ("pool",), parse_ruleset(HERO_CLASSIC)),
    Preset("hero_protect_ban", "hero", ("pool",), parse_ruleset(HERO_PROTECT_BAN)),
    Preset("hero_blind_2", "hero", ("pool",), parse_ruleset(HERO_BLIND_2)),
    Preset("hero_role_bans", "hero", ("pool",), parse_ruleset(HERO_ROLE_BANS)),
    Preset("hero_anti_one_trick", "hero", ("pool",), parse_ruleset(HERO_ANTI_ONE_TRICK)),
    Preset("map_bracket", "map", ("pool",), parse_ruleset(MAP_BRACKET)),
    Preset("map_slot_veto", "map", ("slots",), parse_ruleset(MAP_SLOT_VETO)),
]

PRESETS_BY_ID: dict[str, Preset] = {preset.id: preset for preset in PRESETS}
