"""Export a completed draft to tournament teams/players.

Synthesizes a ``BalancerTeam`` payload from the final rosters and hands it to the
shared team-materialization orchestrator, which owns the destructive cleanup, the
``exported_team_id`` backfill and the transaction boundary — the same sequence
``export_balance`` runs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import DraftPlayerStatus, DraftStatus
from shared.domain.player_sub_roles import workspace_sub_role_slug
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import FLEX_SLOT_CODE, RosterShape
from shared.models.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.repository.draft import (
    DraftPickRepository,
    DraftPlayerRepository,
    DraftSessionRepository,
    DraftTeamRepository,
)
from shared.schemas.role import RoleRef
from src.domain.draft import ranks
from src.domain.draft.errors import err as _err
from src.schemas.team import BalancerTeam, BalancerTeamMember
from src.services.balancer.realtime import stage_export_invalidation
from src.services.draft import loaders
from src.services.draft import realtime as draft_rt
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.rosters import DraftRosterService, draft_rosters
from src.services.formation_node import require_forming
from src.services.team import to_materialization_teams
from src.services.team_export import ExportPlan, refuse_missing_handles, sync_player_ranks, team_materialization


def _draft_to_balancer_payload(
    teams: list[DraftTeam],
    roster_by_team: dict[int, list[DraftPlayer]],
    shape: RosterShape,
    rosters: Mapping[int, PlayerRoster],
    pick_by_player_id: Mapping[int, DraftPick],
    dimension: str,
) -> list[BalancerTeam]:
    """Pure mapping: draft rosters -> balancer export payload.

    The team name is the captain's handle so the export's
    ``find_users_by_handles`` resolves the captain; members carry their
    handle, the slot they were *drafted into* (tank/damage/support), and the
    rank that pick froze. Mirrors the balancer's own payload (assigned role +
    assigned rating) so both feed the shared team materialization identically.

    A captain has no pick, so they are valued live on their seat role -- the
    one the organizer pinned, else their lead role (``ranks.seat_role``). A
    role-less (all-flex) shape drafted nobody onto a role, so it exports the
    ``flex`` open-slot code at the player's best playable rank
    (``ranks.drafted_rank``), the same number the board showed the captain who
    picked them.
    """
    payload: list[BalancerTeam] = []
    for team in sorted(teams, key=lambda t: t.draft_position):
        roster = roster_by_team.get(team.id, [])
        captain = next((p for p in roster if p.is_captain), None)
        captain_roster = rosters.get(captain.id) if captain is not None else None
        team_name = (captain_roster.handle if captain_roster is not None else None) or team.name

        members: list[BalancerTeamMember] = []
        for p in roster:
            player_roster = rosters.get(p.id)
            pk = pick_by_player_id.get(p.id)
            if shape.has_role_slots:
                # A resolved null role is an open slot, not a missing captain pin.
                role = pk.target_role if pk is not None else ranks.seat_role(player_roster, p.captain_role)
            else:
                role = FLEX_SLOT_CODE
            rank = ranks.drafted_rank(
                player_roster, role, shape, frozen=pk.target_rank_value if pk is not None else None
            )
            role_entry = (
                next((entry for entry in player_roster.roles if entry.role == role), None) if player_roster else None
            )
            members.append(
                BalancerTeamMember(
                    uuid=str(p.user_id) if p.user_id is not None else str(uuid4()),
                    name=(player_roster.handle if player_roster is not None else None) or "",
                    sub_role=workspace_sub_role_slug(role, role_entry.subrole)
                    if role_entry and role_entry.subrole
                    else None,
                    role=None if role in (None, FLEX_SLOT_CODE) else RoleRef(dimension=dimension, role=role),
                    rank=rank,
                )
            )
        # Like ``Team.avg_sr``/``total_sr``: an unranked member (``rank=None``) is left out, not counted as 0.
        ranked = [member.rank for member in members if member.rank is not None]
        total_sr = sum(ranked)
        avg_sr = (total_sr / len(ranked)) if ranked else 0.0
        payload.append(BalancerTeam(uuid=uuid4(), name=team_name, avgSr=avg_sr, totalSr=total_sr, members=members))
    return payload


class DraftExportService:
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

    async def _load_payload(
        self, session: AsyncSession, draft_session: DraftSession
    ) -> tuple[list[DraftTeam], list[BalancerTeam], Mapping[int, PlayerRoster]]:
        """Draft rosters -> export payload. Ranks resolve live except where a pick froze one."""
        teams = list(await self.teams_repo.list_by_session(session, draft_session.id))
        roster_rows = [
            p
            for p in await self.players_repo.list_by_session(
                session,
                draft_session.id,
                options=loaders.player_options(),
            )
            if p.status == DraftPlayerStatus.PICKED.value
        ]
        roster_by_team: dict[int, list[DraftPlayer]] = defaultdict(list)
        for p in roster_rows:
            if p.drafted_by_team_id is not None:
                roster_by_team[p.drafted_by_team_id].append(p)

        # Resolved picks carry the drafted role + its rank (frozen at finalize).
        pick_rows = await self.picks_repo.list_resolved(session, draft_session.id)
        pick_by_player_id = {pk.picked_player_id: pk for pk in pick_rows if pk.picked_player_id is not None}

        rosters = await self.rosters.load(session, draft_session, roster_rows)
        payload = _draft_to_balancer_payload(
            teams,
            roster_by_team,
            await self.feasibility.resolve_shape(session, draft_session),
            rosters,
            pick_by_player_id,
            await loaders.rated_dimension(session, draft_session),
        )
        return teams, payload, rosters

    async def export(
        self, session: AsyncSession, draft_session: DraftSession, *, actor_user_id: int | None = None
    ) -> tuple[DraftSession, int, int, list[str]]:
        """Export a COMPLETED draft, stage ``draft.completed`` and the export invalidation.

        Returns session, team counts and advisories.
        """
        if draft_session.status != DraftStatus.COMPLETED.value:
            raise _err("draft_not_completed", "Only a completed draft can be exported")
        await require_forming(session, draft_session.formation_node_id)

        teams, payload, rosters = await self._load_payload(session, draft_session)
        refuse_missing_handles(rosters.values())
        # Idempotent cleanup + insert + backfill + stamp, all in the shared
        # orchestrator's single transaction.
        linked_ids = [t.exported_team_id for t in teams if t.exported_team_id is not None]
        session_id = draft_session.id

        def _unlink() -> None:
            for t in teams:
                t.exported_team_id = None

        async def _finalize(inner: AsyncSession, by_name: Mapping[str, models.Team]) -> None:
            for team, mapped in zip(teams, payload, strict=False):
                public_team = by_name.get(mapped.name)
                if public_team is not None:
                    team.exported_team_id = public_team.id
            draft_session.exported_at = datetime.now(UTC)
            draft_session.export_status = "success"

        async def _on_failure(inner: AsyncSession, exc: BaseException) -> None:
            fresh = await self.sessions_repo.get(inner, session_id)
            if fresh is not None:
                fresh.export_status = "failed"

        outcome = await team_materialization.run(
            session,
            ExportPlan(
                tournament_id=draft_session.tournament_id,
                formation_node_id=draft_session.formation_node_id,
                teams=to_materialization_teams(payload),
                prior_team_ids=linked_ids,
                on_unresolved="skip",
                unlink=_unlink,
                finalize=_finalize,
                on_failure=_on_failure,
            ),
        )
        await draft_rt.publish_draft_event(
            session,
            draft_session=draft_session,
            event_type="draft.completed",
            payload={
                "session_id": draft_session.id,
                "status": draft_session.status,
                "export_status": draft_session.export_status,
            },
            actor_user_id=actor_user_id,
        )
        await stage_export_invalidation(session, draft_session.tournament_id)
        return draft_session, outcome.removed_teams, outcome.imported_teams, outcome.materialization.advisories

    async def export_ranks(self, session: AsyncSession, draft_session: DraftSession) -> int:
        """Re-push ranks onto the players this draft already exported. Never commits.

        Non-destructive counterpart to :meth:`export`: teams stay as they are, so a
        bracket built on them survives. Useful when a rank was fixed in the balancer
        after the export — the payload resolves ranks live except where a pick froze
        one. Returns how many player ranks actually changed.
        """
        if draft_session.status != DraftStatus.COMPLETED.value:
            raise _err("draft_not_completed", "Only a completed draft can be exported")

        teams, payload, _rosters = await self._load_payload(session, draft_session)
        updated = await sync_player_ranks(
            session,
            draft_session.formation_node_id,
            to_materialization_teams(payload),
            linked_team_ids=[t.exported_team_id for t in teams if t.exported_team_id is not None],
        )
        # Ranks only: no team is removed or created, so no draft lifecycle event.
        await stage_export_invalidation(session, draft_session.tournament_id)
        return updated


export_service = DraftExportService()
