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

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import SocialProvider
from shared.domain.roster import CharacterRef, PlayerRoster, RosterRole
from shared.schemas.identity import PlayerIdentityRead
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


#: Distinguishes "the test does not care about the handle" from an explicit
#: ``handle=None`` -- a registration genuinely without one, which is what
#: makes the draft team name fall back to the seat's own name.
_UNSET = object()


def roster(
    registration_id: int,
    *,
    ranks: Mapping[str, int | None] | None = None,
    primary: str | None = None,
    flex: bool = False,
    handle: str | None | object = _UNSET,
    display_name: str | None = None,
    player_id: int | None = None,
    player_name: str | None = None,
    auth_user_id: int | None = None,
    workspace_member_id: int | None = None,
    subroles: Mapping[str, str] | None = None,
    sources: Mapping[str, str] | None = None,
    top_characters: Mapping[str, tuple[CharacterRef, ...]] | None = None,
    public_notes: str | None = None,
    admin_notes: str | None = None,
    custom_fields: Mapping[str, Any] | None = None,
) -> PlayerRoster:
    """Build the engine's answer for one registration.

    ``ranks`` is ``{slot_code: rank}`` in priority order; a ``None`` rank means
    the role is DECLARED but not playable, which is the whole point of the value
    object and the case every draft surface has to survive. ``primary`` names
    the lead role (default: the first key). ``handle`` (a Battle.net handle) defaults to
    ``P<registration_id>#1`` so a test that only cares about identity says
    nothing about it; pass ``None`` for a registration that really has none.
    """
    entries = ranks if ranks is not None else {}
    lead = primary if primary is not None else next(iter(entries), None)
    return PlayerRoster(
        registration_id=registration_id,
        identity=PlayerIdentityRead.of(
            SocialProvider.BATTLENET,
            f"P{registration_id}#1" if handle is _UNSET else handle,  # type: ignore[arg-type]
        ),
        display_name=display_name,
        player_id=player_id,
        player_name=player_name,
        auth_user_id=auth_user_id,
        workspace_member_id=workspace_member_id,
        roles=tuple(
            RosterRole(
                role=code,
                rank=rank,
                source=(sources or {}).get(code, "registration" if rank is not None else "none"),
                is_primary=code == lead,
                priority=priority,
                subrole=(subroles or {}).get(code),
                top_characters=(top_characters or {}).get(code, ()),
            )
            for priority, (code, rank) in enumerate(entries.items())
        ),
        is_full_flex=flex,
        public_notes=public_notes,
        admin_notes=admin_notes,
        custom_fields=dict(custom_fields or {}),
    )


async def formation_node(
    session: AsyncSession, tournament_id: int, *, status: str = "forming", mode: str = "balancer"
) -> int:
    """A formation node of the tournament (flushed, not committed): what a balance, a draft or a team now belongs to."""
    node = models.FlowNode(
        tournament_id=tournament_id, kind="formation", name="Teams", status=status, config={"mode": mode}
    )
    session.add(node)
    await session.flush()
    return node.id


async def wire_input(session: AsyncSession, node_id: int) -> int:
    """Feed ``node_id`` an (empty) registration node's ``participants`` output; the registration node's id."""
    tournament_id = await session.scalar(sa.select(models.FlowNode.tournament_id).where(models.FlowNode.id == node_id))
    registration = models.FlowNode(tournament_id=tournament_id, kind="registration", name="R", status="closed")
    session.add(registration)
    await session.flush()
    session.add(
        models.FlowEdge(
            tournament_id=tournament_id,
            source_node_id=registration.id,
            source_port="participants",
            target_node_id=node_id,
            target_port="players",
        )
    )
    await session.flush()
    return registration.id


async def add_input(session: AsyncSession, registration_node_id: int, member_id: int) -> None:
    """Put the workspace member on the registration node's ``participants`` output, after everyone already there."""
    taken = await session.scalar(
        sa.select(sa.func.count())
        .select_from(models.FlowNodeResult)
        .where(models.FlowNodeResult.node_id == registration_node_id)
    )
    session.add(
        models.FlowNodeResult(
            node_id=registration_node_id,
            port="participants",
            rank=taken + 1,
            workspace_member_id=member_id,
            state="final",
        )
    )
    await session.flush()


async def new_member(session: AsyncSession, workspace_id: int, name: str) -> tuple[int, int]:
    """A player and its workspace member (flushed): ``(member id, user id)``; the caller deletes the user."""
    user = models.User(name=name)
    session.add(user)
    await session.flush()
    member = models.WorkspaceMember(workspace_id=workspace_id, player_id=user.id)
    session.add(member)
    await session.flush()
    return member.id, user.id
