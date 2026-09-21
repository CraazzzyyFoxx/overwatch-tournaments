"""Shared test-double builders for balancer-service.

Every balancer test module used to hand-roll its own ``make_player``/``MASK``
pair with the same 1/2/2 Tank/Damage/Support role mask and the same
``name=f"P{uuid}"`` convention, diverging only in whether ``ratings`` or
``preferences`` was the required argument. Centralized here so the mapping
onto ``src.domain.balancer.entities.Player`` only needs to match once.

``roster`` does the same for the draft side: after ``draftreg1`` a draft seat
carries no roles or ranks of its own, so every draft test needs a
``PlayerRoster`` -- the engine's answer -- instead of a ``DraftPlayer`` with
role columns. One builder, so "declared but unranked" (rank ``None``, which is
what makes a role unplayable) is spelled the same way everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.core.enums import HeroClass
from shared.domain.roster import HeroRef, PlayerRoster, RosterRole
from src.domain.balancer.entities import Player

#: Default Tank/Damage/Support role mask shared by every test that doesn't
#: care about a custom roster shape.
DEFAULT_MASK: dict[str, int] = {"Tank": 1, "Damage": 2, "Support": 2}


def make_player(
    uuid: str,
    ratings: dict[str, int] | None = None,
    preferences: list[str] | None = None,
    *,
    extra_roles: list[str] | None = None,
    is_flex: bool = False,
    mask: dict[str, int] | None = None,
) -> Player:
    """Build a ``Player`` test double.

    Pass ``ratings`` directly (``preferences`` defaults to its keys), or pass
    only ``preferences`` to derive ratings automatically: preferred roles get
    2000, ``extra_roles`` (playable but not preferred -- used for flex
    coverage) get 1500.
    """
    if ratings is None:
        if preferences is None:
            raise ValueError("make_player requires ratings or preferences")
        ratings = dict.fromkeys(preferences, 2000)
        for role in extra_roles or []:
            ratings.setdefault(role, 1500)
    elif extra_roles:
        raise ValueError("extra_roles only applies when deriving ratings from preferences")
    if preferences is None:
        preferences = list(ratings.keys())
    return Player(
        name=f"P{uuid}",
        ratings=ratings,
        preferences=preferences,
        uuid=uuid,
        mask=mask or DEFAULT_MASK,
        is_flex=is_flex,
    )


#: Distinguishes "the test does not care about the battle tag" from an explicit
#: ``battle_tag=None`` -- a registration genuinely without one, which is what
#: makes the draft team name fall back to the seat's own name.
_UNSET = object()


def roster(
    registration_id: int,
    *,
    ranks: Mapping[str, int | None] | None = None,
    primary: str | None = None,
    flex: bool = False,
    battle_tag: str | None | object = _UNSET,
    display_name: str | None = None,
    player_id: int | None = None,
    auth_user_id: int | None = None,
    workspace_member_id: int | None = None,
    subroles: Mapping[str, str] | None = None,
    sources: Mapping[str, str] | None = None,
    top_heroes: Mapping[str, tuple[HeroRef, ...]] | None = None,
    public_notes: str | None = None,
    admin_notes: str | None = None,
    custom_fields: Mapping[str, Any] | None = None,
) -> PlayerRoster:
    """Build the engine's answer for one registration.

    ``ranks`` is ``{slot_code: rank}`` in priority order; a ``None`` rank means
    the role is DECLARED but not playable, which is the whole point of the value
    object and the case every draft surface has to survive. ``primary`` names
    the lead role (default: the first key). ``battle_tag`` defaults to
    ``P<registration_id>#1`` so a test that only cares about identity says
    nothing about it; pass ``None`` for a registration that really has none.
    """
    entries = ranks if ranks is not None else {}
    lead = primary if primary is not None else next(iter(entries), None)
    return PlayerRoster(
        registration_id=registration_id,
        battle_tag=f"P{registration_id}#1" if battle_tag is _UNSET else battle_tag,  # type: ignore[arg-type]
        display_name=display_name,
        player_id=player_id,
        auth_user_id=auth_user_id,
        workspace_member_id=workspace_member_id,
        roles=tuple(
            RosterRole(
                role=HeroClass.from_slot_code(code),
                rank=rank,
                source=(sources or {}).get(code, "registration" if rank is not None else "none"),
                is_primary=code == lead,
                priority=priority,
                subrole=(subroles or {}).get(code),
                top_heroes=(top_heroes or {}).get(code, ()),
            )
            for priority, (code, rank) in enumerate(entries.items())
        ),
        is_full_flex=flex,
        public_notes=public_notes,
        admin_notes=admin_notes,
        custom_fields=dict(custom_fields or {}),
    )
