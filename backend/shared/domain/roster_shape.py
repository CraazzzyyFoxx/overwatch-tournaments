"""Per-team roster shape: how many slots of which kind one team has.

The single source of truth for team composition across draft, balancer and UI.
A slot code is either a registration role (``tank``/``damage``/``support``) or the
reserved ``flex`` code, meaning "any role fits this slot".

Deliberately pure: no I/O, no service imports. Looking a shape up for a
tournament or workspace, and caching that lookup, lives elsewhere.

Slot counts are stored as a tuple of pairs rather than a mapping so a shape stays
hashable, JSON-serializable, deep-copyable and picklable -- it travels through
Pydantic into a JSONB column. ``slots`` and ``role_slots`` hand out fresh plain
dicts, so mutating what you get back cannot corrupt the shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES

__all__ = (
    "DEFAULT_ROSTER_SHAPE",
    "DEFAULT_ROSTER_SLOTS",
    "FLEX_SLOT_CODE",
    "MAX_TEAM_SIZE",
    "MIN_TEAM_SIZE",
    "ROSTER_SLOT_CODES",
    "RegistrationRoleCode",
    "RosterShape",
    "RosterShapeError",
    "RosterSlotCode",
    "parse_roster_slots",
    "resolve_roster_shape",
)

FLEX_SLOT_CODE: Final[str] = "flex"
ROSTER_SLOT_CODES: Final[tuple[str, ...]] = (*REGISTRATION_ROLE_CODES, FLEX_SLOT_CODE)
#: The same vocabulary as a static type, for Pydantic contracts that carry one
#: slot code (the balancer/draft export payloads). Spelled out because a
#: ``Literal`` cannot be derived from a tuple; ``test_roster_shape`` pins the two
#: against each other so they cannot drift.
RosterSlotCode = Literal["tank", "damage", "support", "flex"]
#: ``RosterSlotCode`` minus ``flex`` -- for fields that can never be flex (a
#: player's fixed registration/draft role; flex is a separate ``is_flex``
#: boolean there). Also the single Pydantic-facing type for ``HeroClass``'s
#: :attr:`~shared.core.enums.HeroClass.slot_code`. Pinned against
#: ``REGISTRATION_ROLE_CODES`` by ``test_roster_shape`` for the same reason.
RegistrationRoleCode = Literal["tank", "damage", "support"]

DEFAULT_ROSTER_SLOTS: Final[Mapping[str, int]] = MappingProxyType({"tank": 1, "damage": 2, "support": 2})
# A roster shape is a tournament's team format, not a draft setting: 1v1 is a
# legal format. A draft refuses a shape it has nothing to pick for on its own
# (balancer-service ``DraftLifecycleService.create_session``).
MIN_TEAM_SIZE: Final[int] = 1
# Upper bound inherited from the validator this shape replaces:
# DraftSessionCreateRequest._team_size_range in balancer-service/src/schemas/draft.py.
MAX_TEAM_SIZE: Final[int] = 12


class RosterShapeError(ValueError):
    """An invalid roster slot map, carrying a machine-readable ``code``.

    Subclasses ``ValueError`` so Pydantic ``field_validator`` bodies can let it
    propagate as a validation error instead of a 500.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _validate_team_size(team_size: int) -> None:
    if not MIN_TEAM_SIZE <= team_size <= MAX_TEAM_SIZE:
        raise RosterShapeError(
            "roster_slots_out_of_range",
            f"Roster size {team_size} is outside {MIN_TEAM_SIZE}..{MAX_TEAM_SIZE}",
        )


@dataclass(frozen=True)
class RosterShape:
    """Normalized per-team slot counts: canonical order, no zero entries.

    ``__post_init__`` enforces that invariant, so direct construction and
    ``parse_roster_slots`` offer the same guarantees.
    """

    entries: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise RosterShapeError(
                "roster_slots_not_canonical",
                f"Roster shape entries must be a tuple of (slot code, count) pairs, got {type(self.entries).__name__}",
            )
        if not self.entries:
            raise RosterShapeError(
                "roster_slots_empty",
                "A roster shape needs at least one slot with a positive count",
            )

        previous_index = -1
        for code, count in self.entries:
            if code not in ROSTER_SLOT_CODES:
                raise RosterShapeError(
                    "roster_slots_unknown_code",
                    f"Unknown roster slot code {code!r}; valid codes are {', '.join(ROSTER_SLOT_CODES)}",
                )
            # bool is an int subclass -- True would silently pass as 1.
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise RosterShapeError(
                    "roster_slots_invalid_count",
                    f"Roster slot {code!r} must be a positive integer, got {count!r}",
                )
            index = ROSTER_SLOT_CODES.index(code)
            if index <= previous_index:
                raise RosterShapeError(
                    "roster_slots_not_canonical",
                    f"Roster slots must be unique and ordered as {', '.join(ROSTER_SLOT_CODES)}",
                )
            previous_index = index

        _validate_team_size(self.team_size)

    @property
    def slots(self) -> dict[str, int]:
        """A fresh mutable copy of the slot counts, in canonical order."""
        return dict(self.entries)

    @property
    def team_size(self) -> int:
        return sum(count for _, count in self.entries)

    @property
    def flex_slots(self) -> int:
        return next((count for code, count in self.entries if code == FLEX_SLOT_CODE), 0)

    @property
    def role_slots(self) -> dict[str, int]:
        return {code: count for code, count in self.entries if code != FLEX_SLOT_CODE}

    @property
    def has_role_slots(self) -> bool:
        """False only when every slot is ``flex`` -- the role-less roster.

        This is the switch that hides role counters, role filters and role
        validation. Zero counts are rejected outright, so it can never be
        confused by ``{"tank": 0, "flex": 6}``.
        """
        return any(code != FLEX_SLOT_CODE for code, _ in self.entries)

    @property
    def draft_rounds(self) -> int:
        """Picks this shape needs: the captain already fills one slot.

        ``0`` for a one-slot roster -- such a tournament simply cannot run a draft.
        """
        return self.team_size - 1


def parse_roster_slots(raw: Any) -> RosterShape:
    """Validate and normalize a raw slot map into a ``RosterShape``."""
    if not isinstance(raw, Mapping):
        raise RosterShapeError(
            "roster_slots_not_a_map",
            f"Roster slots must be a mapping of slot code to count, got {type(raw).__name__}",
        )

    counts: dict[str, int] = {}
    for code, value in raw.items():
        if code not in ROSTER_SLOT_CODES:
            raise RosterShapeError(
                "roster_slots_unknown_code",
                f"Unknown roster slot code {code!r}; valid codes are {', '.join(ROSTER_SLOT_CODES)}",
            )
        # bool is an int subclass -- True would silently pass as 1.
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RosterShapeError(
                "roster_slots_invalid_count",
                f"Roster slot {code!r} must be a non-negative integer, got {value!r}",
            )
        if value > 0:
            counts[code] = value

    if not counts:
        raise RosterShapeError(
            "roster_slots_empty",
            "A roster shape needs at least one slot with a positive count",
        )

    # Size is validated by RosterShape.__post_init__ on the normalized entries.
    return RosterShape(entries=tuple((code, counts[code]) for code in ROSTER_SLOT_CODES if code in counts))


# Parsed at import time, so the canonical default is proven valid on module load
# and callers falling back to it never have to re-parse.
DEFAULT_ROSTER_SHAPE: Final[RosterShape] = parse_roster_slots(DEFAULT_ROSTER_SLOTS)


def resolve_roster_shape(tournament_slots: Any, workspace_slots: Any) -> RosterShape:
    """Tournament override -> workspace default -> built-in Overwatch 5v5.

    ``None`` and an empty mapping both mean "no value at this level, keep
    looking", so a cleared override inherits. Any other value is validated:
    corrupt stored config raises instead of silently degrading to the default.
    """
    for candidate in (tournament_slots, workspace_slots):
        if candidate is None:
            continue
        if isinstance(candidate, RosterShape):
            return candidate
        if isinstance(candidate, Mapping) and not candidate:
            continue
        return parse_roster_slots(candidate)
    return DEFAULT_ROSTER_SHAPE
