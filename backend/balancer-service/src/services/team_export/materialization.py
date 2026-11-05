"""The single writer of ``tournament.team`` + ``tournament.player``.

``on_unresolved`` selects skip-vs-raise for both an unresolvable identity and an
unknown slot code. Substitutes are supported.

This module **never commits** — see :mod:`src.services.team_export.service`
for why the transaction boundary belongs to the orchestrator.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import ApiExc, ApiHTTPException
from shared.disciplines import discipline
from shared.domain.roles import RoleNode
from shared.domain.roster_shape import FLEX_SLOT_CODE
from shared.domain.team_format import export_violations
from shared.models.catalog.role import CatalogRole
from shared.models.identity.user import User
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament.player_role import assignment_of
from shared.models.tournament.team import Player, Team
from shared.models.tournament.tournament import Tournament
from shared.repository import get_or_create_workspace_member
from shared.repository.roles import CatalogRoleRepository
from shared.schemas.role import RoleRef
from shared.services.ontology import rated_leaf, resolve_role_ref
from shared.services.team_format import tournament_format
from src.services.newcomer_status import load_prior_participation
from src.services.team_export.identity import find_users_by_handles

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


def resolve_slot_role(role: str | None, *, discipline_code: str, on_unresolved: OnUnresolved) -> str | None:
    """A module role slot keeps its code; flex is open and holds no assignment."""
    if role is None:
        return None
    normalized = role.lower()
    if normalized == FLEX_SLOT_CODE:
        return None
    if any(item.code == normalized for item in discipline(discipline_code).rated_dimension.roles):
        return normalized
    if on_unresolved == "error":
        raise ApiHTTPException(
            status_code=400,
            detail=[ApiExc(code="invalid_hero_role", msg=f"{role} is not a valid hero role.")],
        )
    return None


@dataclass(frozen=True)
class MaterializationMember:
    """One roster slot to be written as a ``tournament.player`` row.

    Identity is either resolved from ``handle`` -- a handle of the tournament's identity
    provider (balancer/draft/stats imports) -- or supplied pre-resolved as
    ``workspace_member_id`` (registered teams, whose members are already anchored — no
    lookup, and the silently-skipped-player failure mode is unreachable).
    """

    name: str
    #: ``None`` = rank not specified; written as a NULL ``tournament.player.rank``. Every writer (imports, balance,
    #: draft and registered exports, rank re-export) builds this, so a rank <= 0 -- no rank -- is NULL here, once.
    rank: int | None
    slot_code: str | None
    sub_role: str | None = None
    handle: str | None = None
    workspace_member_id: int | None = None
    is_substitute: bool = False
    role_ref: RoleRef | None = None
    non_rated_roles: tuple[CatalogRole, ...] = ()

    def __post_init__(self) -> None:
        if self.rank is not None and self.rank <= 0:
            object.__setattr__(self, "rank", None)

    @property
    def identity_handle(self) -> str | None:
        """The handle to resolve this member by (``name`` unless ``handle`` is set)."""
        if self.workspace_member_id is not None:
            return None
        return self.handle if self.handle is not None else self.name


@dataclass(frozen=True)
class MaterializationTeam:
    """One team to be written as a ``tournament.team`` row.

    ``balancer_name`` is stored verbatim on ``Team.balancer_name`` and doubles as
    the captain's handle; ``Team.name`` is the part before ``#``. Pass
    ``captain_player_id`` to anchor a captain without a handle lookup.
    """

    balancer_name: str
    members: tuple[MaterializationMember, ...] = ()
    captain_handle: str | None = None
    captain_player_id: int | None = None

    @property
    def display_name(self) -> str:
        return self.balancer_name.split("#")[0]

    @property
    def captain_lookup(self) -> str | None:
        if self.captain_player_id is not None:
            return None
        return self.captain_handle if self.captain_handle is not None else self.balancer_name


@dataclass
class MaterializationResult:
    created_teams: list[Team] = field(default_factory=list)
    created_players: int = 0
    skipped_members: int = 0
    advisories: list[str] = field(default_factory=list)


def _require_resolved(handle: str) -> None:
    raise ApiHTTPException(
        status_code=400,
        detail=[ApiExc(code="not_found", msg=f"User with handle {handle} not found.")],
    )


async def materialize_teams(
    session: AsyncSession,
    tournament_id: int,
    formation_node_id: int,
    teams: Sequence[MaterializationTeam],
    *,
    on_unresolved: OnUnresolved = "skip",
) -> MaterializationResult:
    """Create tournament teams and players. Flushes; never commits.

    Front-loads identity/history queries; role pairs are resolved once per distinct
    pair, not per player.

    Idempotent twice over: a team whose lowercased ``name`` already exists in the
    formation node is reused rather than duplicated, and a player already placed in
    the node is never given a second row. New rows carry ``formation_node_id``; what
    other formations of the tournament hold is not looked at.
    """
    result = MaterializationResult()

    tournament = (
        await session.execute(sa.select(Tournament).where(Tournament.id == tournament_id))
    ).scalar_one_or_none()
    if tournament is None:
        logger.warning("Tournament %s not found, skipping materialization", tournament_id)
        return result

    team_format, _ = await tournament_format(session, tournament)
    ontology = await CatalogRoleRepository().ontology(
        session, discipline=tournament.discipline, workspace_id=tournament.workspace_id
    )
    leaves: dict[tuple[str | None, str | None, RoleRef | None], CatalogRole | None] = {}

    # ── Batch phase: resolve everything the build loop needs up front ──────────
    # 1. Resolve every handle (captains + members) in one pass under the tournament's identity
    #    provider. Ordered so a strict caller raises on the first unresolved handle in payload order.
    ordered_handles: list[str] = []
    for team_data in teams:
        for handle in (team_data.captain_lookup, *(m.identity_handle for m in team_data.members)):
            if handle:
                ordered_handles.append(handle)
    users_by_handle = await find_users_by_handles(
        session, ordered_handles, provider=discipline(tournament.discipline).identity_provider
    )
    if on_unresolved == "error":
        for handle in ordered_handles:
            if handle not in users_by_handle:
                _require_resolved(handle)

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
    assignments: dict[int, tuple[CatalogRole, ...]] = {}
    for team_data in teams:
        for member in team_data.members:
            key = (member.slot_code, member.sub_role, member.role_ref)
            if key not in leaves:
                if member.role_ref is not None:
                    leaf = await resolve_role_ref(
                        session,
                        discipline=tournament.discipline,
                        workspace_id=tournament.workspace_id,
                        ref=member.role_ref,
                    )
                    if leaf.parent_role_id is None and member.sub_role:
                        leaf = await rated_leaf(
                            session,
                            discipline=tournament.discipline,
                            workspace_id=tournament.workspace_id,
                            role=leaf.code,
                            sub_role=member.sub_role,
                        )
                else:
                    leaf = await rated_leaf(
                        session,
                        discipline=tournament.discipline,
                        workspace_id=tournament.workspace_id,
                        role=resolve_slot_role(
                            member.slot_code, discipline_code=tournament.discipline, on_unresolved=on_unresolved
                        ),
                        sub_role=member.sub_role,
                    )
                leaves[key] = leaf
            leaf = leaves[key]
            assigned = (() if leaf is None else (leaf,)) + member.non_rated_roles
            assignments[id(member)] = assigned

    resolved_user_ids = {user.id for user in users_by_handle.values()} | set(player_id_by_member_id.values())

    # 2. Batch-load existing teams of this formation node by lowercased name.
    team_names = {team_data.display_name.lower() for team_data in teams}
    existing_teams: dict[str, Team] = {}
    if team_names:
        team_rows = (
            (
                await session.execute(
                    sa.select(Team).where(
                        Team.formation_node_id == formation_node_id,
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
    #    this formation node so a repeat never creates a duplicate row.
    placed_user_ids: set[int] = set()
    starters_by_name: dict[str, list[tuple[RoleNode, ...]]] = {team.display_name.lower(): [] for team in teams}
    team_name_by_id = {team.id: name for name, team in existing_teams.items()}
    members_by_player: dict[int, WorkspaceMember] = {}
    history = await load_prior_participation(session, tournament=tournament, user_ids=resolved_user_ids)
    user_id_list = list(resolved_user_ids)
    if resolved_user_ids or existing_teams:
        player_rows = (
            await session.execute(
                sa.select(WorkspaceMember.player_id, Player)
                .join(Player, Player.workspace_member_id == WorkspaceMember.id)
                .where(
                    Player.formation_node_id == formation_node_id,
                    sa.or_(
                        WorkspaceMember.player_id.in_(user_id_list),
                        Player.team_id.in_(team_name_by_id),
                    ),
                )
            )
        ).all()
        for player_id, player in player_rows:
            placed_user_ids.add(player_id)
            name = team_name_by_id.get(player.team_id)
            if name is not None and not player.is_substitution:
                starters_by_name[name].append(tuple(ontology.by_id(row.role_id) for row in player.assignments))

    if resolved_user_ids:
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

    # Resolve and deduplicate once, in write order, before checking the final roster.
    placements: list[list[tuple[MaterializationMember, int, int | None]]] = []
    for team_data in teams:
        selected: list[tuple[MaterializationMember, int, int | None]] = []
        for member in team_data.members:
            member_id = member.workspace_member_id
            if member_id is not None:
                player_id = player_id_by_member_id.get(member_id)
                if player_id is None and on_unresolved == "error":
                    raise ApiHTTPException(
                        status_code=400,
                        detail=[ApiExc(code="not_found", msg=f"Workspace member {member_id} not found.")],
                    )
            else:
                user = users_by_handle.get(member.identity_handle or "")
                player_id = user.id if user is not None else None
            if player_id is None:
                logger.warning("User %s not found, skipping player creation", member.name)
                result.skipped_members += 1
                result.advisories.append(f"{team_data.display_name}: skipped {member.name} (not found)")
                continue
            if player_id in placed_user_ids:
                logger.info("Player %s already in formation %s, skipping", member.name, formation_node_id)
                result.skipped_members += 1
                result.advisories.append(f"{team_data.display_name}: skipped {member.name} (already in tournament)")
                continue
            placed_user_ids.add(player_id)
            selected.append((member, player_id, member_id))
            if not member.is_substitute:
                starters_by_name[team_data.display_name.lower()].append(
                    tuple(ontology.by_id(row.id) for row in assignments[id(member)])
                )
        placements.append(selected)
    for team_data in teams:
        codes = export_violations(team_format, ontology, starters_by_name[team_data.display_name.lower()])
        if codes:
            if on_unresolved == "error":
                raise ApiHTTPException(
                    status_code=409, detail=[ApiExc(code="team_format_violation", msg=", ".join(codes))]
                )
            result.advisories.append(f"{team_data.display_name}: team_format_violation: {', '.join(codes)}")

    # Build exactly the placements that passed validation.
    for team_data, selected in zip(teams, placements, strict=True):
        name = team_data.display_name
        captain: User | None = None
        captain_id = team_data.captain_player_id
        if captain_id is None:
            captain_lookup = team_data.captain_lookup
            captain = users_by_handle.get(captain_lookup) if captain_lookup else None
            captain_id = captain.id if captain else None

        team = existing_teams.get(name.lower())
        if team is None:
            team = Team(
                name=name,
                balancer_name=team_data.balancer_name,
                tournament_id=tournament_id,
                formation_node_id=formation_node_id,
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

        for member, player_id, member_id in selected:
            assigned = assignments[id(member)]
            leaf = next((row for row in assigned if row.dimension_id == ontology.rated.id), None)
            role = ontology.root(ontology.by_id(leaf.id)).code if leaf is not None else None

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
                    rank=member.rank,
                    assignments=[assignment_of(row) for row in assigned],
                    tournament_id=tournament_id,
                    formation_node_id=formation_node_id,
                    team_id=team.id,
                    # A registration-time substitute has replaced nobody yet, so
                    # the link is NULL and gets set when a real substitution
                    # happens. ``Team.avg_sr``/``total_sr`` filter on
                    # ``is_substitution`` alone, so the exclusion stays correct.
                    is_substitution=member.is_substitute,
                    related_player_id=None,
                    is_newcomer=history.is_newcomer(player_id),
                    is_newcomer_role=history.is_newcomer_role(player_id, role, discipline=tournament.discipline),
                    workspace_member_id=member_id,
                )
            )
            result.created_players += 1
            logger.info("Player %s added to team %s", member.name, team.name)

    return result
