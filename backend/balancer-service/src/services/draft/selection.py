"""Draft pick selection, autopick, override, and board advance.

The select-vs-autopick race is resolved by a single conditional UPDATE guarded
by both ``status='on_clock'`` and the optimistic ``version`` token: exactly one
writer's ``rowcount`` is 1, the loser gets a 409. Events are published by the
caller within the same transaction so WorkspaceEvent ids preserve pick order.

Pure business rules (slot counting, role legality, feasibility-error shaping)
live in ``src.domain.draft.rules`` — this file holds only the orchestration
that needs a database session.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import (
    HERO_TYPE_CLASSES,
    DraftAutopickStrategy,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftStatus,
    HeroClass,
)
from shared.domain.roster_shape import RosterShape
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.repository.draft import DraftPickRepository, DraftPlayerRepository, DraftTeamRepository
from shared.repository.workspace import get_or_create_workspace_member
from src.domain.draft import ranks as domain_ranks
from src.domain.draft import rules
from src.domain.draft.entities import AutopickChoice, DraftAssignment, DraftResult, DraftSnapshot
from src.domain.draft.fit import FitConfig, best_fit, fit_players
from src.services.draft import loaders
from src.services.draft._errors import err as _err
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.journal import journal_service
from src.services.draft.rosters import DraftRosterService, draft_rosters

__all__ = ("DraftSelectionService", "selection_service")


class DraftSelectionService:
    def __init__(
        self,
        *,
        teams_repo: DraftTeamRepository = DraftTeamRepository(),
        players_repo: DraftPlayerRepository = DraftPlayerRepository(),
        picks_repo: DraftPickRepository = DraftPickRepository(),
        feasibility: DraftFeasibilityService = feasibility_service,
        rosters: DraftRosterService = draft_rosters,
    ) -> None:
        self.teams_repo = teams_repo
        self.players_repo = players_repo
        self.picks_repo = picks_repo
        self.feasibility = feasibility
        self.rosters = rosters

    async def _actor_member_id(
        self, session: AsyncSession, draft_session: DraftSession, actor_user_id: int | None
    ) -> int | None:
        """Resolve an acting captain's domain player id to a workspace_member id.

        dbarch03 anchors ``draft_pick.picked_by`` on ``workspace_member``; the actor
        is identified by their public player id, so map it (idempotently create) to a
        member in this draft's workspace.
        """
        if actor_user_id is None:
            return None
        member = await get_or_create_workspace_member(
            session, workspace_id=draft_session.workspace_id, player_id=actor_user_id
        )
        return member.id

    async def _finalize(
        self,
        session: AsyncSession,
        pick_id: int,
        *,
        status: DraftPickStatus,
        player_id: int | None,
        picked_by_member_id: int | None,
        is_autopick: bool,
        is_admin_override: bool,
        expected_version: int,
    ) -> bool:
        """Atomic conditional finalize. Returns True iff this writer won the race."""
        return await self.picks_repo.finalize_if_on_clock(
            session,
            pick_id,
            expected_version=expected_version,
            status=status,
            player_id=player_id,
            picked_by_member_id=picked_by_member_id,
            is_autopick=is_autopick,
            is_admin_override=is_admin_override,
        )

    async def _apply_dynamic_round_order(
        self, session: AsyncSession, draft_session: DraftSession, next_pick: DraftPick
    ) -> bool:
        """Re-seat a CUSTOM round whose rule ranks teams by their live average.

        Runs on the first pick of a round only. Returns True when the seating
        actually moved — the caller locks the draft on that, so nobody picks
        against the order they were reading a second ago.
        """
        if next_pick.pick_in_round != 1 or draft_session.format != DraftFormat.CUSTOM.value:
            return False
        round_rules = draft_session.settings_json.get("round_rules") or []
        round_idx = next_pick.round_no - 1
        rule = round_rules[round_idx] if round_idx < len(round_rules) else None
        # The seat-order vocabulary lives once, in rules: seeding, the settings
        # resync and this live re-seat have to agree on which rules are dynamic.
        if rule not in rules.DYNAMIC_ROUND_RULES:
            return False

        # Average the drafted-role rank (off-role aware), not the lead-role one.
        avg_by_team = await self._team_avg_drafted_rank(
            session, draft_session, await self.feasibility.resolve_shape(session, draft_session)
        )
        teams = await self.teams_repo.list_by_session(session, draft_session.id)
        # Tie-break for equal averages — same shape as lifecycle.resync_pick_order's,
        # so a live re-seat and a settings resync rank captains identically.
        captains = await self.players_repo.list_drafted_captains(session, draft_session.id)
        captain_rosters = await self.rosters.load(session, draft_session, captains)
        captain_ranks = {
            captain.drafted_by_team_id: (
                (captain_rosters[captain.id].best_rank or -1) if captain.id in captain_rosters else -1
            )
            for captain in captains
        }
        sorted_team_ids = [
            team.id
            for team in rules.average_seat_order(
                list(teams),
                averages=avg_by_team,
                captain_ranks=captain_ranks,
                descending=rule == "team_avg_desc",
            )
        ]
        round_picks = await self.picks_repo.list_by_round(session, draft_session.id, next_pick.round_no)

        changed = False
        for pick_to_update, team_id in zip(round_picks, sorted_team_ids, strict=False):
            if pick_to_update.draft_team_id != team_id:
                pick_to_update.draft_team_id = team_id
                changed = True
        await session.flush()
        # round_picks returned the identity-mapped objects, so next_pick's
        # draft_team_id reassignment above is already visible in memory.
        return changed

    async def _advance(self, session: AsyncSession, draft_session: DraftSession) -> DraftPick | None:
        """Move the next UPCOMING pick to ON_CLOCK, or complete the draft.

        When the starting round re-seated the teams under the captains (a dynamic
        ``team_avg_*`` rule), the pick goes on the clock unarmed and the session
        pauses instead of running: the board changed order, so everyone has to
        re-read it before anyone may act. An admin resume arms a full pick timer.
        """
        next_pick = await self.picks_repo.next_upcoming_locked(session, draft_session.id)
        if next_pick is None:
            draft_session.status = DraftStatus.COMPLETED.value
            draft_session.current_pick_id = None
            # No actor: the last pick completed the draft, nobody decided to.
            await journal_service.record_lifecycle(session, draft_session, action="completed", actor_auth_user_id=None)
            await session.flush()
            return None

        reordered = await self._apply_dynamic_round_order(session, draft_session, next_pick)

        next_pick.status = DraftPickStatus.ON_CLOCK.value
        next_pick.clock_remaining_ms = None
        # A fresh pick starts on its main clock: the grace period is per pick.
        next_pick.overtime_started_at = None
        draft_session.current_pick_id = next_pick.id
        if reordered:
            draft_session.status = DraftStatus.PAUSED.value
            draft_session.blocked_reason = "order_recalculated"
            # No deadline and no recorded remainder: lifecycle.resume() arms a full
            # pick timer for whoever the new order put on the clock.
            next_pick.clock_started_at = None
            next_pick.clock_expires_at = None
        else:
            now = datetime.now(UTC)
            next_pick.clock_started_at = now
            next_pick.clock_expires_at = now + timedelta(seconds=draft_session.pick_time_seconds)
        await session.flush()
        return next_pick

    async def _apply_won(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        pick: DraftPick,
        player: DraftPlayer,
    ) -> DraftResult:
        player.status = DraftPlayerStatus.PICKED.value
        player.drafted_by_team_id = pick.draft_team_id
        await session.flush()
        next_pick = await self._advance(session, draft_session)
        # No refresh needed: _finalize syncs the pick via synchronize_session and
        # draft_session was only mutated in Python (expire_on_commit=False).
        return DraftResult(
            pick=pick,
            next_pick=next_pick,
            completed=next_pick is None,
            # Set by _advance when the next round re-seated the teams.
            blocked_reason=draft_session.blocked_reason,
        )

    async def _team_avg_drafted_rank(
        self, session: AsyncSession, draft_session: DraftSession, shape: RosterShape
    ) -> dict[int, float]:
        """Average drafted-role rank per team (picked players + captains).

        Uses each pick's frozen ``target_rank_value`` -- the one derivation the
        draft still stores, because it is a fact about a pick that happened.
        Captains have no pick, so they are valued live on their lead role. A
        role-less shape ignores the frozen value: it was frozen against a role
        the shape gives no meaning to, so ``slot_rank`` re-derives the same
        maximum every other reader of a flex draft shows.
        """
        all_players = await self.players_repo.list_by_session(
            session, draft_session.id, options=loaders.player_options()
        )
        players = [
            p for p in all_players if p.drafted_by_team_id is not None and p.status == DraftPlayerStatus.PICKED.value
        ]
        picks = await self.picks_repo.list_resolved(session, draft_session.id)
        pick_by_player_id = {pk.picked_player_id: pk for pk in picks if pk.picked_player_id is not None}
        rosters = await self.rosters.load(session, draft_session, players)

        sums: dict[int, float] = {}
        counts: dict[int, int] = {}
        for p in players:
            pk = pick_by_player_id.get(p.id)
            if shape.has_role_slots and pk is not None and pk.target_rank_value is not None:
                rank = pk.target_rank_value
            else:
                roster = rosters.get(p.id)
                lead = roster.primary if roster is not None else None
                role = (pk.target_role if pk else None) or (lead.role if lead is not None else None)
                rank = domain_ranks.slot_rank(roster, role, shape) or 0
            tid = p.drafted_by_team_id
            sums[tid] = sums.get(tid, 0.0) + rank
            counts[tid] = counts.get(tid, 0) + 1
        return {tid: sums[tid] / counts[tid] for tid in sums}

    async def select(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        pick: DraftPick,
        *,
        player_id: int,
        expected_version: int,
        target_role: HeroClass | None,
        actor_user_id: int | None,
        actor_auth_user_id: int | None = None,
        actor_player_ids: Collection[int] = (),
        is_admin: bool,
    ) -> DraftResult:
        rules.validate_current_pick(draft_session, pick)
        # captain_user_id (read in rules.is_on_clock_captain) resolves via
        # captain_member; eager-load it so the property read never triggers an
        # async lazy load.
        team = await self.teams_repo.get(
            session, pick.draft_team_id, options=loaders.team_options(), populate_existing=True
        )
        player_ids = set(actor_player_ids)
        if actor_user_id is not None:
            player_ids.add(actor_user_id)
        if not is_admin and not rules.is_on_clock_captain(
            team,
            actor_auth_user_id=actor_auth_user_id,
            actor_player_ids=player_ids,
        ):
            raise _err("not_your_pick", "Only the on-clock captain may pick", status_code=403)
        snapshot = await self.feasibility.load_snapshot(session, draft_session)
        shape = await self.feasibility.resolve_shape(session, draft_session)
        player = rules.available_player_from(snapshot, player_id)
        roster = snapshot.roster(player.id)
        counts = rules.team_slot_counts(snapshot.players, snapshot.picks, pick.draft_team_id, shape, snapshot.rosters)
        decision = rules.resolve_pick_slot(shape, counts, roster, target_role)

        feasibility_report = await self.feasibility.analyze_session(
            session,
            draft_session,
            state=await self.feasibility.state_from_snapshot(session, draft_session, snapshot),
            hypothetical=DraftAssignment(
                player_id=player.id,
                team_id=pick.draft_team_id,
                slot_code=decision.role.slot_code,
            ),
        )
        if not feasibility_report.is_feasible:
            raise rules.unsafe_pick_error(feasibility_report)

        won = await self._finalize(
            session,
            pick.id,
            status=DraftPickStatus.COMPLETED,
            player_id=player.id,
            picked_by_member_id=await self._actor_member_id(session, draft_session, actor_user_id),
            is_autopick=False,
            is_admin_override=False,
            expected_version=expected_version,
        )
        if not won:
            raise _err("pick_already_resolved", "Pick was already resolved")
        # Always record the resolved decision (role + its rank) on the pick, so the
        # pick is a complete (player, role, rank) record regardless of off-role. A
        # role-less roster records no role: recorded_role is None there.
        pick.target_role = decision.recorded_role
        pick.target_rank_value = domain_ranks.slot_rank(roster, decision.role, shape)
        await journal_service.record(
            session,
            draft_session.id,
            action="pick_made",
            entity_type="draft_pick",
            entity_id=pick.id,
            actor_auth_user_id=actor_auth_user_id,
            after={
                "pick_id": pick.id,
                "overall_no": pick.overall_no,
                "team_id": pick.draft_team_id,
                "player_id": player.id,
                "role": pick.target_role,
            },
        )
        return await self._apply_won(session, draft_session, pick, player)

    def _queued_choice(
        self,
        team: DraftTeam | None,
        snapshot: DraftSnapshot,
        safe_by_player: Mapping[int, set[HeroClass]],
        available_ids: Collection[int],
    ) -> AutopickChoice | None:
        """The captain's own list, consulted before the fit strategy.

        The first queued player who is still available AND has at least one
        globally safe option wins -- a queued player whose every option would
        strand a role slot is skipped, never forced, because autopick may not
        break the draft on a captain's behalf. Their role is the safe option they
        are ranked highest on; ties go to their primary role, then canonical slot
        order, so the same queue always yields the same pick.
        """
        for player_id in (team.pick_queue if team is not None else None) or []:
            if player_id not in available_ids:
                continue
            safe_roles = safe_by_player.get(player_id)
            if not safe_roles:
                continue
            roster = snapshot.roster(player_id)
            lead = roster.primary.role if (roster is not None and roster.primary is not None) else None
            role = min(
                safe_roles,
                key=lambda candidate: (
                    -((roster.rank_on(candidate) if roster is not None else None) or 0),
                    candidate is not lead,
                    HERO_TYPE_CLASSES.index(candidate),
                ),
            )
            return AutopickChoice(player_id=player_id, role=role, source="queue")
        return None

    async def autopick_choice(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        pick: DraftPick,
        *,
        snapshot: DraftSnapshot | None = None,
    ) -> AutopickChoice | None:
        """WHO autopick takes and WHY -- without taking them.

        The single code path behind both the clock's autopick and the captain's
        queue preview: a preview that ran its own ranking would eventually show a
        different player than the clock takes, which is the one thing a priority
        list may not do. ``None`` means no globally safe option exists at all
        (the caller pauses on a role shortage).
        """
        if snapshot is None:
            snapshot = await self.feasibility.load_snapshot(session, draft_session)
        shape = await self.feasibility.resolve_shape(session, draft_session)
        available = [p for p in snapshot.players if p.status == DraftPlayerStatus.AVAILABLE.value]
        counts = rules.team_slot_counts(snapshot.players, snapshot.picks, pick.draft_team_id, shape, snapshot.rosters)
        capacity = rules.role_openings(shape, counts)
        options = await self.feasibility.evaluate_session_pick_options(
            session,
            draft_session,
            team_id=pick.draft_team_id,
            state=await self.feasibility.state_from_snapshot(session, draft_session, snapshot),
        )
        safe_by_player: dict[int, set[HeroClass]] = {}
        for option in options:
            if option.is_safe:
                safe_by_player.setdefault(option.player_id, set()).add(option.role)

        available_ids = {p.id for p in available}
        team = next((t for t in snapshot.teams if t.id == pick.draft_team_id), None)
        queued = self._queued_choice(team, snapshot, safe_by_player, available_ids)
        if queued is not None:
            return queued

        # Fit is built from the engine's rosters: a player is scored at the rank
        # of the role they would actually fill, and a player the balancer ranks
        # on no role is not a candidate at all (rather than a rank-0 last resort).
        choice = best_fit(
            fit_players(available, snapshot.rosters),
            capacity,
            DraftAutopickStrategy(draft_session.autopick_strategy),
            FitConfig(),
            allowed_options={(player_id, role) for player_id, roles in safe_by_player.items() for role in roles},
        )
        if choice is None:
            return None
        return AutopickChoice(player_id=choice.player_id, role=choice.role, source="fit")

    async def autopick(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        pick: DraftPick,
        *,
        expected_version: int,
        actor_user_id: int | None = None,
        actor_auth_user_id: int | None = None,
        reason: str = "expiry",
    ) -> DraftResult:
        rules.validate_current_pick(draft_session, pick)
        snapshot = await self.feasibility.load_snapshot(session, draft_session)
        shape = await self.feasibility.resolve_shape(session, draft_session)
        choice = await self.autopick_choice(session, draft_session, pick, snapshot=snapshot)

        if choice is None:
            result = rules.mark_role_shortage_paused(draft_session, pick)
            await session.flush()
            return result

        won = await self._finalize(
            session,
            pick.id,
            status=DraftPickStatus.AUTOPICKED,
            player_id=choice.player_id,
            picked_by_member_id=None,
            is_autopick=True,
            is_admin_override=False,
            expected_version=expected_version,
        )
        if not won:
            raise _err("pick_already_resolved", "Pick was already resolved")
        player = next(p for p in snapshot.players if p.id == choice.player_id)
        roster = snapshot.roster(player.id)
        pick.target_role = choice.role.slot_code if shape.has_role_slots else None
        pick.target_rank_value = domain_ranks.slot_rank(roster, choice.role, shape)
        await journal_service.record(
            session,
            draft_session.id,
            action="pick_autopicked",
            entity_type="draft_pick",
            entity_id=pick.id,
            actor_auth_user_id=actor_auth_user_id,
            reason=reason,
            after={
                "pick_id": pick.id,
                "overall_no": pick.overall_no,
                "team_id": pick.draft_team_id,
                "player_id": player.id,
                "role": pick.target_role,
                "source": choice.source,
            },
        )
        return await self._apply_won(session, draft_session, pick, player)

    async def override(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        pick: DraftPick,
        *,
        player_id: int | None,
        expected_version: int,
        actor_user_id: int | None,
        target_role: HeroClass | None = None,
    ) -> DraftResult:
        if not draft_session.allow_admin_override:
            raise _err("override_disabled", "Admin override is disabled for this draft")
        rules.validate_current_pick(draft_session, pick)
        if player_id is None:
            raise _err("override_needs_player", "Override requires a player_id", status_code=422)
        snapshot = await self.feasibility.load_snapshot(session, draft_session)
        shape = await self.feasibility.resolve_shape(session, draft_session)
        player = rules.available_player_from(snapshot, player_id)
        roster = snapshot.roster(player.id)
        counts = rules.team_slot_counts(snapshot.players, snapshot.picks, pick.draft_team_id, shape, snapshot.rosters)
        decision = rules.resolve_pick_slot(shape, counts, roster, target_role)
        feasibility_report = await self.feasibility.analyze_session(
            session,
            draft_session,
            state=await self.feasibility.state_from_snapshot(session, draft_session, snapshot),
            hypothetical=DraftAssignment(
                player_id=player.id,
                team_id=pick.draft_team_id,
                slot_code=decision.role.slot_code,
            ),
        )
        if not feasibility_report.is_feasible:
            raise rules.unsafe_pick_error(feasibility_report)

        won = await self._finalize(
            session,
            pick.id,
            status=DraftPickStatus.COMPLETED,
            player_id=player.id,
            picked_by_member_id=await self._actor_member_id(session, draft_session, actor_user_id),
            is_autopick=False,
            is_admin_override=True,
            expected_version=expected_version,
        )
        if not won:
            raise _err("pick_already_resolved", "Pick was already resolved")
        pick.target_role = decision.recorded_role
        pick.target_rank_value = domain_ranks.slot_rank(roster, decision.role, shape)
        return await self._apply_won(session, draft_session, pick, player)


selection_service = DraftSelectionService()
