"""The single writer of ``tournament.team`` + ``tournament.player``.

Consolidates two near-duplicate implementations of ``bulk_create_from_balancer``
(``balancer-service/src/services/team.py`` and
``parser-service/src/services/team/flows.py``), which had drifted apart on four
axes. Each divergence is now an explicit parameter rather than an accident of
which service you happened to call:

======================  ==========================  ==========================
Axis                    balancer-service            parser-service
======================  ==========================  ==========================
Unresolvable tag        skipped the player           raised 400 ``not_found``
Unknown slot code       returned ``None``            raised 400
Transaction             committed internally         committed internally
Substitutes             unsupported                  unsupported
======================  ==========================  ==========================

Resolved as: ``on_unresolved`` selects skip-vs-raise for BOTH identity and slot
code (each old caller was uniformly lenient or uniformly strict, so one flag
reproduces both faithfully); the commit moves to the caller; substitutes are
supported.

This function **never commits** — see :mod:`shared.services.team_export.service`
for why the transaction boundary belongs to the orchestrator.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import HeroClass
from shared.core.errors import ApiExc, ApiHTTPException
from shared.domain.player_sub_roles import normalize_sub_role
from shared.domain.roster_shape import FLEX_SLOT_CODE
from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.team import Player, Team
from shared.models.tournament.tournament import Tournament
from shared.repository import get_or_create_workspace_member
from shared.services.newcomer_status import load_prior_participation
from shared.services.team_export.identity import find_users_by_battle_tags

__all__ = (
    "MaterializationMember",
    "MaterializationTeam",
    "MaterializationResult",
    "OnUnresolved",
    "materialize_teams",
    "resolve_slot_role",
)

logger = logging.getLogger(__name__)

OnUnresolved = Literal["skip", "error"]


def resolve_slot_role(role: str | None, *, on_unresolved: OnUnresolved) -> HeroClass | None:
    """Roster slot code -> the role stored on ``tournament.player``.

    ``flex`` is a real slot, not bad input: a role-less roster assigns no game
    role and ``HeroClass.flex`` is how that survives the import.
    """
    if role is None:
        return None
    normalized = role.lower()
    if normalized == "tank":
        return HeroClass.tank
    if normalized == "damage":
        return HeroClass.damage
    if normalized == "support":
        return HeroClass.support
    if normalized == FLEX_SLOT_CODE:
        return HeroClass.flex
    if on_unresolved == "error":
        raise ApiHTTPException(
            status_code=400,
            detail=[ApiExc(code="invalid_hero_role", msg=f"{role} is not a valid hero role.")],
        )
    return None


@dataclass(frozen=True)
class MaterializationMember:
    """One roster slot to be written as a ``tournament.player`` row.

    Identity is either resolved from ``battle_tag`` (balancer/draft/parser
    imports) or supplied pre-resolved as ``workspace_member_id`` (registered
    teams, whose members are already anchored — no tag lookup, and the
    silently-skipped-player failure mode is unreachable).
    """

    name: str
    rank: int
    slot_code: str | None
    sub_role: str | None = None
    battle_tag: str | None = None
    workspace_member_id: int | None = None
    is_substitute: bool = False

    @property
    def identity_tag(self) -> str | None:
        """The tag to resolve this member by; ``name`` is the historical default."""
        if self.workspace_member_id is not None:
            return None
        return self.battle_tag if self.battle_tag is not None else self.name


@dataclass(frozen=True)
class MaterializationTeam:
    """One team to be written as a ``tournament.team`` row.

    ``balancer_name`` is stored verbatim on ``Team.balancer_name`` and is also,
    by long-standing convention, the captain's battle tag; ``Team.name`` is the
    part before ``#``. Pass ``captain_player_id`` to anchor a captain without a
    tag lookup.
    """

    balancer_name: str
    members: tuple[MaterializationMember, ...] = ()
    captain_battle_tag: str | None = None
    captain_player_id: int | None = None

    @property
    def display_name(self) -> str:
        # ``str.split`` cannot raise; the old callers wrapped this in a
        # ``try/except ValueError`` that could never fire.
        return self.balancer_name.split("#")[0]

    @property
    def captain_tag(self) -> str | None:
        if self.captain_player_id is not None:
            return None
        return self.captain_battle_tag if self.captain_battle_tag is not None else self.balancer_name


@dataclass
class MaterializationResult:
    created_teams: list[Team] = field(default_factory=list)
    created_players: int = 0
    skipped_members: int = 0


def _require_resolved(tag: str) -> None:
    raise ApiHTTPException(
        status_code=400,
        detail=[ApiExc(code="not_found", msg=f"User with battle tag {tag} not found.")],
    )


async def materialize_teams(
    session: AsyncSession,
    tournament_id: int,
    teams: Sequence[MaterializationTeam],
    *,
    on_unresolved: OnUnresolved = "skip",
) -> MaterializationResult:
    """Create tournament teams and players. Flushes; never commits.

    Front-loads a handful of batch queries and makes only in-memory decisions
    plus INSERTs in the build loop — the per-player query fan this replaced was
    O(players x 5) round-trips.

    Idempotent twice over: a team whose lowercased ``name`` already exists in the
    tournament is reused rather than duplicated, and a player already placed in
    the tournament is never given a second row.
    """
    result = MaterializationResult()

    tournament = (
        await session.execute(sa.select(Tournament).where(Tournament.id == tournament_id))
    ).scalar_one_or_none()
    if tournament is None:
        logger.warning("Tournament %s not found, skipping materialization", tournament_id)
        return result

    # ── Batch phase: resolve everything the build loop needs up front ──────────
    # 1. Resolve every battle tag (captains + members) in one pass. Ordered so a
    #    strict caller raises on the same tag it always did.
    ordered_tags: list[str] = []
    for team_data in teams:
        for tag in (team_data.captain_tag, *(m.identity_tag for m in team_data.members)):
            if tag:
                ordered_tags.append(tag)
    users_by_tag = await find_users_by_battle_tags(session, ordered_tags)
    if on_unresolved == "error":
        for tag in ordered_tags:
            if tag not in users_by_tag:
                _require_resolved(tag)

    # Pre-resolved members (registered teams) come in as workspace_member ids;
    # the newcomer + dedup logic below is keyed on the domain player id.
    pre_resolved_member_ids = {
        m.workspace_member_id for t in teams for m in t.members if m.workspace_member_id is not None
    }
    player_id_by_member_id: dict[int, int] = {}
    if pre_resolved_member_ids:
        rows = (
            await session.execute(
                sa.select(WorkspaceMember.id, WorkspaceMember.player_id).where(
                    WorkspaceMember.id.in_(list(pre_resolved_member_ids))
                )
            )
        ).all()
        player_id_by_member_id = dict(rows)

    resolved_user_ids = {user.id for user in users_by_tag.values()} | set(player_id_by_member_id.values())

    # 2. Batch-load existing teams for this tournament by lowercased name.
    team_names = {team_data.display_name.lower() for team_data in teams}
    existing_teams: dict[str, Team] = {}
    if team_names:
        team_rows = (
            (
                await session.execute(
                    sa.select(Team).where(
                        Team.tournament_id == tournament_id,
                        sa.func.lower(Team.name).in_(list(team_names)),
                    )
                )
            )
            .scalars()
            .all()
        )
        for team in team_rows:
            existing_teams.setdefault(team.name.lower(), team)

    # 3. ``load_prior_participation`` answers the newcomer question separately
    #    (chronological, scope-aware); one more query finds players already in
    #    this tournament so a repeat never creates a duplicate row.
    players_in_tournament: set[int] = set()
    members_by_player: dict[int, WorkspaceMember] = {}
    history = await load_prior_participation(session, tournament=tournament, user_ids=resolved_user_ids)
    if resolved_user_ids:
        user_id_list = list(resolved_user_ids)
        player_rows = (
            await session.execute(
                sa.select(WorkspaceMember.player_id, Player.tournament_id)
                .join(Player, Player.workspace_member_id == WorkspaceMember.id)
                .where(WorkspaceMember.player_id.in_(user_id_list))
            )
        ).all()
        for player_id, player_tournament_id in player_rows:
            if player_tournament_id == tournament_id:
                players_in_tournament.add(player_id)

        # 4. Batch-load existing workspace members for these users.
        member_rows = (
            (
                await session.execute(
                    sa.select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == tournament.workspace_id,
                        WorkspaceMember.player_id.in_(user_id_list),
                    )
                )
            )
            .scalars()
            .all()
        )
        for member_row in member_rows:
            members_by_player[member_row.player_id] = member_row

    # ── Build phase: in-memory decisions + INSERTs only ────────────────────────
    placed_user_ids: set[int] = set(players_in_tournament)

    for team_data in teams:
        name = team_data.display_name
        captain: User | None = None
        captain_id = team_data.captain_player_id
        if captain_id is None:
            captain_tag = team_data.captain_tag
            captain = users_by_tag.get(captain_tag) if captain_tag else None
            captain_id = captain.id if captain else None

        team = existing_teams.get(name.lower())
        if team is None:
            team = Team(
                name=name,
                balancer_name=team_data.balancer_name,
                tournament_id=tournament_id,
                captain_id=captain_id,
            )
            session.add(team)
            # Flush per new team only (a dozen INSERTs, not hundreds of SELECTs)
            # so ``team.id`` is available for the roster rows below.
            await session.flush()
            existing_teams[name.lower()] = team
            result.created_teams.append(team)
            logger.info("Team %s created in tournament %s", name, tournament_id)
        else:
            logger.info("Team %s already exists in tournament %s, skipping", name, tournament_id)

        for member in team_data.members:
            if member.workspace_member_id is not None:
                player_id = player_id_by_member_id.get(member.workspace_member_id)
                if player_id is None:
                    if on_unresolved == "error":
                        raise ApiHTTPException(
                            status_code=400,
                            detail=[
                                ApiExc(
                                    code="not_found",
                                    msg=f"Workspace member {member.workspace_member_id} not found.",
                                )
                            ],
                        )
                    result.skipped_members += 1
                    continue
                member_id = member.workspace_member_id
            else:
                user = users_by_tag.get(member.identity_tag or "")
                if user is None:
                    # Unreachable when ``on_unresolved == "error"`` (validated above).
                    logger.warning("User %s not found, skipping player creation", member.name)
                    result.skipped_members += 1
                    continue
                player_id = user.id
                member_id = None

            if player_id in placed_user_ids:
                logger.info("Player %s already in tournament %s, skipping", member.name, tournament_id)
                continue

            role = resolve_slot_role(member.slot_code, on_unresolved=on_unresolved)

            if member_id is None:
                workspace_member = members_by_player.get(player_id)
                if workspace_member is None:
                    workspace_member = await get_or_create_workspace_member(
                        session, workspace_id=tournament.workspace_id, player_id=player_id
                    )
                    members_by_player[player_id] = workspace_member
                member_id = workspace_member.id

            session.add(
                Player(
                    name=member.name,
                    sub_role=normalize_sub_role(member.sub_role),
                    rank=member.rank,
                    role=role,
                    tournament_id=tournament_id,
                    team_id=team.id,
                    # A registration-time substitute has replaced nobody yet, so
                    # the link is NULL and gets set when a real substitution
                    # happens. ``Team.avg_sr``/``total_sr`` filter on
                    # ``is_substitution`` alone, so the exclusion stays correct.
                    is_substitution=member.is_substitute,
                    related_player_id=None,
                    is_newcomer=history.is_newcomer(player_id),
                    is_newcomer_role=history.is_newcomer_role(player_id, role),
                    workspace_member_id=member_id,
                )
            )
            placed_user_ids.add(player_id)
            result.created_players += 1
            logger.info("Player %s added to team %s", member.name, team.name)

    return result
