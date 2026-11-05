"""Eager-load option sets for draft rows, and the owner-dependent reads (spec §9.1).

A draft session belongs to a tournament or to one lobby of a mix. Its discipline is a column of the session; the
roster shape and the role-impact knobs differ by owner and are answered here; ranks and roles by ``rosters``, the
draft's only door to them. Nothing else in the draft branches on the owner.

Async code must eager-load these; a lazy load would raise ``MissingGreenlet``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.disciplines import DISCIPLINES
from shared.domain.roster_shape import RosterShape
from shared.models.catalog import CatalogRole
from shared.models.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.repository import CatalogRoleRepository, CustomGameRepository, UserBalancerConfigRepository
from shared.repository.balance import BalancerTournamentConfigRepository
from shared.services.team_format import custom_game_slot_shape, tournament_slot_shape

__all__ = ("pick_options", "player_options", "rated_dimension", "rated_rows", "role_overrides", "shape", "team_options")

_games = CustomGameRepository()
_host_configs = UserBalancerConfigRepository()
_tournament_configs = BalancerTournamentConfigRepository()


def player_options() -> list[Any]:
    """The member behind ``user_id``. Roles and ranks come from ``rosters``."""
    return [selectinload(DraftPlayer.member)]


def team_options() -> list[Any]:
    """``DraftTeam.captain_user_id`` reads ``captain_member``."""
    return [selectinload(DraftTeam.captain_member)]


def pick_options() -> list[Any]:
    """``DraftPick.picked_by_user_id`` reads ``picked_by_member``."""
    return [selectinload(DraftPick.picked_by_member)]


async def rated_rows(session: AsyncSession, draft_session: DraftSession) -> dict[str, CatalogRole]:
    return await CatalogRoleRepository().rated_rows(session, discipline=draft_session.discipline, workspace_id=None)


async def rated_dimension(session: AsyncSession, draft_session: DraftSession) -> str:
    return DISCIPLINES[draft_session.discipline].rated_dimension.code


async def shape(session: AsyncSession, draft_session: DraftSession) -> RosterShape:
    """The roster shape the draft's teams fill: the tournament's format, or the mix's frozen one."""
    if draft_session.tournament_id is not None:
        return await tournament_slot_shape(session, draft_session.tournament_id)
    return await custom_game_slot_shape(session, await _games.get(session, draft_session.custom_game_id))


async def role_overrides(session: AsyncSession, draft_session: DraftSession) -> dict[str, Any] | None:
    """The stored balancer knobs the draft's role impacts start from: the formation node's config, or the mix host's own
    (spec §9.1). ``None`` leaves the discipline defaults."""
    if draft_session.tournament_id is not None:
        stored = await _tournament_configs.get_by_formation_node(session, draft_session.formation_node_id)
        return stored.config_json if stored is not None else None
    game = await _games.get(session, draft_session.custom_game_id)
    host = await _host_configs.get_by_user(session, game.host_user_id) if game.host_user_id is not None else None
    return host.config_json if host is not None else None
