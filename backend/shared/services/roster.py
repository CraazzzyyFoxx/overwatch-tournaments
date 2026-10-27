"""The one resolver of "which roles does this registration play, and at what rank".

    RosterEngine.for_tournament(session, tournament_id)
        -> {registration_id: PlayerRoster}

Everything downstream -- admin list, pool verdict, balancer algorithm input,
draft pool, draft board, feasibility, autopick, draft export -- projects those
value objects. No consumer touches ``registration_role.rank_value``,
``member_rank`` or the snapshot tables directly, and no consumer keeps a copy;
the only stored derivation is the ``(role, rank)`` a completed draft pick
freezes as a historical fact.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from typing import Any, NamedTuple

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from shared.core.social import display_social_handle
from shared.disciplines import identity_provider, rated_role_codes
from shared.division_grid import DivisionGrid
from shared.domain.member_rank import RankScope, ResolvedRank
from shared.domain.player_sub_roles import workspace_sub_role_slug
from shared.domain.roster import CharacterRef, PlayerRoster, RosterRole, flex_role_mode
from shared.domain.roster_shape import RosterShape
from shared.models.catalog import CatalogRole
from shared.models.catalog.entity import CatalogEntity
from shared.models.identity.user import User
from shared.models.registration.registration import (
    Registration,
    RegistrationForm,
    RegistrationIdentity,
    RegistrationRole,
    RegistrationRoleEntity,
)
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament import Tournament
from shared.registration_statuses import balancer_pool_included_clause
from shared.repository import TournamentRepository
from shared.schemas.identity import PlayerIdentityRead
from shared.schemas.role import RoleRef
from shared.services.division_grid.access import get_effective_division_grid
from shared.services.member_rank import TOURNAMENT_ORDER, MemberRankService, member_rank_service

__all__ = ("RosterEngine", "registration_load_options", "roster_engine")


def registration_load_options() -> list[Any]:
    """Everything the engine reads off a registration, eager-loaded.

    A caller that already selects registrations for its own reasons passes these
    so :meth:`RosterEngine.resolve` never lazy-loads (which would raise
    ``MissingGreenlet`` in async code).
    """
    return [
        selectinload(Registration.roles)
        .selectinload(RegistrationRole.hero_entries)
        .selectinload(RegistrationRoleEntity.entity),
        selectinload(Registration.workspace_member).selectinload(WorkspaceMember.player),
        selectinload(Registration.identities),
        selectinload(Registration.form_version),
    ]


def _primary_tag_order(provider: str) -> sa.ScalarSelect[str]:
    """The event provider's primary handle, as a correlated scalar.

    Joining would multiply registrations that carry several handles.
    """
    return (
        sa.select(RegistrationIdentity.handle_normalized)
        .where(
            RegistrationIdentity.registration_id == Registration.id,
            RegistrationIdentity.provider == provider,
            RegistrationIdentity.position == 0,
        )
        .limit(1)
        .correlate(Registration)
        .scalar_subquery()
    )


def _pool_clauses(tournament_id: int) -> tuple[Any, ...]:
    """The balancer pool predicate, exactly as the panel defines it."""
    return (
        Registration.status == "approved",
        Registration.deleted_at.is_(None),
        balancer_pool_included_clause(
            Registration.balancer_status,
            sa.select(Tournament.workspace_id).where(Tournament.id == tournament_id).scalar_subquery(),
        ),
    )


def _any_of(column: Any, ids: Iterable[int]) -> Any:
    """``column = ANY(:ids)``: one array parameter where ``IN`` binds one per id, so the statement text is the same
    at any count and the driver reuses its prepared (asyncpg) or converted (psycopg) form of it."""
    return column == sa.any_(sa.literal(list(ids), ARRAY(sa.Integer)))


def _character_refs(role: RegistrationRole) -> tuple[CharacterRef, ...]:
    return tuple(
        CharacterRef(id=entry.entity.id, slug=entry.entity.slug, image_path=entry.entity.image_path)
        for entry in sorted(role.hero_entries or [], key=lambda entry: entry.priority)
        if entry.entity is not None
    )


class _Person(NamedTuple):
    """Who a registration's workspace member is, as its roster carries it."""

    player_id: int | None
    auth_user_id: int | None
    player_name: str | None

    @classmethod
    def of(cls, member: WorkspaceMember | None) -> _Person | None:
        """Off a loaded ``workspace_member -> player`` chain (``registration_load_options``)."""
        if member is None:
            return None
        player = member.player
        return cls(
            member.player_id,
            player.auth_user_id if player is not None else None,
            player.name if player is not None else None,
        )


class _Member(NamedTuple):
    """One row of :meth:`RosterEngine._members`: the member's workspace, which the rank layers check, and its person."""

    workspace_id: int
    person: _Person


@dataclass(slots=True)
class _RoleRow:
    """A ``RegistrationRole`` as :meth:`RosterEngine.for_tournament` reads it: what the engine reads off one, with
    the ``role``/``subrole`` hybrids folded in."""

    id: int
    role: str
    subrole: str | None
    priority: int
    is_primary: bool
    is_active: bool
    rank_value: int | None


@dataclass(slots=True)
class _IdentityRow:
    provider: str
    position: int
    handle: str


@dataclass(slots=True)
class _RegistrationRow:
    """A ``Registration`` as :meth:`RosterEngine.for_tournament` reads it: the columns and collections the engine
    reads off one loaded with ``registration_load_options``, as plain rows. ``resolve`` takes either."""

    id: int
    workspace_member_id: int | None
    display_name: str | None
    public_notes: str | None
    admin_notes: str | None
    custom_fields_json: dict[str, Any] | None
    status: str
    balancer_status: str
    exclude_reason: str | None
    checked_in: bool
    registration_team_id: int | None
    team_slot_code: str | None
    is_substitute: bool
    stream_pov: bool
    roles: list[_RoleRow] = field(init=False, default_factory=list)
    identities: list[_IdentityRow] = field(init=False, default_factory=list)

    def primary_game_identity(self, *, provider: str) -> _IdentityRow | None:
        """``Registration.primary_game_identity``."""
        return next((row for row in self.identities if row.provider == provider and row.position == 0), None)


#: The ``Registration`` columns behind a ``_RegistrationRow``, in its field order.
_REGISTRATION_COLUMNS = tuple(getattr(Registration, column.name) for column in fields(_RegistrationRow) if column.init)

type _Registration = Registration | _RegistrationRow
type _Role = RegistrationRole | _RoleRow


class RosterEngine:
    def __init__(
        self,
        *,
        ranks: MemberRankService = member_rank_service,
        tournaments: TournamentRepository = TournamentRepository(),
    ) -> None:
        self.ranks = ranks
        self.tournaments = tournaments

    # -- entry points --------------------------------------------------------

    async def for_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        pool_only: bool = False,
        registration_ids: Sequence[int] | None = None,
        include_deleted: bool = False,
    ) -> dict[int, PlayerRoster]:
        """Every registration of a tournament, resolved. The one entry point.

        ``pool_only`` narrows to the balancer pool exactly as the panel defines it
        (approved, not deleted, and a ``balancer_status`` that does not exclude) --
        this is what the draft seeds from and what the balance job balances.
        """
        row = (
            await session.execute(
                sa.select(Tournament.workspace_id, Tournament.discipline).where(Tournament.id == tournament_id)
            )
        ).one_or_none()
        if row is None:
            return {}
        workspace_id, discipline = row
        # Plain Core rows, no ORM: building the objects for the registrations, their roles and identities, a role's
        # top characters and the member's player was most of a load's time, for values read once.
        query = (
            sa.select(*_REGISTRATION_COLUMNS)
            .where(Registration.tournament_id == tournament_id)
            .order_by(_primary_tag_order(identity_provider(discipline)).asc(), Registration.id.asc())
        )
        if not include_deleted:
            query = query.where(Registration.deleted_at.is_(None))
        if pool_only:
            query = query.where(*_pool_clauses(tournament_id))
        if registration_ids is not None:
            if not registration_ids:
                return {}
            query = query.where(_any_of(Registration.id, registration_ids))

        registrations = [_RegistrationRow(*values) for values in await session.execute(query)]
        await self._collections(session, registrations)
        return await self.resolve(
            session,
            registrations,
            workspace_id=workspace_id,
            tournament_id=tournament_id,
            discipline=discipline,
            role_codes=rated_role_codes(discipline),
            characters=await self._characters(session, [role.id for reg in registrations for role in reg.roles]),
            members=await self._members(
                session, {reg.workspace_member_id for reg in registrations if reg.workspace_member_id is not None}
            ),
        )

    async def pool_ids(self, session: AsyncSession, tournament_id: int, registration_ids: Sequence[int]) -> set[int]:
        """Which of these registrations the balancer pool includes -- ids only.

        For a caller that resolves several leniencies at once: narrowing with
        this and then resolving the union in ONE :meth:`for_tournament` pass
        costs one cheap id query instead of a second full engine run.
        """
        if not registration_ids:
            return set()
        rows = await session.scalars(
            sa.select(Registration.id).where(
                Registration.tournament_id == tournament_id,
                _any_of(Registration.id, registration_ids),
                *_pool_clauses(tournament_id),
            )
        )
        return set(rows)

    async def resolve(
        self,
        session: AsyncSession,
        registrations: Sequence[_Registration],
        *,
        workspace_id: int | None,
        tournament_id: int | None = None,
        form: RegistrationForm | None = None,
        grid: DivisionGrid | None = None,
        order: Sequence[RankScope] = TOURNAMENT_ORDER,
        author_user_id: int | None = None,
        role_codes: Sequence[str] | None = None,
        discipline: str | None = None,
        characters: Mapping[int, tuple[CharacterRef, ...]] | None = None,
        members: Mapping[int, _Member] | None = None,
    ) -> dict[int, PlayerRoster]:
        """Resolve already-loaded registrations. Rows must carry
        :func:`registration_load_options`.

        ``form``/``grid`` are read from the tournament when omitted; pass them when
        the caller already holds them (the admin list does) to save two queries.
        ``characters`` (by registration role id) and ``members`` (by workspace
        member id) are :meth:`for_tournament`'s own Core reads; without them both
        come off the rows.
        """
        if not registrations:
            return {}
        if tournament_id is None:
            tournament_id = next((reg.tournament_id for reg in registrations), None)
        if role_codes is None or discipline is None:
            tournament = await self.tournaments.get(session, tournament_id)
            discipline = discipline or tournament.discipline
            role_codes = role_codes or rated_role_codes(discipline)
        if form is None and tournament_id is not None:
            form = await session.scalar(
                sa.select(RegistrationForm)
                # ``flex_role_mode`` reads the schema off the current version,
                # which is never lazy-loadable in async code.
                .options(selectinload(RegistrationForm.current_version))
                .where(RegistrationForm.tournament_id == tournament_id)
            )
        mode = flex_role_mode(form)
        if grid is None:
            grid = await get_effective_division_grid(session, workspace_id, tournament_id, discipline=discipline)

        declared = {reg.id: self._declared_roles(reg, mode=mode, role_codes=role_codes) for reg in registrations}
        resolved = await self._resolve_ranks(
            session,
            registrations,
            declared=declared,
            workspace_id=workspace_id,
            discipline=discipline,
            grid=grid,
            order=order,
            author_user_id=author_user_id,
            members=members,
        )
        provider = identity_provider(discipline)
        return {
            reg.id: self._build(
                reg,
                declared[reg.id],
                resolved.get(reg.id, {}),
                mode=mode,
                provider=provider,
                characters=characters,
                members=members,
            )
            for reg in registrations
        }

    # -- role set ------------------------------------------------------------

    def _declared_roles(self, reg: _Registration, *, mode: str, role_codes: Sequence[str]) -> tuple[_Role | str, ...]:
        """The roles this registration declares, in priority order.

        ``optional``: the active rows, as written. ``all_roles``/``forced``: the
        rows in the registrant's order (primary first), then every role with no
        row at all synthesized after them in canonical order -- role is not a
        constraint there, so a row the sheet import left inactive (its rank did
        not parse) still names a role the player can be drafted on. A bare
        string in the result is such a synthesized role. The registrant's
        own priority is never replaced by the module order: it is what the
        balancer's discomfort is built from. A registration with no rows gets no
        lead -- there is nobody's choice to stand in for.
        """
        rows = sorted(reg.roles or [], key=lambda row: (row.priority, row.id or 0))
        by_role: dict[str, RegistrationRole] = {}
        for row in rows:
            role = row.role
            if role not in role_codes or role in by_role:
                continue
            if mode == "optional" and not row.is_active:
                continue
            by_role[role] = row
        declared = sorted(by_role.values(), key=lambda row: not row.is_primary)
        if mode == "optional":
            return tuple(declared)
        return (*declared, *(role for role in role_codes if role not in by_role))

    # -- ranks ---------------------------------------------------------------

    async def _resolve_ranks(
        self,
        session: AsyncSession,
        registrations: Sequence[_Registration],
        *,
        declared: Mapping[int, tuple[_Role | str, ...]],
        workspace_id: int | None,
        discipline: str,
        grid: DivisionGrid | None,
        order: Sequence[RankScope],
        author_user_id: int | None,
        members: Mapping[int, _Member] | None,
    ) -> dict[int, dict[str, ResolvedRank]]:
        """``{registration_id: {role: ResolvedRank}}`` under ``order``.

        The registration's own number is one layer among several: an empty
        ``rank_value`` *inherits* the workspace canon and then the discipline's native ladder
        rather than reading as "unranked". Without a workspace
        (no tournament in hand) or without a member (no identity to inherit
        through) only that own layer exists.
        """
        own: dict[int, dict[str, int | None]] = {}
        member_of: dict[int, int] = {}
        for reg in registrations:
            entries = declared.get(reg.id, ())
            own[reg.id] = {
                (entry if isinstance(entry, str) else entry.role): (
                    None if isinstance(entry, str) else entry.rank_value
                )
                for entry in entries
            }
            if reg.workspace_member_id is not None and own[reg.id]:
                member_of[reg.id] = reg.workspace_member_id

        if workspace_id is None or not member_of:
            return {
                registration_id: {
                    role: ResolvedRank(value, "registration" if value is not None else "none")
                    for role, value in roles.items()
                }
                for registration_id, roles in own.items()
            }

        roles_wanted = sorted({role for roles in own.values() for role in roles})
        players = (
            await self._players_by_member(session, workspace_id=workspace_id, member_ids=list(member_of.values()))
            if members is None
            else {
                member_id: members[member_id].person.player_id
                for member_id in set(member_of.values())
                if member_id in members and members[member_id].workspace_id == workspace_id
            }
        )
        resolved = await self.ranks.resolve(
            session,
            workspace_id=workspace_id,
            discipline=discipline,
            members=players,
            roles=roles_wanted,
            order=order,
            author_user_id=author_user_id,
            registration_ranks={
                (member_id, role): value
                for registration_id, member_id in member_of.items()
                for role, value in own[registration_id].items()
                if value is not None
            },
            grid=grid,
        )

        out: dict[int, dict[str, ResolvedRank]] = {}
        for registration_id, roles in own.items():
            # The own layer doubles as the fallback, so a member the workspace
            # filter rejected cannot blank out the number the organiser typed.
            fallback = {
                role: ResolvedRank(value, "registration" if value is not None else "none")
                for role, value in roles.items()
            }
            member_id = member_of.get(registration_id)
            out[registration_id] = (
                fallback
                if member_id is None
                else {role: resolved.get((member_id, role), rank) for role, rank in fallback.items()}
            )
        return out

    async def _players_by_member(
        self, session: AsyncSession, *, workspace_id: int, member_ids: Sequence[int]
    ) -> dict[int, int | None]:
        """``{workspace_member_id: players.user.id}`` -- what the Overwatch layer keys on."""
        if not member_ids:
            return {}
        rows = await session.execute(
            sa.select(WorkspaceMember.id, WorkspaceMember.player_id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.id.in_(sorted(set(member_ids))),
            )
        )
        return dict(rows.all())

    async def _collections(self, session: AsyncSession, registrations: Sequence[_RegistrationRow]) -> None:
        """Fill each row's ``roles`` and ``identities``, one query each. A role's ``role``/``subrole`` fold its leaf
        and parent codes the way the ``RegistrationRole`` hybrids' Python side does; joined here, where the hybrids'
        SQL side is two correlated subqueries per row."""
        by_id = {reg.id: reg for reg in registrations}
        if not by_id:
            return
        parent = aliased(CatalogRole)
        roles = await session.execute(
            sa.select(
                RegistrationRole.registration_id,
                RegistrationRole.id,
                CatalogRole.code,
                parent.code,
                RegistrationRole.priority,
                RegistrationRole.is_primary,
                RegistrationRole.is_active,
                RegistrationRole.rank_value,
            )
            .join(CatalogRole, CatalogRole.id == RegistrationRole.role_id)
            .outerjoin(parent, parent.id == CatalogRole.parent_role_id)
            .where(_any_of(RegistrationRole.registration_id, by_id))
        )
        for registration_id, role_id, leaf, parent_code, *flags in roles:
            role, subrole = (leaf, None) if parent_code is None else (parent_code, leaf)
            by_id[registration_id].roles.append(_RoleRow(role_id, role, subrole, *flags))
        identities = await session.execute(
            sa.select(
                RegistrationIdentity.registration_id,
                RegistrationIdentity.provider,
                RegistrationIdentity.position,
                RegistrationIdentity.handle,
            )
            .where(_any_of(RegistrationIdentity.registration_id, by_id))
            # ``Registration.identities``' own order.
            .order_by(
                RegistrationIdentity.registration_id, RegistrationIdentity.provider, RegistrationIdentity.position
            )
        )
        for registration_id, *identity in identities:
            by_id[registration_id].identities.append(_IdentityRow(*identity))

    async def _characters(self, session: AsyncSession, role_ids: Sequence[int]) -> dict[int, tuple[CharacterRef, ...]]:
        """``{registration_role_id: top characters}``, in the registrant's order: ``_character_refs`` off a loaded
        ``hero_entries -> entity`` chain, in one query."""
        if not role_ids:
            return {}
        rows = await session.execute(
            sa.select(RegistrationRoleEntity.role_id, CatalogEntity.id, CatalogEntity.slug, CatalogEntity.image_path)
            .join(CatalogEntity, CatalogEntity.id == RegistrationRoleEntity.entity_id)
            .where(_any_of(RegistrationRoleEntity.role_id, role_ids))
            .order_by(RegistrationRoleEntity.role_id, RegistrationRoleEntity.priority)
        )
        characters: dict[int, list[CharacterRef]] = {}
        for role_id, entity_id, slug, image_path in rows:
            characters.setdefault(role_id, []).append(CharacterRef(id=entity_id, slug=slug, image_path=image_path))
        return {role_id: tuple(refs) for role_id, refs in characters.items()}

    async def _members(self, session: AsyncSession, member_ids: Collection[int]) -> dict[int, _Member]:
        """Each workspace member with its player, in one query: ``_build``'s person and ``_resolve_ranks``' member ->
        player map, where the ``workspace_member -> player`` chain and ``_players_by_member`` took three."""
        if not member_ids:
            return {}
        rows = await session.execute(
            sa.select(
                WorkspaceMember.id,
                WorkspaceMember.workspace_id,
                WorkspaceMember.player_id,
                User.auth_user_id,
                User.name,
            )
            .outerjoin(User, User.id == WorkspaceMember.player_id)
            .where(_any_of(WorkspaceMember.id, member_ids))
        )
        return {
            member_id: _Member(workspace_id, _Person(player_id, auth_user_id, name))
            for member_id, workspace_id, player_id, auth_user_id, name in rows
        }

    # -- assembly ------------------------------------------------------------

    def _build(
        self,
        reg: _Registration,
        declared: tuple[_Role | str, ...],
        resolved: Mapping[str, ResolvedRank],
        *,
        mode: str,
        provider: str,
        characters: Mapping[int, tuple[CharacterRef, ...]] | None,
        members: Mapping[int, _Member] | None,
    ) -> PlayerRoster:
        entries: list[RosterRole] = []
        from_row: set[str] = set()
        for priority, entry in enumerate(declared):
            row = None if isinstance(entry, str) else entry
            role = entry if isinstance(entry, str) else entry.role
            if row is not None:
                from_row.add(role)
            rank = resolved.get(role, ResolvedRank(None, "none"))
            entries.append(
                RosterRole(
                    role=role,
                    rank=rank.value,
                    source=rank.source,
                    is_primary=bool(row.is_primary) if row is not None else False,
                    priority=priority,
                    subrole=row.subrole if row is not None else None,
                    top_characters=(
                        ()
                        if row is None
                        else _character_refs(row)
                        if characters is None
                        else characters.get(row.id, ())
                    ),
                )
            )

        if mode != "optional":
            # Role stops being a constraint: every role the tournament runs is
            # playable, so a role no layer ranked inherits the player's strongest
            # number -- the balancer's eligibility for a role IS having one. A role
            # with its own rating keeps it, because the draft's role chooser SHOWS it.
            best = max((entry.rank for entry in entries if entry.is_playable), default=None)
            if best is not None:
                entries = [
                    entry if entry.is_playable else RosterRole(**{**_as_dict(entry), "rank": best}) for entry in entries
                ]

        # THE flex predicate. Over the roles the player actually declared AND can
        # play -- the raw ``registration_role`` rows also count inactive/unranked
        # ones, which would send a single-role tank to the balancer as
        # ``isFullFlex``. Synthesized roles carry no ``is_primary`` and must not
        # veto an ``all_roles`` registrant who marked every declared role primary.
        # ``forced`` makes every role primary by contract, whether or not the rows
        # were rewritten since the form flipped to it.
        declared_playable = [entry for entry in entries if entry.is_playable and entry.role in from_row]
        playable_count = sum(1 for entry in entries if entry.is_playable)
        is_full_flex = (
            playable_count > 1
            if mode == "forced"
            else len(declared_playable) > 1 and all(entry.is_primary for entry in declared_playable)
        )

        if members is None:
            person = _Person.of(reg.workspace_member)
        else:
            member = members.get(reg.workspace_member_id)
            person = member.person if member is not None else None
        primary = reg.primary_game_identity(provider=provider)
        return PlayerRoster(
            registration_id=reg.id,
            identity=PlayerIdentityRead.of(provider, primary.handle if primary is not None else None),
            display_name=reg.display_name,
            player_id=person.player_id if person is not None else None,
            auth_user_id=person.auth_user_id if person is not None else None,
            player_name=person.player_name if person is not None else None,
            workspace_member_id=reg.workspace_member_id,
            roles=tuple(entries),
            is_full_flex=is_full_flex,
            public_notes=reg.public_notes,
            admin_notes=reg.admin_notes,
            custom_fields=dict(reg.custom_fields_json or {}),
            status=reg.status,
            balancer_status=reg.balancer_status,
            exclude_reason=reg.exclude_reason,
            checked_in=bool(reg.checked_in),
            registration_team_id=reg.registration_team_id,
            team_slot_code=reg.team_slot_code,
            is_substitute=bool(reg.is_substitute),
            identities={identity.provider: identity.handle for identity in reg.identities if identity.position == 0},
            stream_pov=bool(reg.stream_pov),
            additional_handles=tuple(
                display_social_handle(provider, row.handle)
                for row in sorted(reg.identities, key=lambda row: row.position)
                if row.provider == provider and row.position > 0
            ),
        )

    # -- algorithm input -----------------------------------------------------

    def balancer_input(
        self,
        rosters: Iterable[PlayerRoster],
        *,
        key: str = "registration_id",
    ) -> dict[str, Any]:
        """The balancer algorithm's ``xv-1`` payload, built from the same rosters.

        ``key`` names the field the result's player uuids carry, so the caller can
        map a solved team back.
        """
        players: dict[str, Any] = {}
        for roster in rosters:
            if not roster.is_draftable:
                continue
            players[str(getattr(roster, key))] = {
                "identity": {
                    "name": _export_name(roster),
                    "isFullFlex": roster.is_full_flex,
                },
                "stats": {
                    "classes": {
                        entry.role: {
                            "isActive": True,
                            "rank": entry.rank,
                            "priority": entry.priority,
                            "subtype": workspace_sub_role_slug(entry.role, entry.subrole) if entry.subrole else None,
                        }
                        for entry in roster.playable
                    }
                },
            }
        return {"format": "xv-1", "players": players}

    # -- full snapshot -------------------------------------------------------

    def full_export(
        self,
        rosters: Iterable[PlayerRoster],
        *,
        shape: RosterShape,
        flex_role_mode: str,
        dimension: str,
        grid: DivisionGrid | None = None,
        source: Mapping[str, Any] | None = None,
        key: str = "registration_id",
        include_private: bool = False,
    ) -> dict[str, Any]:
        """``owt-1``: everything the roster projection knows, losslessly.

        A STRICT SUPERSET of :meth:`balancer_input`. Every player node still
        carries the ``xv-1`` ``identity``/``stats.classes`` pair verbatim, and
        ``player_loader.parse_player_node`` reads nothing else, so an ``owt-1``
        file uploads into the balance-job endpoint unchanged -- pinned by
        ``balancer-service/tests/test_owt_export_is_solver_input``.

        Two deliberate widenings over ``xv-1``:

        * declared-but-unranked roles are emitted with ``isActive: false``
          instead of being dropped, which is what makes the file answer "is this
          player ranked yet". The loader tests ``isActive`` BEFORE it compares
          the rank, so a ``null`` rank cannot reach its ``rank <= 0``.
        * ``roster`` carries the shape the run would use, flex slot included.
          The solver takes the flex mask from the tournament rather than the
          file, so without it an export cannot be replayed.
        """
        players: dict[str, Any] = {}
        for roster in rosters:
            primary = roster.primary
            owt: dict[str, Any] = {
                "registration_id": roster.registration_id,
                "identity": roster.identity.model_dump() if roster.identity is not None else None,
                "display_name": roster.display_name,
                "player_id": roster.player_id,
                "auth_user_id": roster.auth_user_id,
                "workspace_member_id": roster.workspace_member_id,
                "is_full_flex": roster.is_full_flex,
                # What a role-less (flex) slot is worth for this player -- the
                # same "best playable rank" the solver synthesizes for it.
                "flex_rating": roster.best_rank,
                "draftable": roster.is_draftable,
                "ranked_complete": roster.is_ranked_complete,
                "primary_role": RoleRef.of(dimension, primary.role, primary.subrole).model_dump()
                if primary is not None
                else None,
                "status": roster.status,
                "balancer_status": roster.balancer_status,
                "checked_in": roster.checked_in,
                "registration_team_id": roster.registration_team_id,
                "team_slot_code": roster.team_slot_code,
                "is_substitute": roster.is_substitute,
                "roles": [_role_export(entry, grid, dimension=dimension) for entry in roster.roles],
            }
            if include_private:
                owt["private"] = {
                    "public_notes": roster.public_notes,
                    "admin_notes": roster.admin_notes,
                    "exclude_reason": roster.exclude_reason,
                    "custom_fields": dict(roster.custom_fields),
                    "identities": dict(roster.identities),
                    "stream_pov": roster.stream_pov,
                    "additional_handles": list(roster.additional_handles),
                }
            players[str(getattr(roster, key))] = {
                "identity": {
                    "name": _export_name(roster),
                    "isFullFlex": roster.is_full_flex,
                },
                "stats": {
                    "classes": {
                        entry.role: {
                            "isActive": entry.is_playable,
                            "rank": entry.rank,
                            "priority": entry.priority,
                            "subtype": workspace_sub_role_slug(entry.role, entry.subrole) if entry.subrole else None,
                        }
                        for entry in roster.roles
                    }
                },
                "owt": owt,
            }
        return {
            "format": "owt-1",
            "generated_at": datetime.now(UTC).isoformat(),
            "source": {"player_key": key, **dict(source or {})},
            "roster": {
                "slots": shape.slots,
                "team_size": shape.team_size,
                "flex_slots": shape.flex_slots,
                "flex_role_mode": flex_role_mode,
            },
            "players": players,
        }


def _as_dict(entry: RosterRole) -> dict[str, Any]:
    return {
        "role": entry.role,
        "rank": entry.rank,
        "source": entry.source,
        "is_primary": entry.is_primary,
        "priority": entry.priority,
        "subrole": entry.subrole,
        "top_characters": entry.top_characters,
    }


def _export_name(roster: PlayerRoster) -> str:
    return roster.handle or roster.display_name or f"registration-{roster.registration_id}"


def _role_export(entry: RosterRole, grid: DivisionGrid | None, *, dimension: str) -> dict[str, Any]:
    # A tier-less grid is a legitimate workspace state (nobody configured one);
    # ``resolve_division`` raises on it, and a decorative label is never worth
    # failing the export for.
    resolvable = grid is not None and bool(grid.tiers) and entry.rank is not None
    tier = grid.resolve_division(entry.rank) if resolvable else None  # type: ignore[union-attr, arg-type]
    return {
        "role": RoleRef.of(dimension, entry.role, entry.subrole).model_dump(),
        "rank": entry.rank,
        "source": entry.source,
        "is_primary": entry.is_primary,
        "priority": entry.priority,
        "playable": entry.is_playable,
        "division": None if tier is None else {"number": tier.number, "name": tier.name},
        "top_characters": [character.wire() for character in entry.top_characters],
    }


roster_engine = RosterEngine()
