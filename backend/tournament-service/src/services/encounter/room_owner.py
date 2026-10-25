"""Who owns a pick-ban room, and what that owner lets a caller do there (spec §4.4, §8.2).

D77 keeps a mix round out of every read model (``EncounterRepository``); the pick-ban, readiness and chat paths are
the exceptions and load through here. A tournament room answers to its tournament (hidden-tournament rule,
``match.result``); a mix room is public to watch and run by the mix's hosts. Imports no service: ``pick_ban_session``
reads the mix config from here.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core import http_status as status
from shared.core.enums import FirstBanRotation, MapVetoMode, PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.pick_ban_rules import mix_ban_preset
from shared.models.encounter.encounter import Encounter
from shared.models.tournament.pick_ban import PickBanConfig, PickBanConfigItem
from shared.repository import EncounterRepository
from shared.rpc.identity import ensure_workspace_permission
from shared.services.mix_hosts import is_mix_host
from shared.services.tournament.visibility import ensure_tournament_viewable

__all__ = (
    "ensure_room_organizer",
    "ensure_room_viewable",
    "load_room_encounter",
    "mix_ban_config",
    "mix_fearless_exclusions",
)

_encounters = EncounterRepository()


async def load_room_encounter(session: AsyncSession, encounter_id: int, *, for_update: bool) -> Encounter:
    """The room's encounter, whichever owner; 404 when there is none. Locked for a write, plain for a read."""
    encounter = (
        await _encounters.get_any_owner_for_update(session, encounter_id)
        if for_update
        else await _encounters.get_any_owner(session, encounter_id)
    )
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    return encounter


async def ensure_room_viewable(session: AsyncSession, auth_user: Any, encounter: Encounter) -> None:
    """A tournament room is visible as its tournament is; a mix room to everyone (spec §4.4)."""
    if encounter.custom_game_id is None:
        await ensure_tournament_viewable(session, auth_user, encounter.tournament_id)


async def ensure_room_organizer(session: AsyncSession, auth_user: Any, encounter_id: int) -> int:
    """The room's workspace once ``auth_user`` may run it: workspace ``match.result`` for a tournament room, a host
    of the mix for a mix room (spec §7.3). 404 for an unknown encounter, 403 otherwise."""
    owner = (
        await session.execute(
            sa.select(Encounter.workspace_id, Encounter.custom_game_id).where(Encounter.id == encounter_id)
        )
    ).first()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    if owner.custom_game_id is None:
        ensure_workspace_permission(auth_user, owner.workspace_id, "match", "result")
    elif not await is_mix_host(session, auth_user, owner.custom_game_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the mix's host or a co-host runs this room"
        )
    return int(owner.workspace_id)


async def mix_ban_config(session: AsyncSession, encounter: Encounter, kind: PickBanKind) -> PickBanConfig | None:
    """A mix room's config (spec §8.1): the hero ban preset Start froze on the match's lobby
    (``mix.lobby.live_ban_preset``) over the game's active characters; no map room.

    The frozen copy, not the mix's ``hero_ban_preset``: a header edit after Start -- or a room reset -- keeps the
    preset the match started on. Transient -- never added to the session: the room snapshots the ruleset and the
    pool when it opens, and nothing reads this object again. ``None`` when the match plays without bans.

    The mix's clocks, when set, replace the timer of every step they cover: ``hero_ban_seconds`` a ban's and a
    protect's, ``hero_pick_seconds`` a pick's; a side pick or an assignment keeps the preset's own. Read as the room
    opens, like Fearless (:func:`mix_fearless_exclusions`). So are the pickers: ``hero_free_order`` turns every
    turn-by-turn pick (member ``next``) into a free-order one (``any``), ``hero_captains_only`` marks every member pick
    ``captains_only``.
    """
    if kind != PickBanKind.HERO:
        return None
    row = (
        await session.execute(
            sa.select(
                models.CustomGameLobby.live_ban_preset,
                models.CustomGame.hero_ban_seconds,
                models.CustomGame.hero_pick_seconds,
                models.CustomGame.hero_free_order,
                models.CustomGame.hero_captains_only,
            )
            .join(models.CustomGame, models.CustomGame.id == models.CustomGameLobby.custom_game_id)
            .where(models.CustomGameLobby.live_encounter_id == encounter.id)
        )
    ).one_or_none()
    if row is None or row.live_ban_preset is None:
        return None
    preset = mix_ban_preset(encounter.discipline, row.live_ban_preset)
    if preset is None:
        return None
    clocks = {"ban": row.hero_ban_seconds, "protect": row.hero_ban_seconds, "pick": row.hero_pick_seconds}
    ruleset = preset.ruleset.to_json()
    for phase in ruleset["phases"]:
        for step in phase["steps"]:
            if clocks.get(step["action"]) is not None:
                step["timer_seconds"] = clocks[step["action"]]
            if row.hero_free_order and step.get("member") == "next":
                step["member"] = "any"
            if row.hero_captains_only and step.get("member") is not None:
                step["captains_only"] = True
    heroes = (
        await session.scalars(
            sa.select(models.CatalogEntity.id)
            .where(
                models.CatalogEntity.discipline == encounter.discipline,
                models.CatalogEntity.kind == "character",
                models.CatalogEntity.active.is_(True),
            )
            .order_by(models.CatalogEntity.id)
        )
    ).all()
    return PickBanConfig(
        kind=PickBanKind.HERO,
        mode=MapVetoMode.POOL,
        first_ban_rotation=FirstBanRotation(preset.first_ban_rotation or FirstBanRotation.FIXED.value),
        ruleset_json=ruleset,
        items=[PickBanConfigItem(item_id=hero_id, sort_order=index) for index, hero_id in enumerate(heroes)],
        slots=[],
    )


async def mix_fearless_exclusions(session: AsyncSession, encounter: Encounter) -> dict[int, set[int]]:
    """``{seat of this match (encounter.team_member id): heroes it may not pick}`` (spec §11.4, §11.6 R4-8): every
    hero picked for the same player in a recorded round of this mix -- any lobby, any team, since mix teams
    reshuffle. Empty unless the mix plays Fearless. An undone round's encounter is gone, and its heroes with it."""
    fearless = await session.scalar(
        sa.select(models.CustomGame.hero_fearless).where(models.CustomGame.id == encounter.custom_game_id)
    )
    if not fearless:
        return {}
    now = aliased(models.EncounterTeamMember)
    then = aliased(models.EncounterTeamMember)
    rows = await session.execute(
        sa.select(now.id, models.PickBanEntry.item_id)
        .join(then, then.workspace_member_id == now.workspace_member_id)
        .join(models.PickBanEntry, models.PickBanEntry.picked_for_member_id == then.id)
        .join(models.CustomGameRound, models.CustomGameRound.encounter_id == then.encounter_id)
        .join(models.Encounter, models.Encounter.id == then.encounter_id)
        .where(now.encounter_id == encounter.id, models.Encounter.custom_game_id == encounter.custom_game_id)
    )
    exclusions: dict[int, set[int]] = {}
    for member_id, hero_id in rows.all():
        exclusions.setdefault(member_id, set()).add(hero_id)
    return exclusions
