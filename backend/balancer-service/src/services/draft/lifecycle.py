"""Draft session lifecycle: create, seed, and status transitions.

Services flush within the caller's transaction (routes/worker commit). Status
moves are guarded by ``shared.core.draft_state``. The pick clock is
DB-resumable: absolute ``clock_expires_at`` while live, frozen
``clock_remaining_ms`` while paused.

Pure business rules (seat ordering, registration mapping, seed-row building)
live in ``src.domain.draft.rules`` — this file holds only the orchestration
that needs a database session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import draft_state
from shared.core.enums import (
    DraftCaptainOrder,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftStatus,
    TournamentStatus,
)
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import RosterShape
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.models.tenancy.workspace import WorkspaceMember
from shared.models.tournament import Tournament
from shared.repository.draft import (
    DraftPickRepository,
    DraftPlayerRepository,
    DraftSessionRepository,
    DraftTeamRepository,
)
from shared.repository.workspace import get_or_create_workspace_member
from src.domain.draft import rules
from src.domain.draft.entities import PoolSeat
from src.domain.draft.errors import err as _err
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.rosters import DraftRosterService, draft_rosters

__all__ = ("DraftLifecycleService", "lifecycle_service")


class DraftLifecycleService:
    def __init__(
        self,
        *,
        sessions_repo: DraftSessionRepository = DraftSessionRepository(),
        teams_repo: DraftTeamRepository = DraftTeamRepository(),
        players_repo: DraftPlayerRepository = DraftPlayerRepository(),
        picks_repo: DraftPickRepository = DraftPickRepository(),
        feasibility: DraftFeasibilityService = feasibility_service,
        rosters: DraftRosterService = draft_rosters,
    ) -> None:
        self.sessions_repo = sessions_repo
        self.teams_repo = teams_repo
        self.players_repo = players_repo
        self.picks_repo = picks_repo
        self.feasibility = feasibility
        self.rosters = rosters

    async def assert_no_active_draft(self, session: AsyncSession, tournament_id: int) -> None:
        if await self.sessions_repo.exists_active_for_tournament(session, tournament_id):
            raise _err("draft_already_active", f"Tournament {tournament_id} already has an active draft")

    async def seed_row_counts(self, session: AsyncSession, session_id: int) -> tuple[int, int, int]:
        """Existing (team, player, pick) row counts for a session, in one round trip.

        Three scalar subqueries instead of three separate ``COUNT`` statements —
        used by the seed-diff preview (``rpc/draft.py``'s ``_seed`` handler) to
        report what a re-seed would replace. Deliberately not hidden behind a
        single-model repository: it spans three models in one query.
        """
        row = (
            await session.execute(
                sa.select(
                    *(
                        sa.select(sa.func.count())
                        .select_from(model)
                        .where(model.session_id == session_id)
                        .scalar_subquery()
                        for model in (DraftTeam, DraftPlayer, DraftPick)
                    )
                )
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)

    async def create_session(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        workspace_id: int,
        shape: RosterShape,
        pool_source: str = "balancer_balance",
        source_balance_id: int | None = None,
        fmt: DraftFormat = DraftFormat.SNAKE,
        pick_time_seconds: int = 45,
        overtime_seconds: int = 0,
        autopick_strategy: str = "best_fit",
        allow_admin_override: bool = True,
        settings: dict | None = None,
    ) -> DraftSession:
        # `rounds` is derived, never passed: the shape owns the roster size.
        await self.assert_no_active_draft(session, tournament_id)
        draft = DraftSession(
            tournament_id=tournament_id,
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

    async def resync_pick_order(self, session: AsyncSession, draft_session: DraftSession) -> int:
        """Re-seat every round that has not started yet. Returns how many picks moved.

        ``round_rules`` lives on the session while the pick rows are materialized at
        seed time, so changing a rule afterwards used to change nothing on the board:
        the wizard previewed the new order and the draft kept picking in the old one.
        Callers run this after a settings change so the two cannot disagree.

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
        captain_ranks = {
            captain.drafted_by_team_id: (rosters.get(captain.id).best_rank or -1)
            if rosters.get(captain.id) is not None
            else -1
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

        A seat carries a registration id and nothing else. Roles and ranks are
        NOT copied here -- they are resolved from the registration on every read,
        which is what makes a rank typed in the balancer after seeding show up in
        the draft without a re-seed.
        """
        if draft_session.status not in (DraftStatus.SETUP.value, DraftStatus.READY.value):
            raise _err("draft_not_seedable", "Draft can only be seeded in SETUP or READY")
        captains = [seat for seat in seats if seat.draft_position is not None]
        if not captains:
            raise _err("draft_no_captains", "At least one captain is required to seed a draft")

        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.READY)

        rosters = await self.rosters.pool(session, draft_session.tournament_id)
        missing = [seat.registration_id for seat in seats if seat.registration_id not in rosters]
        if missing:
            raise _err(
                "registration_not_in_pool",
                f"Registrations {sorted(missing)} are not in the balancer pool for this tournament",
                status_code=422,
            )
        # A registration the balancer ranks on no role has nothing to be drafted
        # on: seating it used to mint a ``damage`` player at rank 0. Refuse, and
        # name who needs a rank.
        unranked = [rosters[seat.registration_id] for seat in seats if not rosters[seat.registration_id].is_draftable]
        if unranked:
            raise rules.unranked_pool_error(unranked)

        # Re-seed: clear any prior teams/players/picks (cascade via relationships).
        await self.picks_repo.delete_by_session(session, draft_session.id)
        await self.players_repo.delete_by_session(session, draft_session.id)
        await self.teams_repo.delete_by_session(session, draft_session.id)
        draft_session.current_pick_id = None
        await session.flush()

        ordered_captains = sorted(captains, key=lambda seat: seat.draft_position or 0)

        # Resolve domain player ids -> workspace_member rows for this session's
        # workspace (dbarch03: draft identity is anchored on workspace_member).
        # Done once up front so every team/player row reuses the same member id.
        player_ids = {
            roster.player_id
            for roster in (rosters[seat.registration_id] for seat in seats)
            if roster.player_id is not None
        }
        member_by_player: dict[int, int] = {}
        if player_ids:
            # Batch-prefetch existing membership rows (the common case on re-seed)
            # instead of one INSERT..ON CONFLICT round-trip per player.
            rows = await session.execute(
                sa.select(WorkspaceMember.player_id, WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == draft_session.workspace_id,
                    WorkspaceMember.player_id.in_(player_ids),
                )
            )
            member_by_player = dict(rows.tuples().all())
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
            roster = rosters[seat.registration_id]
            team = DraftTeam(
                session_id=draft_session.id,
                captain_workspace_member_id=_member_id(roster),
                captain_auth_user_id=roster.auth_user_id,
                name=seat.team_name or roster.battle_tag or roster.display_name or f"Team {position}",
                draft_position=position,
            )
            teams.append(team)
            team_by_position[position] = team
        await self.teams_repo.create_many(session, teams)

        captain_registration_ids = {seat.registration_id for seat in ordered_captains}
        players_to_create: list[DraftPlayer] = []
        for position, seat in enumerate(ordered_captains, start=1):
            # Captains become PICKED players already on their own roster.
            roster = rosters[seat.registration_id]
            players_to_create.append(
                DraftPlayer(
                    session_id=draft_session.id,
                    registration_id=seat.registration_id,
                    workspace_member_id=_member_id(roster),
                    is_captain=True,
                    status=DraftPlayerStatus.PICKED.value,
                    drafted_by_team_id=team_by_position[position].id,
                )
            )
        for seat in seats:
            if seat.registration_id in captain_registration_ids:
                continue
            roster = rosters[seat.registration_id]
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
            team_by_position[position].id: (rosters[seat.registration_id].best_rank or -1)
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
    ) -> DraftSession:
        """Seed a draft from the balancer registration pool.

        ``captain_registration_ids`` are ``balancer.registration`` ids chosen as
        captains; ``captain_order`` decides seat order (WEAKEST_FIRST seats the
        lowest-rated captain at position 1). Every other in-pool registration
        becomes an available draft player. Ordering reads the engine's ranks --
        the same numbers the balancer sorted the captain picker by.
        """
        rosters = await self.rosters.pool(session, draft_session.tournament_id)
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
        ordered_ids = rules.order_captain_ids(
            [(registration_id, rosters[registration_id].best_rank) for registration_id in captain_registration_ids],
            captain_order,
            rng_seed,
        )
        captain_ids = set(ordered_ids)
        seats = [
            PoolSeat(
                registration_id=registration_id,
                draft_position=position,
                team_name=team_names.get(registration_id),
            )
            for position, registration_id in enumerate(ordered_ids, start=1)
        ]
        seats.extend(
            PoolSeat(registration_id=registration_id)
            for registration_id in sorted(rosters)
            if registration_id not in captain_ids
        )
        return await self.seed(session, draft_session, seats=seats)

    async def _first_upcoming(self, session: AsyncSession, draft_session_id: int) -> DraftPick | None:
        return await self.picks_repo.first_upcoming(session, draft_session_id)

    async def start(self, session: AsyncSession, draft_session: DraftSession, *, force: bool = False) -> DraftSession:
        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.LIVE)
        # The phase gate keeps organizers from going live before the tournament
        # reaches its draft phase. A superuser may bypass it (``force``) to run a
        # draft out of band — a test run, or a rescue after the schedule drifted.
        if not force:
            tournament_status = await session.scalar(
                sa.select(Tournament.status).where(Tournament.id == draft_session.tournament_id)
            )
            if tournament_status != TournamentStatus.DRAFT.value:
                raise _err(
                    "tournament_not_in_draft_phase",
                    "Draft can only start while the tournament is in the draft phase",
                )
        first = await self._first_upcoming(session, draft_session.id)
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
    ) -> DraftPick:
        """Give the on-clock captain more time, live or paused.

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
            raise _err("pick_already_resolved", "Pick was already resolved")

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

    async def rollback(self, session: AsyncSession, draft_session: DraftSession) -> DraftSession:
        """Rollback the last resolved pick, resetting player/pick states and pausing the draft."""
        draft_state.validate_transition(DraftStatus(draft_session.status), DraftStatus.PAUSED)

        # Find the last resolved pick (completed, autopicked, or skipped). Not a
        # repository method: the status set (including SKIPPED) and the
        # desc-ordered "most recent" lookup are specific to this one caller, not a
        # generic CRUD shape (``repository-boundaries.md``: bespoke filters stay in
        # the service).
        last_resolved = await session.scalar(
            sa.select(DraftPick)
            .where(
                DraftPick.session_id == draft_session.id,
                DraftPick.status.in_(
                    [
                        DraftPickStatus.COMPLETED.value,
                        DraftPickStatus.AUTOPICKED.value,
                        DraftPickStatus.SKIPPED.value,
                    ]
                ),
            )
            .order_by(DraftPick.overall_no.desc())
            .limit(1)
        )
        if last_resolved is None:
            raise _err("no_picks_to_rollback", "There are no resolved picks to rollback")

        # Find all picks with overall_no >= last_resolved.overall_no
        picks_to_revert = (
            await session.scalars(
                sa.select(DraftPick)
                .where(
                    DraftPick.session_id == draft_session.id,
                    DraftPick.overall_no >= last_resolved.overall_no,
                )
                .order_by(DraftPick.overall_no.asc())
            )
        ).all()

        player_ids_to_free = [p.picked_player_id for p in picks_to_revert if p.picked_player_id is not None]
        if player_ids_to_free:
            players = await self.players_repo.bulk_get(session, player_ids_to_free)
            for player in players:
                player.status = DraftPlayerStatus.AVAILABLE.value
                player.drafted_by_team_id = None

        for pick in picks_to_revert:
            pick.picked_player_id = None
            pick.picked_by_workspace_member_id = None
            pick.is_autopick = False
            pick.is_admin_override = False
            pick.target_role = None
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


lifecycle_service = DraftLifecycleService()
