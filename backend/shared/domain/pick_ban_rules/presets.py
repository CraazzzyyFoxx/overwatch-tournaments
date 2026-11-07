"""Built-in rulesets the constructor offers as a starting point.

Core owns the :class:`Preset` schema and the game-neutral map presets. A game's own rulesets (the character
bans that only make sense against its classes) are declared by its module through
``DisciplineSpec.pick_ban_presets`` and reach the constructor through :func:`presets_for`.

Each preset validates clean for its own kind and modes — ``test_pick_ban_rules_presets`` is the guard, so a preset
can never ship an unsavable ruleset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.core.enums import FirstBanRotation

from .compile import select_phase
from .registry import RoundCtx
from .schema import Ruleset, parse_ruleset


class UnknownDiscipline(LookupError):
    """A discipline code no installed module declares; never answered with another game's presets."""


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    kind: str
    #: Pool modes the preset fits (``pool``/``slots``/``progressive``).
    modes: tuple[str, ...]
    ruleset: Ruleset
    #: The ``PickBanConfig.first_ban_rotation`` value the preset needs, or ``None`` when it leaves the organizer's
    #: rotation alone. The rotation lives outside the ruleset document.
    first_ban_rotation: str | None = None

    def __post_init__(self) -> None:
        if self.first_ban_rotation is not None:
            FirstBanRotation(self.first_ban_rotation)  # ValueError on a spelling the config column rejects

    @property
    def mix_eligible(self) -> bool:
        """Whether a pickup mix may play this preset (spec §8.1).

        A mix plays character presets (kind ``hero``) and every round is map 1 of a Bo1, so only the phase that round
        selects matters. It must ban no player: a per-player ban targets a tournament roster, and a mix seat has none.
        A preset whose per-player bans start on a later map is playable.
        """
        if self.kind != "hero":
            return False
        phase = select_phase(self.ruleset, RoundCtx(round=1, best_of=1, kind=self.kind))
        return phase is None or not any(step.target is not None for step in phase.steps)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "modes": list(self.modes),
            "ruleset": self.ruleset.to_json(),
            "first_ban_rotation": self.first_ban_rotation,
            "mix_eligible": self.mix_eligible,
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

#: Map 1: each side bans one map for the whole series, then the opener picks the first map. Every later map: the
#: previous game's loser picks out of what is left (played maps drop out of a progressive pool by themselves).
MAP_BY_MAP: dict[str, Any] = {
    "version": 2,
    "timer_seconds": 60,
    "on_timeout": "random_fill",
    "phases": [
        {
            "id": "first_map",
            "name": None,
            "when": {"type": "map_index", "params": {"op": "==", "value": 1}},
            "pool_filter": {},
            "generator": None,
            "steps": [
                {"id": "ban_a", "action": "ban", "actors": "first"},
                {"id": "ban_b", "action": "ban", "actors": "second"},
                {"id": "pick_first", "action": "pick", "actors": "first"},
            ],
        },
        {
            "id": "next_maps",
            "name": None,
            "when": {},
            "pool_filter": {},
            "generator": None,
            "steps": [{"id": "pick_loser", "action": "pick", "actors": "loser_prev"}],
        },
    ],
}

#: The presets every game gets: a map pool needs no game-specific vocabulary.
GENERIC_PRESETS: tuple[Preset, ...] = (
    Preset("map_bracket", "map", ("pool",), parse_ruleset(MAP_BRACKET)),
    Preset("map_slot_veto", "map", ("slots",), parse_ruleset(MAP_SLOT_VETO)),
    Preset("map_by_map", "map", ("progressive",), parse_ruleset(MAP_BY_MAP)),
)

GENERIC_PRESETS_BY_ID: dict[str, Preset] = {preset.id: preset for preset in GENERIC_PRESETS}


def presets_for(discipline: str) -> tuple[Preset, ...]:
    """The presets an organizer of ``discipline`` may start from: that module's own, then the generic ones.

    Raises :class:`UnknownDiscipline` for a code no installed module declares, and ``ValueError`` when a module
    declares an id twice or one that shadows a generic preset.
    """
    # Imported on call: ``shared.disciplines`` loads the game modules, which import this package's schema.
    from shared.disciplines import DISCIPLINES

    spec = DISCIPLINES.get(discipline)
    if spec is None:
        raise UnknownDiscipline(discipline)
    own = spec.pick_ban_presets() if spec.pick_ban_presets is not None else ()
    presets = (*own, *GENERIC_PRESETS)
    ids = [preset.id for preset in presets]
    if len(set(ids)) != len(ids):
        raise ValueError(f"discipline {discipline!r} declares a pick-ban preset id more than once: {sorted(ids)}")
    return presets


def mix_ban_preset(discipline: str, code: str) -> Preset | None:
    """The preset ``code`` a pickup mix of ``discipline`` may play (:attr:`Preset.mix_eligible`), or ``None``.

    An unknown game or code answers ``None``, never another game's preset.
    """
    try:
        presets = presets_for(discipline)
    except UnknownDiscipline:
        return None
    return next((preset for preset in presets if preset.id == code and preset.mix_eligible), None)
