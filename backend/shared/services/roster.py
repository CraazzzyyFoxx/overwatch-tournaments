"""THE engine: one place that answers "which roles does this registration play,
and at what rank".

Before this module the same question had five independent answers -- the admin
registration serializer, ``registration/_common``'s ready/incomplete verdict,
the browser's ``buildBalancerInput``, ``tournament-service`` ``export.py``, and
balancer-service's ``draft/rules.map_registration``. Two of them read the raw
``balancer.registration_role.rank_value`` column and three read the resolved
value, so a player ranked only through the workspace canon or an Overwatch
snapshot was fully ranked in the balancer and blank in the draft.

Now there is one call path and therefore one failure mode:

    RosterEngine.for_tournament(session, tournament_id)
        -> {registration_id: PlayerRoster}

Everything downstream -- admin list, pool verdict, balancer algorithm input,
draft pool, draft board, feasibility, autopick, draft export -- projects those
value objects. No consumer touches ``registration_role.rank_value``,
``member_rank`` or the snapshot tables directly, and no consumer keeps a copy;
the only stored derivation left in the system is the ``(role, rank)`` a
completed draft pick freezes as a historical fact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.balancer_registration_statuses import balancer_pool_included_clause
from shared.core.enums import HERO_TYPE_CLASSES, HeroClass
from shared.division_grid import DivisionGrid
from shared.domain.member_rank import RankScope, ResolvedRank
from shared.domain.roster import HeroRef, PlayerRoster, RosterRole, flex_role_mode
from shared.domain.roster_shape import RosterShape
from shared.models.registration.registration import (
    BalancerRegistration,
    BalancerRegistrationForm,
    BalancerRegistrationRole,
    BalancerRegistrationRoleHero,
)
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament import Tournament
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
        selectinload(BalancerRegistration.roles)
        .selectinload(BalancerRegistrationRole.hero_entries)
        .selectinload(BalancerRegistrationRoleHero.hero),
        selectinload(BalancerRegistration.workspace_member).selectinload(WorkspaceMember.player),
    ]


def _hero_refs(role: BalancerRegistrationRole) -> tuple[HeroRef, ...]:
    return tuple(
        HeroRef(id=entry.hero.id, slug=entry.hero.slug, image_path=entry.hero.image_path)
        for entry in sorted(role.hero_entries or [], key=lambda entry: entry.priority)
        if entry.hero is not None
    )


def _parse_role(code: str | None) -> HeroClass | None:
    """A registration role code; ``flex`` is a roster SLOT, never a rated role."""
    parsed = HeroClass.parse(code)
    return parsed if parsed is not None and parsed is not HeroClass.flex else None


class RosterEngine:
    def __init__(self, *, ranks: MemberRankService = member_rank_service) -> None:
        self.ranks = ranks

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
        workspace_id = await session.scalar(sa.select(Tournament.workspace_id).where(Tournament.id == tournament_id))
        query = (
            sa.select(BalancerRegistration)
            .where(BalancerRegistration.tournament_id == tournament_id)
            .options(*registration_load_options())
            .order_by(BalancerRegistration.battle_tag_normalized.asc(), BalancerRegistration.id.asc())
        )
        if not include_deleted:
            query = query.where(BalancerRegistration.deleted_at.is_(None))
        if pool_only:
            query = query.where(
                BalancerRegistration.status == "approved",
                BalancerRegistration.deleted_at.is_(None),
                balancer_pool_included_clause(
                    BalancerRegistration.balancer_status,
                    sa.select(Tournament.workspace_id).where(Tournament.id == tournament_id).scalar_subquery(),
                ),
            )
        if registration_ids is not None:
            if not registration_ids:
                return {}
            query = query.where(BalancerRegistration.id.in_(list(registration_ids)))

        registrations = list(await session.scalars(query))
        return await self.resolve(
            session,
            registrations,
            workspace_id=workspace_id,
            tournament_id=tournament_id,
        )

    async def resolve(
        self,
        session: AsyncSession,
        registrations: Sequence[BalancerRegistration],
        *,
        workspace_id: int | None,
        tournament_id: int | None = None,
        form: BalancerRegistrationForm | None = None,
        grid: DivisionGrid | None = None,
        order: Sequence[RankScope] = TOURNAMENT_ORDER,
        author_user_id: int | None = None,
    ) -> dict[int, PlayerRoster]:
        """Resolve already-loaded registrations. Rows must carry
        :func:`registration_load_options`.

        ``form``/``grid`` are read from the tournament when omitted; pass them when
        the caller already holds them (the admin list does) to save two queries.
        """
        if not registrations:
            return {}
        if tournament_id is None:
            tournament_id = next((reg.tournament_id for reg in registrations), None)
        if form is None and tournament_id is not None:
            form = await session.scalar(
                sa.select(BalancerRegistrationForm).where(BalancerRegistrationForm.tournament_id == tournament_id)
            )
        mode = flex_role_mode(form)
        if grid is None:
            grid = await get_effective_division_grid(session, workspace_id, tournament_id)

        declared = {reg.id: self._declared_roles(reg, mode=mode) for reg in registrations}
        resolved = await self._resolve_ranks(
            session,
            registrations,
            declared=declared,
            workspace_id=workspace_id,
            grid=grid,
            order=order,
            author_user_id=author_user_id,
        )
        return {
            reg.id: self._build(reg, declared[reg.id], resolved.get(reg.id, {}), mode=mode) for reg in registrations
        }

    # -- role set ------------------------------------------------------------

    def _declared_roles(
        self, reg: BalancerRegistration, *, mode: str
    ) -> tuple[BalancerRegistrationRole | HeroClass, ...]:
        """The roles this registration declares, in priority order.

        ``optional``: the active rows, as written. ``all_roles``/``forced``: the
        rows in the registrant's order (primary first), then every role with no
        row at all synthesized after them in canonical order -- role is not a
        constraint there, so a row the sheet import left inactive (its rank did
        not parse) still names a role the player can be drafted on. A bare
        ``HeroClass`` in the result is such a synthesized role. The registrant's
        own priority is never replaced by the enum order: it is what the
        balancer's discomfort is built from. A registration with no rows gets no
        lead -- there is nobody's choice to stand in for.
        """
        rows = sorted(reg.roles or [], key=lambda row: (row.priority, row.id or 0))
        by_role: dict[HeroClass, BalancerRegistrationRole] = {}
        for row in rows:
            role = _parse_role(row.role)
            if role is None or role in by_role:
                continue
            if mode == "optional" and not row.is_active:
                continue
            by_role[role] = row
        declared = sorted(by_role.values(), key=lambda row: not row.is_primary)
        if mode == "optional":
            return tuple(declared)
        return (*declared, *(role for role in HERO_TYPE_CLASSES if role not in by_role))

    # -- ranks ---------------------------------------------------------------

    async def _resolve_ranks(
        self,
        session: AsyncSession,
        registrations: Sequence[BalancerRegistration],
        *,
        declared: Mapping[int, tuple[BalancerRegistrationRole | HeroClass, ...]],
        workspace_id: int | None,
        grid: DivisionGrid | None,
        order: Sequence[RankScope],
        author_user_id: int | None,
    ) -> dict[int, dict[HeroClass, ResolvedRank]]:
        """``{registration_id: {role: ResolvedRank}}`` under ``order``.

        The registration's own number is one layer among several: an empty
        ``rank_value`` *inherits* the workspace canon and then the latest
        Overwatch snapshot rather than reading as "unranked". Without a workspace
        (no tournament in hand) or without a member (no identity to inherit
        through) only that own layer exists.
        """
        own: dict[int, dict[HeroClass, int | None]] = {}
        member_of: dict[int, int] = {}
        for reg in registrations:
            entries = declared.get(reg.id, ())
            own[reg.id] = {
                (entry if isinstance(entry, HeroClass) else _parse_role(entry.role)): (
                    None if isinstance(entry, HeroClass) else entry.rank_value
                )
                for entry in entries
                if isinstance(entry, HeroClass) or _parse_role(entry.role) is not None
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

        roles_wanted = sorted({role.slot_code for roles in own.values() for role in roles})
        resolved = await self.ranks.resolve(
            session,
            workspace_id=workspace_id,
            members=await self._players_by_member(
                session, workspace_id=workspace_id, member_ids=list(member_of.values())
            ),
            roles=roles_wanted,
            order=order,
            author_user_id=author_user_id,
            registration_ranks={
                (member_id, role.slot_code): value
                for registration_id, member_id in member_of.items()
                for role, value in own[registration_id].items()
                if value is not None
            },
            grid=grid,
        )

        out: dict[int, dict[HeroClass, ResolvedRank]] = {}
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
                else {role: resolved.get((member_id, role.slot_code), rank) for role, rank in fallback.items()}
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

    # -- assembly ------------------------------------------------------------

    def _build(
        self,
        reg: BalancerRegistration,
        declared: tuple[BalancerRegistrationRole | HeroClass, ...],
        resolved: Mapping[HeroClass, ResolvedRank],
        *,
        mode: str,
    ) -> PlayerRoster:
        entries: list[RosterRole] = []
        from_row: set[HeroClass] = set()
        for priority, entry in enumerate(declared):
            row = None if isinstance(entry, HeroClass) else entry
            role = entry if isinstance(entry, HeroClass) else _parse_role(entry.role)
            if role is None:
                continue
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
                    top_heroes=_hero_refs(row) if row is not None else (),
                )
            )

        if mode != "optional":
            # Role stops being a constraint: every role the tournament runs is
            # playable, so a role no layer ranked inherits the player's strongest
            # number -- the balancer's eligibility for a role IS having one. The
            # per-role catalogue still reports each role's own rating where it
            # exists, because the draft SHOWS it: stamping the maximum over a real
            # rating turned the role chooser into one number printed three times.
            best = max((entry.rank for entry in entries if entry.is_playable), default=None)
            if best is not None:
                entries = [
                    entry if entry.is_playable else RosterRole(**{**_as_dict(entry), "rank": best})
                    for entry in entries
                ]

        # THE flex predicate. Over the roles the player actually declared AND can
        # play -- the raw ``registration_role`` rows also count inactive/unranked
        # ones, which is how a single-role tank used to reach the balancer as
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

        member = reg.workspace_member
        player = member.player if member is not None else None
        return PlayerRoster(
            registration_id=reg.id,
            battle_tag=reg.battle_tag,
            display_name=reg.display_name,
            player_id=member.player_id if member is not None else None,
            auth_user_id=player.auth_user_id if player is not None else None,
            workspace_member_id=reg.workspace_member_id,
            roles=tuple(entries),
            is_full_flex=is_full_flex,
            notes=reg.notes,
            admin_notes=reg.admin_notes,
            custom_fields=dict(reg.custom_fields_json or {}),
            status=reg.status,
            balancer_status=reg.balancer_status,
            exclude_reason=reg.exclude_reason,
            checked_in=bool(reg.checked_in),
            registration_team_id=reg.registration_team_id,
            team_slot_code=reg.team_slot_code,
            is_substitute=bool(reg.is_substitute),
            discord_nick=reg.discord_nick,
            twitch_nick=reg.twitch_nick,
            boosty_nick=reg.boosty_nick,
            stream_pov=bool(reg.stream_pov),
            smurf_tags=tuple(reg.smurf_tags_json or ()),
        )

    # -- algorithm input -----------------------------------------------------

    def balancer_input(
        self,
        rosters: Iterable[PlayerRoster],
        *,
        key: str = "registration_id",
    ) -> dict[str, Any]:
        """The balancer algorithm's ``xv-1`` payload, built from the same rosters.

        Used to be assembled in the browser from the admin list, which is why the
        algorithm and the draft could disagree at all. ``key`` names the field the
        result's player uuids carry, so the caller can map a solved team back.
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
                        entry.role.slot_code: {
                            "isActive": True,
                            "rank": entry.rank,
                            "priority": entry.priority,
                            "subtype": entry.subrole,
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
                "battle_tag": roster.battle_tag,
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
                "primary_role": primary.role.slot_code if primary is not None else None,
                "sub_role": roster.sub_role,
                "status": roster.status,
                "balancer_status": roster.balancer_status,
                "checked_in": roster.checked_in,
                "registration_team_id": roster.registration_team_id,
                "team_slot_code": roster.team_slot_code,
                "is_substitute": roster.is_substitute,
                "roles": [_role_export(entry, grid) for entry in roster.roles],
            }
            if include_private:
                owt["private"] = {
                    "notes": roster.notes,
                    "admin_notes": roster.admin_notes,
                    "exclude_reason": roster.exclude_reason,
                    "custom_fields": dict(roster.custom_fields),
                    "discord_nick": roster.discord_nick,
                    "twitch_nick": roster.twitch_nick,
                    "boosty_nick": roster.boosty_nick,
                    "stream_pov": roster.stream_pov,
                    "smurf_tags": list(roster.smurf_tags),
                }
            players[str(getattr(roster, key))] = {
                "identity": {
                    "name": _export_name(roster),
                    "isFullFlex": roster.is_full_flex,
                },
                "stats": {
                    "classes": {
                        entry.role.slot_code: {
                            "isActive": entry.is_playable,
                            "rank": entry.rank,
                            "priority": entry.priority,
                            "subtype": entry.subrole,
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
        "top_heroes": entry.top_heroes,
    }


def _export_name(roster: PlayerRoster) -> str:
    return roster.battle_tag or roster.display_name or f"registration-{roster.registration_id}"


def _role_export(entry: RosterRole, grid: DivisionGrid | None) -> dict[str, Any]:
    # A tier-less grid is a legitimate workspace state (nobody configured one);
    # ``resolve_division`` raises on it, and a decorative label is never worth
    # failing the export for.
    resolvable = grid is not None and bool(grid.tiers) and entry.rank is not None
    tier = grid.resolve_division(entry.rank) if resolvable else None  # type: ignore[union-attr, arg-type]
    return {
        "role": entry.role.slot_code,
        "rank": entry.rank,
        "source": entry.source,
        "is_primary": entry.is_primary,
        "priority": entry.priority,
        "subrole": entry.subrole,
        "playable": entry.is_playable,
        "division": None if tier is None else {"number": tier.number, "name": tier.name},
        "top_heroes": [
            {"hero_id": hero.id, "slug": hero.slug, "image_path": hero.image_path} for hero in entry.top_heroes
        ],
    }


roster_engine = RosterEngine()
