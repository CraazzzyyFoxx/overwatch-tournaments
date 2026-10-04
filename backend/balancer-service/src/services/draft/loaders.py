"""Eager-load option sets for draft rows.

``DraftPlayer`` no longer carries roles or ranks (``draftreg1`` deleted the
snapshot), so what has to be eager-loaded is its identity: the member behind
``user_id``. The registration itself is NOT loaded here -- nothing reads
``DraftPlayer.registration``, and the roster engine selects the registrations
it resolves itself, so eager-loading them alongside the seats only re-ran the
engine's own five queries and threw the rows away (2026-09-30).

Async code must eager-load these; a lazy load would raise ``MissingGreenlet``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import selectinload

from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftTeam

__all__ = ("pick_options", "player_options", "team_options")


def player_options() -> list[Any]:
    """The member behind ``user_id``. Roles and ranks come from the roster engine."""
    return [selectinload(DraftPlayer.member)]


def team_options() -> list[Any]:
    """``DraftTeam.captain_user_id`` reads ``captain_member``."""
    return [selectinload(DraftTeam.captain_member)]


def pick_options() -> list[Any]:
    """``DraftPick.picked_by_user_id`` reads ``picked_by_member``."""
    return [selectinload(DraftPick.picked_by_member)]
