"""Eager-load option sets for draft rows.

dbarch03 re-anchored draft identity on ``workspace_member`` and normalized the
per-role JSON into child tables, so the compatibility read properties
(``DraftPlayer.user_id`` / ``role_ranks`` / ``secondary_roles_json`` /
``role_top_heroes``, ``DraftTeam.captain_user_id``, ``DraftPick.picked_by_user_id``)
now read relationships. Async code must eager-load those relationships — a lazy
load would raise ``MissingGreenlet`` — so every draft-row query/``session.get``
passes the matching option set from here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import selectinload

from shared.models.balancer.draft import (
    DraftPick,
    DraftPlayer,
    DraftPlayerRole,
    DraftPlayerRoleHero,
    DraftTeam,
)

__all__ = ("player_options", "team_options", "pick_options")


def player_options() -> list[Any]:
    """Everything ``DraftPlayer``'s read properties touch: member + roles(+heroes)."""
    return [
        selectinload(DraftPlayer.member),
        selectinload(DraftPlayer.roles)
        .selectinload(DraftPlayerRole.hero_entries)
        .selectinload(DraftPlayerRoleHero.hero),
    ]


def team_options() -> list[Any]:
    """``DraftTeam.captain_user_id`` reads ``captain_member``."""
    return [selectinload(DraftTeam.captain_member)]


def pick_options() -> list[Any]:
    """``DraftPick.picked_by_user_id`` reads ``picked_by_member``."""
    return [selectinload(DraftPick.picked_by_member)]
