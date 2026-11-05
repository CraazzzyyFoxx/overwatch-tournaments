"""Draft session lifecycle: create, seed, status transitions, pick actions and their events.

Services flush within the caller's transaction (rpc handlers and the clock
worker commit). Status moves are guarded by ``shared.core.draft_state``. The
pick clock is DB-resumable: absolute ``clock_expires_at`` while live, frozen
``clock_remaining_ms`` while paused.

Pure business rules (seat ordering, registration mapping, seed-row building)
live in ``src.domain.draft.rules`` — this file holds only the orchestration
that needs a database session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import draft_state
from shared.core.enums import (
    DraftCaptainOrder,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftStatus,
    FlowNodeKind,
    FlowNodeStatus,
)
from shared.core.errors import BaseAPIException
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import RosterShape
from shared.models.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.models.tournament.flow import FlowNode
from shared.repository import CustomGameRepository
from shared.repository.draft import (
    DraftPickRepository,
    DraftPlayerRepository,
    DraftSessionRepository,
    DraftTeamRepository,
)
from shared.repository.flow_node import FlowNodeRepository
from shared.repository.identity import UserRepository
from shared.repository.tournament import TournamentRepository
from shared.repository.workspace import WorkspaceMemberRepository, get_or_create_workspace_member
from shared.schemas.draft_format import session_format_from_tournament
from shared.schemas.role import RoleRef
from shared.services.ontology import resolve_role_ref
from shared.services.team_format import tournament_slot_shape
from src import schemas
from src.domain.draft import ranks, rules
from src.domain.draft.entities import DraftResult, PoolSeat
from src.domain.draft.errors import err as _err
from src.services.draft import loaders
from src.services.draft import realtime as draft_rt
from src.services.draft.board import board_service
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.journal import journal_service
from src.services.draft.rosters import DraftRosterService, draft_rosters
from src.services.draft.selection import DraftSelectionService, selection_service
from src.services.formation_node import require_formation_node
from src.services.mix_room_dms import notify_mix_captain

__all__ = ("DraftLifecycleService", "lifecycle_service")

#: ``settings_json`` keys the tournament's format rule owns. A client may not set
#: them: on create they come from ``Tournament.draft_format_json``, on patch the
#: session keeps the snapshot it was created with. Otherwise the wizard (or a
#: stale bundle) would be a second, unlocked place to edit the format.
_FORMAT_SETTINGS_KEYS = ("round_rules", "avg_tie_seed_reverse")


def _with_format_settings(client: dict[str, Any], owned: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in client.items() if k not in _FORMAT_SETTINGS_KEYS} | owned


def _pick_event_payload(draft: DraftSession, pick: DraftPick, *, dimension: str) -> dict:
    return {
        "session_id": draft.id,
        "pick_id": pick.id,
        "overall_pick_no": pick.overall_no,
        "draft_team_id": pick.draft_team_id,
        "picked_player_id": pick.picked_player_id,
        "target_role": ref.model_dump() if (ref := RoleRef.of(dimension, pick.target_role)) else None,
        "target_rank_value": pick.target_rank_value,
        "pick_version": pick.version,
        "status": pick.status,
        "current_pick_index": draft.current_pick_id,
    }


def _override_journal_state(pick: DraftPick) -> dict:
    return {
        "pick_id": pick.id,
        "overall_no": pick.overall_no,
        "player_id": pick.picked_player_id,
        "team_id": pick.draft_team_id,
        "role": pick.target_role,
        "rank_value": pick.target_rank_value,
        "version": pick.version,
    }


def _seed_diff(
    *,
    before: tuple[int, int, int],
    after: tuple[int, int, int],
    version_before: int,
    version_after: int,
) -> schemas.DraftSeedDiff:
    return schemas.DraftSeedDiff(
        teams_before=before[0],
        teams_after=after[0],
        players_before=before[1],
        players_after=after[1],
        picks_before=before[2],
        picks_after=after[2],
        session_version_before=version_before,
        session_version_after=version_after,
    )


class DraftLifecycleService:
    def __init__(
        self,
        *,
        sessions_repo: DraftSessionRepository = DraftSessionRepository(),
        teams_repo: DraftTeamRepository = DraftTeamRepository(),
        players_repo: DraftPlayerRepository = DraftPlayerRepository(),
        picks_repo: DraftPickRepository = DraftPickRepository(),
        tournaments_repo: TournamentRepository = TournamentRepository(),
        members_repo: WorkspaceMemberRepository = WorkspaceMemberRepository(),
        users_repo: UserRepository = UserRepository(),
        feasibility: DraftFeasibilityService = feasibility_service,
        rosters: DraftRosterService = draft_rosters,
        selection: DraftSelectionService = selection_service,
        custom_games: CustomGameRepository = CustomGameRepository(),
        flow_nodes: FlowNodeRepository = FlowNodeRepository(),
    ) -> None:
        self.sessions_repo = sessions_repo
        self.teams_repo = teams_repo
        self.players_repo = players_repo
        self.picks_repo = picks_repo
        self.tournaments_repo = tournaments_repo
        self.members_repo = members_repo
        self.users_repo = users_repo
        self.feasibility = feasibility
        self.rosters = rosters
        self.selection = selection
        self.custom_games = custom_games
        self.flow_nodes = flow_nodes

    async def get_session(self, session: AsyncSession, session_id: int) -> DraftSession:
        draft = await self.sessions_repo.get(session, session_id)
        if draft is None:
            raise BaseAPIException(status_code=404, detail="Draft session not found")
        return draft

    async def get_pick(self, session: AsyncSession, pick_id: int) -> tuple[DraftSession, DraftPick]:
        pick = await self.picks_repo.get(session, pick_id)
        if pick is None:
            raise BaseAPIException(status_code=404, detail="Draft pick not found")
        return await self.get_session(session, pick.session_id), pick

    async def get_team(self, session: AsyncSession, draft_session: DraftSession, team_id: int) -> DraftTeam:
        team = await self.teams_repo.get(session, team_id)
        if team is None or team.session_id != draft_session.id:
            raise BaseAPIException(status_code=404, detail="Draft team not found")
        return team

    async def actor_player_id(self, session: AsyncSession, auth_user_id: int) -> int | None:
        """The domain player id linked to an acting auth user (``players.user.auth_user_id`` is unique)."""
        return await self.users_repo.get_id_by_auth_user_id(session, auth_user_id)

    async def resolve_role(self, session: AsyncSession, draft_session: DraftSession, ref: RoleRef | None) -> str | None:
        """A client ``RoleRef`` -> the top-level role code of this draft's discipline/workspace."""
        row = await resolve_role_ref(
            session,
            discipline=draft_session.discipline,
            workspace_id=draft_session.workspace_id,
            ref=ref,
            top_level_only=True,
        )
        return row.code if row is not None else None

    async def assert_no_active_draft(self, session: AsyncSession, formation_node_id: int) -> None:
        if await self.sessions_repo.exists_active_for_formation_node(session, formation_node_id):
            raise _err("draft_already_active", f"Formation node {formation_node_id} already has an active draft")

    async def assert_draft_formation(self, session: AsyncSession, formation_node_id: int) -> FlowNode:
        """A draft forms the teams only of a formation node that says it does: the
        balancer and team registration write `tournament.team` their own way.

        Checked on create, seed and start: a session created before the check
        existed, or a node switched away from draft since, is stopped too.
        """
        node = await self.flow_nodes.get(session, formation_node_id)
        if node is None:
            raise _err("flow_node_not_found", "Flow node not found", status_code=404)
        mode = node.config.get("mode")
        if node.kind != FlowNodeKind.FORMATION or mode != "draft":
            raise _err(
                "tournament_not_draft_formation",
                f"Flow node {formation_node_id} forms its teams by {mode!r}, not by draft",
            )
        return node

    async def tournament_draft_format(
        self, session: AsyncSession, tournament_id: int, *, rounds: int
    ) -> tuple[DraftFormat, dict]:
        """The tournament's format rule, projected onto a session of ``rounds`` rounds.

        The format is entered once in the tournament's settings, and every new
        session takes its snapshot from here (``NULL`` -> snake).
        """
        raw = await self.tournaments_repo.get_draft_format_json(session, tournament_id)
        return session_format_from_tournament(raw, rounds)

    async def create_session(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        shape: RosterShape,
        tournament_id: int | None = None,
        formation_node_id: int | None = None,
        custom_game_id: int | None = None,
        lobby_index: int | None = None,
        pool_source: str = "balancer_balance",
        source_balance_id: int | None = None,
        fmt: DraftFormat = DraftFormat.SNAKE,
        pick_time_seconds: int = 45,
        overtime_seconds: int = 0,
        autopick_strategy: str = "best_fit",
        allow_admin_override: bool = True,
        settings: dict | None = None,
    ) -> DraftSession:
        """A session of exactly one owner: a tournament's formation node, or one lobby of a mix (spec §9.1). One
        active session per owner -- checked here for a node, by ``uq_draft_session_active_lobby`` for a lobby."""
        if (tournament_id is None) != (formation_node_id is None):
            raise _err(
                "formation_node_required",
                "A tournament draft names its formation node, a mix draft names none",
                status_code=422,
            )
        # `rounds` is derived, never passed: the shape owns the roster size.
        if shape.draft_rounds < 1:
            raise _err(
                "invalid_roster_shape",
                f"The roster shape {shape.slots} has a single slot: the captain is the whole team, "
                "so there is nothing to draft",
                status_code=422,
            )
        if tournament_id is not None:
            await self.assert_no_active_draft(session, formation_node_id)
            owner = await self.tournaments_repo.get(session, tournament_id)
        else:
            owner = await self.custom_games.get(session, custom_game_id)
        draft = DraftSession(
            tournament_id=tournament_id,
            formation_node_id=formation_node_id,
            custom_game_id=custom_game_id,
            lobby_index=lobby_index,
            discipline=owner.discipline,
            workspace_id=workspace_id,
            status=DraftStatus.SETUP.value,
            format=fmt.value,
            rounds=shape.draft_rounds,
            pick_time_seconds=pick_time_seconds,
            overtime_seconds=overtime_seconds,
            pool_source=pool_source,
            source_balance_id=source_balance_id,
            autopick_strategy=autopick_strategy,
            allow_admin_override=allow_admin_override,
            settings_json=settings or {},
        )
        draft = await self.sessions_repo.create(session, draft)
        await session.refresh(draft)
        return draft

    async def create_for_tournament(
        self,
        session: AsyncSession,
        payload: schemas.DraftSessionCreateRequest,
        *,
        tournament_id: int,
        workspace_id: int,
        actor_user_id: int,
    ) -> DraftSession:
        """Create a session for the payload's formation node and publish ``draft.session_updated``."""
        await require_formation_node(session, tournament_id, payload.formation_node_id)
        await self.assert_draft_formation(session, payload.formation_node_id)
        # The roster shape is the tournament's, not the request's: a draft
        # cannot be created at a size the tournament does not run. The format
        # is the tournament's for the same reason -- it is a rule organizers
        # announce, edited in the tournament's settings, not here.
        shape = await tournament_slot_shape(session, tournament_id)
        fmt, format_settings = await self.tournament_draft_format(session, tournament_id, rounds=shape.draft_rounds)
        draft = await self.create_session(
            session,
            tournament_id=tournament_id,
            formation_node_id=payload.formation_node_id,
            workspace_id=workspace_id,
            shape=shape,
            pool_source=payload.pool_source.value,
            source_balance_id=payload.source_balance_id,
            fmt=fmt,
            pick_time_seconds=payload.pick_time_seconds,
            overtime_seconds=payload.overtime_seconds,
            autopick_strategy=payload.autopick_strategy.value,
            allow_admin_override=payload.allow_admin_override,
            settings=_with_format_settings(payload.settings, format_settings),
        )
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft,
            event_type="draft.session_updated",
            payload={"session_id": draft.id, "status": draft.status},
            actor_user_id=actor_user_id,
        )
        return draft

    async def patch_session(
        self,
        session: AsyncSession,
        session_id: int,
        payload: schemas.DraftSessionPatchRequest,
        *,
        actor_user_id: int,
    ) -> DraftSession:
        """Apply an organizer's settings patch; a re-seat publishes ``draft.session_updated``."""
        draft = await self.get_session(session, session_id)
        if draft.status not in (DraftStatus.SETUP.value, DraftStatus.READY.value):
            raise _err("draft_settings_locked", "Draft settings can only change before the draft starts")
        if payload.pick_time_seconds is not None:
            draft.pick_time_seconds = payload.pick_time_seconds
        if payload.overtime_seconds is not None:
            draft.overtime_seconds = payload.overtime_seconds
        if payload.autopick_strategy is not None:
            draft.autopick_strategy = payload.autopick_strategy.value
        if payload.allow_admin_override is not None:
            draft.allow_admin_override = payload.allow_admin_override
        if payload.rounds is not None:
            # Kept only so a stale client cannot silently desync the board:
            # the sole accepted value is the one the shape already implies.
            rules.validate_draft_rounds(
                rounds=payload.rounds, shape=await self.feasibility.resolve_shape(session, draft)
            )
            draft.rounds = payload.rounds
        if payload.settings is not None:
            # A full replace, minus the format the tournament owns: the session
            # keeps the snapshot it was created with (see _FORMAT_SETTINGS_KEYS).
            draft.settings_json = _with_format_settings(
                payload.settings,
                {k: draft.settings_json[k] for k in _FORMAT_SETTINGS_KEYS if k in draft.settings_json},
            )
        # The pick rows carry the seat order `round_rules` decides, so a rules
        # change re-seats them; rounds already in progress keep their order.
        moved = await self.resync_pick_order(session, draft)
        if moved:
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status, "picks_reordered": moved},
                actor_user_id=actor_user_id,
            )
        return draft

    async def resync_pick_order(self, session: AsyncSession, draft_session: DraftSession) -> int:
        """Re-seat every round that has not started yet. Returns how many picks moved.

        ``round_rules`` lives on the session while the pick rows are materialized at
        seed time; callers run this after a settings change so the board and the
        rules cannot disagree.

        A round holding any pick that is no longer UPCOMING is history and is left
        alone -- reordering a round somebody already picked in would rewrite who
        picked when. Dynamic ``team_avg_*`` rounds keep the seed order here; they are
        re-seated when they start.
        """
        teams = await self.teams_repo.list_by_session(session, draft_session.id)
        if not teams:
            return 0
        picks = await self.picks_repo.list_by_session(session, draft_session.id)
        if not picks:
            return 0

        captains = await self.players_repo.list_drafted_captains(session, draft_session.id)
        rosters = await self.rosters.load(session, draft_session, captains)
        shape = await self.feasibility.resolve_shape(session, draft_session)
        captain_ranks = {
            captain.drafted_by_team_id: ranks.captain_rank(rosters.get(captain.id), captain.captain_role, shape)
            for captain in captains
        }
        fmt = DraftFormat(draft_session.format)
        round_rules = draft_session.settings_json.get("round_rules") or []

        by_round: dict[int, list[DraftPick]] = {}
        for pick in picks:
            by_round.setdefault(pick.round_no, []).append(pick)

        moved = 0
        for round_no, round_picks in by_round.items():
            if any(pick.status != DraftPickStatus.UPCOMING.value for pick in round_picks):
                continue
            round_seats = rules.round_seat_order(
                list(teams),
                fmt=fmt,
                round_rules=round_rules,
                round_idx=round_no - 1,
                captain_ranks=captain_ranks,
            )
            for pick, team in zip(sorted(round_picks, key=lambda p: p.pick_in_round), round_seats, strict=False):
                if pick.draft_team_id != team.id:
                    pick.draft_team_id = team.id
                    moved += 1
        if moved:
            await session.flush()
        return moved

    async def seed(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        *,
        seats: list[PoolSeat],
    ) -> DraftSession:
        """Materialize teams + pool + all picks, then transition SETUP/READY -> READY.

        A seat carries a registration (tournament) or a member (mix) id and nothing else. Roles and ranks are
        NOT copied here -- they are resolved from the owner's engine on every read,
        which is what makes a rank typed in the balancer after seeding show up in
        the draft without a re-seed.
        """
        if draft_session.status not in (DraftStatus.SETUP.value, DraftStatus.READY.value):
            raise _err("draft_not_seedable", "Draft can only be seeded in SETUP or READY")
        rules.validate_seat_identities(seats, mix=draft_session.custom_game_id is not None)
        if draft_session.tournament_id is not None:
            await self.assert_draft_formation(session, draft_session.formation_node_id)
        captains = [seat for seat in seats if seat.draft_position is not None]
        if not captains:
            raise _err("draft_no_captains", "At least one captain is required to seed a draft")

        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.READY)

        rosters = await self.rosters.pool(session, draft_session)
        missing = [seat.key for seat in seats if seat.key not in rosters]
        if missing:
            raise _err(
                "registration_not_in_pool",
                f"Registrations {sorted(missing)} are not in the balancer pool for this tournament",
                status_code=422,
            )
        # A registration the balancer ranks on no role has nothing to be drafted
        # on: refuse, and name who needs a rank.
        unranked = [rosters[seat.key] for seat in seats if not rosters[seat.key].is_draftable]
        if unranked:
            raise rules.unranked_pool_error(unranked)
        shape = await self.feasibility.resolve_shape(session, draft_session)
        rules.validate_captain_roles(captains, rosters, shape)
        role_rows = await loaders.rated_rows(session, draft_session)

        # Re-seed: clear any prior teams/players/picks.
        await self.picks_repo.delete_by_session(session, draft_session.id)
        await self.players_repo.delete_by_session(session, draft_session.id)
        await self.teams_repo.delete_by_session(session, draft_session.id)
        draft_session.current_pick_id = None
        await session.flush()

        ordered_captains = sorted(captains, key=lambda seat: seat.draft_position or 0)

        # Resolve domain player ids -> workspace_member rows for this session's
        # workspace (draft identity is anchored on workspace_member).
        # Done once up front so every team/player row reuses the same member id.
        player_ids = {
            roster.player_id for roster in (rosters[seat.key] for seat in seats) if roster.player_id is not None
        }
        member_by_player: dict[int, int] = {}
        if player_ids:
            # Batch-prefetch existing membership rows (the common case on re-seed)
            # instead of one INSERT..ON CONFLICT round-trip per player.
            member_by_player = await self.members_repo.member_ids_by_player(
                session, workspace_id=draft_session.workspace_id, player_ids=player_ids
            )
        # get_or_create also autofills the baseline RBAC role for a brand-new
        # auth-linked member — keep that side effect, but only pay for it on
        # players that genuinely have no membership row yet.
        for player_id in player_ids - member_by_player.keys():
            member = await get_or_create_workspace_member(
                session, workspace_id=draft_session.workspace_id, player_id=player_id
            )
            member_by_player[player_id] = member.id

        def _member_id(roster: PlayerRoster) -> int | None:
            return member_by_player.get(roster.player_id) if roster.player_id is not None else None

        teams: list[DraftTeam] = []
        team_by_position: dict[int, DraftTeam] = {}
        for position, seat in enumerate(ordered_captains, start=1):
            roster = rosters[seat.key]
            team = DraftTeam(
                session_id=draft_session.id,
                captain_workspace_member_id=_member_id(roster),
                captain_auth_user_id=roster.auth_user_id,
                name=seat.team_name or roster.handle or roster.display_name or f"Team {position}",
                draft_position=position,
            )
            teams.append(team)
            team_by_position[position] = team
        await self.teams_repo.create_many(session, teams)

        captain_keys = {seat.key for seat in ordered_captains}
        players_to_create: list[DraftPlayer] = []
        for position, seat in enumerate(ordered_captains, start=1):
            # Captains become PICKED players already on their own roster.
            roster = rosters[seat.key]
            players_to_create.append(
                DraftPlayer(
                    session_id=draft_session.id,
                    registration_id=seat.registration_id,
                    workspace_member_id=_member_id(roster),
                    is_captain=True,
                    status=DraftPlayerStatus.PICKED.value,
                    drafted_by_team_id=team_by_position[position].id,
                    captain_role_row=role_rows[seat.captain_role] if seat.captain_role else None,
                    dimension_id=role_rows[seat.captain_role].dimension_id if seat.captain_role else None,
                )
            )
        for seat in seats:
            if seat.key in captain_keys:
                continue
            roster = rosters[seat.key]
            players_to_create.append(
                DraftPlayer(
                    session_id=draft_session.id,
                    registration_id=seat.registration_id,
                    workspace_member_id=_member_id(roster),
                    status=DraftPlayerStatus.AVAILABLE.value,
                )
            )
        await self.players_repo.create_many(session, players_to_create)

        # Pre-create all picks in deterministic order based on round rules.
        team_captain_ranks = {
            team_by_position[position].id: ranks.captain_rank(rosters[seat.key], seat.captain_role, shape)
            for position, seat in enumerate(ordered_captains, start=1)
        }
        seats_in_order = [team_by_position[position] for position in sorted(team_by_position)]

        fmt = DraftFormat(draft_session.format)
        round_rules = draft_session.settings_json.get("round_rules") or []

        picks: list[DraftPick] = []
        overall_no = 1
        for round_idx in range(draft_session.rounds):
            round_seats = rules.round_seat_order(
                seats_in_order,
                fmt=fmt,
                round_rules=round_rules,
                round_idx=round_idx,
                captain_ranks=team_captain_ranks,
            )
            for pick_in_round, team in enumerate(round_seats, start=1):
                picks.append(
                    DraftPick(
                        session_id=draft_session.id,
                        overall_no=overall_no,
                        round_no=round_idx + 1,
                        pick_in_round=pick_in_round,
                        draft_team_id=team.id,
                        status=DraftPickStatus.UPCOMING.value,
                        version=0,
                    )
                )
                overall_no += 1
        await self.picks_repo.create_many(session, picks)

        draft_session.status = DraftStatus.READY.value
        draft_session.blocked_reason = None
        rules.bump_seed_version(draft_session)
        # expire_on_commit=False and all mutations above are Python-side: the
        # in-memory session row is already current, no refresh round-trip needed.
        await session.flush()
        return draft_session

    async def seed_from_pool(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        *,
        captain_registration_ids: list[int],
        team_names: dict[int, str] | None = None,
        captain_order: DraftCaptainOrder = DraftCaptainOrder.MANUAL,
        rng_seed: int | None = None,
        captain_roles: dict[int, str] | None = None,
    ) -> DraftSession:
        """Seed a draft from the balancer registration pool.

        ``captain_registration_ids`` are ``registration.registration`` ids chosen as
        captains; ``captain_order`` decides seat order (WEAKEST_FIRST seats the
        lowest-rated captain at position 1). ``captain_roles`` pins a captain to
        one of their roles (absent = their lead role). Every other in-pool
        registration becomes an available draft player. Ordering reads the rank
        of the role each captain is seated on -- the number the captain step
        shows next to them.
        """
        rosters = await self.rosters.pool(session, draft_session)
        if not captain_registration_ids:
            raise _err("draft_no_captains", "Select at least one captain from the pool")
        for registration_id in captain_registration_ids:
            if registration_id not in rosters:
                raise _err(
                    "captain_not_in_pool",
                    f"Captain registration {registration_id} is not in the balancer pool for this tournament",
                    status_code=422,
                )

        team_names = team_names or {}
        captain_roles = captain_roles or {}
        shape = await self.feasibility.resolve_shape(session, draft_session)
        ordered_ids = rules.order_captain_ids(
            [
                (
                    registration_id,
                    ranks.captain_rank(rosters[registration_id], captain_roles.get(registration_id), shape),
                )
                for registration_id in captain_registration_ids
            ],
            captain_order,
            rng_seed,
        )
        captain_ids = set(ordered_ids)
        seats = [
            PoolSeat(
                registration_id=registration_id,
                draft_position=position,
                team_name=team_names.get(registration_id),
                captain_role=captain_roles.get(registration_id),
            )
            for position, registration_id in enumerate(ordered_ids, start=1)
        ]
        seats.extend(
            PoolSeat(registration_id=registration_id)
            for registration_id in sorted(rosters)
            if registration_id not in captain_ids
        )
        return await self.seed(session, draft_session, seats=seats)

    async def seed_or_preview(
        self,
        session: AsyncSession,
        session_id: int,
        payload: schemas.DraftSeedRequest,
        *,
        actor_user_id: int,
    ) -> schemas.DraftSeedResponse:
        """Seed a session from the request's pool captains and report the diff.

        ``preview_only`` runs the whole seed inside a SAVEPOINT and rolls it back,
        so the diff and the feasibility report describe exactly what a real seed
        would write. A real seed stages ``draft.session_updated``; the caller commits.
        """
        draft = await self.sessions_repo.get_for_update(session, session_id)
        if draft is None:
            raise BaseAPIException(status_code=404, detail="Draft session not found")
        rules.validate_seed_version(draft, expected_version=payload.expected_version)
        before = await self.sessions_repo.seed_row_counts(session, draft.id)
        version_before = draft.version
        savepoint = await session.begin_nested() if payload.preview_only else None
        try:
            if not payload.pool_captains:
                raise BaseAPIException(
                    status_code=422,
                    detail="Provide pool_captains: a draft seat is a balancer registration",
                )
            await self.seed_from_pool(
                session,
                draft,
                captain_registration_ids=[c.registration_id for c in payload.pool_captains],
                team_names={c.registration_id: c.name for c in payload.pool_captains if c.name},
                captain_order=payload.captain_order,
                rng_seed=payload.seed,
                captain_roles={
                    c.registration_id: await self.resolve_role(session, draft, c.role)
                    for c in payload.pool_captains
                    if c.role
                },
            )

            after = await self.sessions_repo.seed_row_counts(session, draft.id)
            report = await self.feasibility.analyze_session(session, draft)
            response = schemas.DraftSeedResponse(
                session=await board_service.session_read(session, draft),
                preview_only=payload.preview_only,
                diff=_seed_diff(
                    before=before,
                    after=after,
                    version_before=version_before,
                    version_after=draft.version,
                ),
                feasibility=schemas.DraftFeasibilityResponse.model_validate(report),
            )
            if savepoint is not None:
                await savepoint.rollback()
                return response

            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.session_updated",
                payload={"session_id": draft.id, "status": draft.status},
                actor_user_id=actor_user_id,
            )
            return response
        except Exception:
            if savepoint is not None and savepoint.is_active:
                await savepoint.rollback()
            raise

    async def start(self, session: AsyncSession, draft_session: DraftSession, *, force: bool = False) -> DraftSession:
        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.LIVE)
        # A mix draft has no formation node to be forming (spec §9.1).
        if draft_session.tournament_id is not None:
            # Not bypassed by ``force``: no draft forms another formation's teams.
            node = await self.assert_draft_formation(session, draft_session.formation_node_id)
            # The node gate keeps organizers from going live before the formation node is forming. A superuser may
            # bypass it (``force``) to run a draft out of band — a test run, or a rescue after the schedule drifted.
            if not force and node.status != FlowNodeStatus.FORMING:
                raise _err("formation_not_forming", "Draft can only start while its formation node is forming")
        first = await self.picks_repo.first_upcoming(session, draft_session.id)
        if first is None:
            raise _err("draft_no_picks", "Draft has no picks to start")
        report = await self.feasibility.analyze_session(session, draft_session)
        if not report.is_feasible:
            raise rules.role_shortage_error(report)
        now = datetime.now(UTC)
        rules.arm_clock(first, draft_session.pick_time_seconds, now)
        draft_session.status = DraftStatus.LIVE.value
        draft_session.blocked_reason = None
        draft_session.current_pick_id = first.id
        await session.flush()
        if draft_session.custom_game_id is not None:
            # One DM per captain when the clock starts -- not at the seed, per pick or on resume (spec §12.1 R3-3).
            game = await self.custom_games.get(session, draft_session.custom_game_id)
            for team in await self.teams_repo.list_by_session(session, draft_session.id):
                await notify_mix_captain(
                    session,
                    kind="mix.draft_started",
                    game=game,
                    lobby_index=draft_session.lobby_index,
                    auth_user_id=team.captain_auth_user_id,
                    dedupe_key=f"mix_draft:{draft_session.id}:{team.captain_workspace_member_id}",
                )
        return draft_session

    async def pause(self, session: AsyncSession, draft_session: DraftSession) -> DraftSession:
        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.PAUSED)
        now = datetime.now(UTC)
        current = (
            await self.picks_repo.get(session, draft_session.current_pick_id) if draft_session.current_pick_id else None
        )
        if current is not None and current.clock_expires_at is not None:
            remaining = (current.clock_expires_at - now).total_seconds() * 1000.0
            current.clock_remaining_ms = max(0, int(remaining))
            current.clock_expires_at = None
        draft_session.status = DraftStatus.PAUSED.value
        draft_session.blocked_reason = None
        await session.flush()
        return draft_session

    async def resume(self, session: AsyncSession, draft_session: DraftSession) -> DraftSession:
        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.LIVE)
        report = await self.feasibility.analyze_session(session, draft_session)
        if not report.is_feasible:
            raise rules.role_shortage_error(report)
        now = datetime.now(UTC)
        current = (
            await self.picks_repo.get(session, draft_session.current_pick_id) if draft_session.current_pick_id else None
        )
        if current is not None:
            remaining_ms = (
                current.clock_remaining_ms
                if current.clock_remaining_ms is not None
                else (draft_session.pick_time_seconds * 1000)
            )
            current.clock_started_at = now
            current.clock_expires_at = now + timedelta(milliseconds=remaining_ms)
            current.clock_remaining_ms = None
        draft_session.status = DraftStatus.LIVE.value
        draft_session.blocked_reason = None
        await session.flush()
        return draft_session

    async def extend_pick(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        pick: DraftPick,
        *,
        seconds: int,
        expected_version: int,
        actor_auth_user_id: int,
    ) -> DraftPick:
        """Give the on-clock captain more time, live or paused; journal it and publish ``draft.clock_extended``.

        Additive on whichever representation of the clock is authoritative right
        now: the absolute deadline while LIVE, the frozen remainder while PAUSED.
        Overtime is untouched -- a pick already in its grace period just gets a
        later overtime deadline, and one that is not keeps its grace period for
        later.
        """
        if draft_session.status not in (DraftStatus.LIVE.value, DraftStatus.PAUSED.value):
            raise _err("draft_not_live", "Draft is not live")
        if pick.id != draft_session.current_pick_id or pick.status != DraftPickStatus.ON_CLOCK.value:
            raise _err("pick_not_on_clock", "This is not the current on-clock pick")
        if pick.version != expected_version:
            raise rules.pick_conflict(pick)

        if draft_session.status == DraftStatus.LIVE.value:
            base = pick.clock_expires_at or datetime.now(UTC)
            pick.clock_expires_at = base + timedelta(seconds=seconds)
        else:
            remaining_ms = (
                pick.clock_remaining_ms
                if pick.clock_remaining_ms is not None
                else draft_session.pick_time_seconds * 1000
            )
            pick.clock_remaining_ms = remaining_ms + seconds * 1000
        pick.version += 1
        await session.flush()
        expires_at = pick.clock_expires_at.isoformat() if pick.clock_expires_at else None
        await journal_service.record(
            session,
            draft_session.id,
            action="pick_extended",
            entity_type="draft_pick",
            entity_id=pick.id,
            actor_auth_user_id=actor_auth_user_id,
            before={"version": expected_version},
            after={
                "pick_id": pick.id,
                "overall_no": pick.overall_no,
                "team_id": pick.draft_team_id,
                "seconds": seconds,
                "clock_expires_at": expires_at,
            },
        )
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft_session,
            event_type="draft.clock_extended",
            payload={
                "session_id": draft_session.id,
                "pick_id": pick.id,
                "clock_expires_at": expires_at,
                "added_seconds": seconds,
                "pick_version": pick.version,
            },
            actor_user_id=actor_auth_user_id,
        )
        return pick

    async def cancel(self, session: AsyncSession, draft_session: DraftSession) -> DraftSession:
        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.CANCELLED)
        draft_session.status = DraftStatus.CANCELLED.value
        draft_session.blocked_reason = None
        await session.flush()
        return draft_session

    async def delete_session(self, session: AsyncSession, draft_session: DraftSession) -> None:
        """Erase a draft session and everything hanging off it.

        A LIVE/PAUSED draft has captains on a clock, so it must be cancelled first;
        every other status is erasable. Teams already exported to the tournament are
        NOT removed: the export is a separate artifact and ``exported_team_id`` is
        only a back-reference into it.
        """
        if draft_session.status not in rules.DELETABLE_STATUSES:
            raise _err("draft_in_flight", "Cancel the draft before deleting it")
        # Drop the session -> current pick reference before the cascade removes that
        # pick, so no flush can write a dangling FK.
        draft_session.current_pick_id = None
        await session.flush()
        # One statement: teams, players, roles, heroes, picks and audit rows all
        # hang off the session with ON DELETE CASCADE, so the ORM cascade would only
        # buy hundreds of round-trips. Expunge keeps the deleted row out of any
        # later flush.
        await self.sessions_repo.delete_by_id(session, draft_session.id)
        session.expunge(draft_session)

    async def delete_for_tournament(
        self, session: AsyncSession, session_id: int, *, tournament_id: int, actor_user_id: int
    ) -> None:
        """Erase ``session_id`` if it belongs to ``tournament_id``, publishing ``draft.session_updated`` first."""
        draft = await self.get_session(session, session_id)
        if draft.tournament_id != tournament_id:
            raise BaseAPIException(status_code=404, detail="Draft session not found")
        # Published before the row goes away: spectators keep a board keyed
        # by this session and would otherwise never learn it is gone.
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft,
            event_type="draft.session_updated",
            payload={"session_id": draft.id, "status": draft.status, "deleted": True},
            actor_user_id=actor_user_id,
        )
        await self.delete_session(session, draft)

    async def rollback(self, session: AsyncSession, draft_session: DraftSession) -> DraftSession:
        """Rollback the last resolved pick, resetting player/pick states and pausing the draft.

        409 ``rollback_frees_captain`` when the pick seated the player a mix host has since crowned (Replace captain):
        freed, they would captain the team from the pool. The host crowns a player who stays on the team first."""
        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.PAUSED)

        last_resolved = await self.picks_repo.last_resolved(session, draft_session.id)
        if last_resolved is None:
            raise _err("no_picks_to_rollback", "There are no resolved picks to rollback")

        picks_to_revert = await self.picks_repo.list_from(session, draft_session.id, last_resolved.overall_no)

        player_ids_to_free = [p.picked_player_id for p in picks_to_revert if p.picked_player_id is not None]
        if player_ids_to_free:
            players = await self.players_repo.bulk_get(session, player_ids_to_free)
            if draft_session.custom_game_id is not None:
                captains = {
                    team.captain_workspace_member_id
                    for team in await self.teams_repo.list_by_session(session, draft_session.id)
                }
                if any(player.workspace_member_id in captains for player in players):
                    raise _err(
                        "rollback_frees_captain",
                        "This pick seated the team's captain: replace the captain with a player who stays, then roll back",
                    )
            for player in players:
                player.status = DraftPlayerStatus.AVAILABLE.value
                player.drafted_by_team_id = None

        for pick in picks_to_revert:
            pick.picked_player_id = None
            pick.picked_by_workspace_member_id = None
            pick.is_autopick = False
            pick.is_admin_override = False
            pick.target_role_row = None
            pick.dimension_id = None
            pick.target_rank_value = None
            # The grace period is per pick: a pick autopicked out of overtime must
            # come back on its MAIN clock, not already "in overtime", or the next
            # expiry autopicks at once and the board shows a +m:ss clock.
            pick.overtime_started_at = None
            # Increment version to prevent race conditions from pending requests
            pick.version += 1

            if pick.id == last_resolved.id:
                pick.status = DraftPickStatus.ON_CLOCK.value
                pick.clock_remaining_ms = draft_session.pick_time_seconds * 1000
                pick.clock_started_at = None
                pick.clock_expires_at = None
            else:
                pick.status = DraftPickStatus.UPCOMING.value
                pick.clock_remaining_ms = None
                pick.clock_started_at = None
                pick.clock_expires_at = None

        draft_session.status = DraftStatus.PAUSED.value
        draft_session.blocked_reason = None
        draft_session.current_pick_id = last_resolved.id
        draft_session.export_status = None
        draft_session.exported_at = None

        await session.flush()
        return draft_session

    async def transition(
        self,
        session: AsyncSession,
        session_id: int,
        action: Callable[..., Awaitable[DraftSession]],
        *,
        event_type: str,
        audit_action: str,
        actor_auth_user_id: int,
        **action_kwargs: Any,
    ) -> DraftSession:
        """Run a status move on the session, journal it and publish ``event_type``.

        A mix draft's move takes the mix row first and re-reads the session under it -- the order the last pick, which
        writes the lobby's lineup, takes too (``selection``) -- so a move never lands on a draft that finished, or was
        cancelled, while it waited. Nothing moves a finished mix draft: it IS its lobby's lineup, maybe already on the
        floor (spec §5.1, §9.4), and a pause or a rollback would reopen it. The host re-forms the lobby instead."""
        draft = await self.get_session(session, session_id)
        if draft.custom_game_id is not None:
            await self.custom_games.get(session, draft.custom_game_id, for_update=True)
            await session.refresh(draft)
            if draft.status == DraftStatus.COMPLETED.value:
                raise _err(
                    "mix_draft_completed", "A finished mix draft is its lobby's lineup: re-form the lobby instead"
                )
        await action(session, draft, **action_kwargs)
        current = await self.picks_repo.get(session, draft.current_pick_id) if draft.current_pick_id else None
        payload: dict[str, Any] = {"session_id": draft.id, "status": draft.status}
        if current is not None:
            # Every lifecycle move names the pick it leaves on the clock. A resume
            # re-arms that pick's deadline and a rollback moves the clock back to an
            # earlier pick: a client that only folds events in has no other way to
            # learn either.
            payload["pick_id"] = current.id
            payload["draft_team_id"] = current.draft_team_id
            payload["clock_expires_at"] = current.clock_expires_at.isoformat() if current.clock_expires_at else None
            payload["pick_version"] = current.version
        # Journalled inside the transition's own transaction: the organizer's log
        # cannot show a move the board never made, nor miss one it did.
        await journal_service.record_lifecycle(
            session,
            draft,
            action=audit_action,
            actor_auth_user_id=actor_auth_user_id,
            after=None
            if current is None
            else {"pick_id": current.id, "overall_no": current.overall_no, "team_id": current.draft_team_id},
        )
        await draft_rt.publish_draft_event(
            session, draft_session=draft, event_type=event_type, payload=payload, actor_user_id=actor_auth_user_id
        )
        await draft_rt.mix_changed(session, draft, actor_user_id=actor_auth_user_id)
        return draft

    async def publish_result(
        self,
        session: AsyncSession,
        draft: DraftSession,
        result: DraftResult,
        *,
        made_event: str,
        actor_user_id: int | None,
    ) -> None:
        """Publish what a resolved pick did to the board: the pick, then completion, a block or the next clock."""
        if result.blocked_reason and result.next_pick is None:
            # Nothing was picked (role shortage) — the block is the whole story.
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.blocked",
                payload={
                    "session_id": draft.id,
                    "pick_id": result.pick.id,
                    "draft_team_id": result.pick.draft_team_id,
                    # `blocked_reason`, never `reason`: the vocabulary has exactly
                    # one meaning per field, and this one is the business cause.
                    "blocked_reason": result.blocked_reason,
                },
                actor_user_id=actor_user_id,
            )
            return
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft,
            event_type=made_event,
            payload=_pick_event_payload(draft, result.pick, dimension=await loaders.rated_dimension(session, draft)),
            actor_user_id=actor_user_id,
        )
        if result.completed:
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.completed",
                payload={"session_id": draft.id, "status": draft.status},
            )
        elif result.blocked_reason and result.next_pick is not None:
            # The pick landed, but the next round re-seated the teams and the draft
            # is paused: no pick_started, it would flip clients back to live.
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.blocked",
                payload={
                    "session_id": draft.id,
                    "pick_id": result.next_pick.id,
                    "draft_team_id": result.next_pick.draft_team_id,
                    "blocked_reason": result.blocked_reason,
                },
                actor_user_id=actor_user_id,
            )
        elif result.next_pick is not None:
            await draft_rt.publish_draft_event(
                session,
                draft_session=draft,
                event_type="draft.pick_started",
                payload={
                    "session_id": draft.id,
                    "pick_id": result.next_pick.id,
                    "overall_pick_no": result.next_pick.overall_no,
                    "draft_team_id": result.next_pick.draft_team_id,
                    "clock_expires_at": result.next_pick.clock_expires_at.isoformat()
                    if result.next_pick.clock_expires_at
                    else None,
                },
            )

    async def select_pick(
        self,
        session: AsyncSession,
        draft: DraftSession,
        pick: DraftPick,
        payload: schemas.DraftPickSelectRequest,
        *,
        actor_auth_user_id: int,
        is_admin: bool,
    ) -> None:
        """Resolve ``pick`` with the captain's choice and publish ``draft.pick_made``."""
        actor_user_id = await self.actor_player_id(session, actor_auth_user_id)
        result = await self.selection.select(
            session,
            draft,
            pick,
            player_id=payload.player_id,
            expected_version=payload.expected_version,
            target_role=await self.resolve_role(session, draft, payload.target_role),
            actor_user_id=actor_user_id,
            actor_auth_user_id=actor_auth_user_id,
            actor_player_ids=[actor_user_id] if actor_user_id is not None else [],
            is_admin=is_admin,
        )
        await self.publish_result(session, draft, result, made_event="draft.pick_made", actor_user_id=actor_user_id)

    async def autopick_pick(
        self,
        session: AsyncSession,
        draft: DraftSession,
        pick: DraftPick,
        *,
        expected_version: int,
        actor_auth_user_id: int,
    ) -> None:
        """The admin's "autopick now": resolve ``pick`` by the autopick strategy and publish ``draft.autopicked``."""
        result = await self.selection.autopick(
            session,
            draft,
            pick,
            expected_version=expected_version,
            actor_auth_user_id=actor_auth_user_id,
            # The cause is a property of the path: this is the admin's button, the
            # clock's own call is the one that reports ``expiry``.
            reason="admin",
        )
        await self.publish_result(session, draft, result, made_event="draft.autopicked", actor_user_id=None)

    async def override_pick(
        self,
        session: AsyncSession,
        draft: DraftSession,
        pick: DraftPick,
        payload: schemas.DraftPickOverrideRequest,
        *,
        actor_auth_user_id: int,
    ) -> None:
        """Resolve ``pick`` with an admin's choice, journal the override and publish ``draft.pick_made``."""
        before = _override_journal_state(pick)
        actor_user_id = await self.actor_player_id(session, actor_auth_user_id)
        result = await self.selection.override(
            session,
            draft,
            pick,
            player_id=payload.player_id,
            expected_version=payload.expected_version,
            actor_user_id=actor_user_id,
            target_role=await self.resolve_role(session, draft, payload.target_role),
        )
        await journal_service.record(
            session,
            draft.id,
            action="pick_overridden",
            entity_type="draft_pick",
            entity_id=pick.id,
            actor_auth_user_id=actor_auth_user_id,
            reason=payload.note,
            before=before,
            after=_override_journal_state(pick),
        )
        await self.publish_result(session, draft, result, made_event="draft.pick_made", actor_user_id=actor_user_id)


lifecycle_service = DraftLifecycleService()
