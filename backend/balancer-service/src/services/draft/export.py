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

from shared.core.enums import DraftPlayerStatus, DraftStatus
from shared.domain.roster import PlayerRoster
from shared.domain.roster_shape import FLEX_SLOT_CODE, RosterShape
from shared.models.balancer.draft import DraftPick, DraftPlayer, DraftSession, DraftTeam
from shared.repository.draft import DraftPickRepository, DraftPlayerRepository, DraftTeamRepository
from shared.services.team_export import ExportPlan, sync_player_ranks, team_materialization
from src import models
from src.domain.draft import ranks
from src.schemas.team import BalancerTeam, BalancerTeamMember
from src.services.draft import loaders
from src.services.draft._errors import err as _err
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.rosters import DraftRosterService, draft_rosters
from src.services.team import to_materialization_teams


def _draft_to_balancer_payload(
    teams: list[DraftTeam],
    roster_by_team: dict[int, list[DraftPlayer]],
    shape: RosterShape,
    rosters: Mapping[int, PlayerRoster],
    pick_by_player_id: Mapping[int, DraftPick],
) -> list[BalancerTeam]:
    """Pure mapping: draft rosters -> balancer export payload.

    The team name is the captain's battle_tag so the export's
    ``find_users_by_battle_tags`` resolves the captain; members carry their
    battle_tag, the slot they were *drafted into* (tank/damage/support), and the
    rank that pick froze. Mirrors the balancer's own payload (assigned role +
    assigned rating) so both feed ``bulk_create_from_balancer`` identically.

    A captain has no pick, so they are valued live on their lead role. A
    role-less (all-flex) shape drafted nobody onto a role, so it exports the
    ``flex`` slot code -- stored as ``HeroClass.flex`` -- at the player's best
    playable rank, the same number the board showed the captain who picked
    them; the frozen pick rank is skipped there because it was frozen against a
    role the shape gives no meaning to.
    """
    payload: list[BalancerTeam] = []
    for team in sorted(teams, key=lambda t: t.draft_position):
        roster = roster_by_team.get(team.id, [])
        captain = next((p for p in roster if p.is_captain), None)
        captain_roster = rosters.get(captain.id) if captain is not None else None
        team_name = (captain_roster.battle_tag if captain_roster is not None else None) or team.name

        members: list[BalancerTeamMember] = []
        total_sr = 0
        for p in roster:
            player_roster = rosters.get(p.id)
            lead = player_roster.primary if player_roster is not None else None
            pk = pick_by_player_id.get(p.id)
            if shape.has_role_slots:
                role = (pk.target_role if (pk and pk.target_role) else None) or (
                    lead.role.slot_code if lead is not None else FLEX_SLOT_CODE
                )
                rank = (
                    pk.target_rank_value
                    if (pk is not None and pk.target_rank_value is not None)
                    else (ranks.slot_rank(player_roster, role, shape) or 0)
                )
            else:
                role = FLEX_SLOT_CODE
                rank = ranks.slot_rank(player_roster, None, shape) or 0
            total_sr += rank
            members.append(
                BalancerTeamMember(
                    uuid=str(p.user_id) if p.user_id is not None else str(uuid4()),
                    name=(player_roster.battle_tag if player_roster is not None else None) or "",
                    sub_role=player_roster.sub_role if player_roster is not None else None,
                    role=role,  # tank/damage/support/flex
                    rank=rank,
                )
            )
        avg_sr = (total_sr / len(members)) if members else 0.0
        payload.append(BalancerTeam(uuid=uuid4(), name=team_name, avgSr=avg_sr, totalSr=total_sr, members=members))
    return payload


class DraftExportService:
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

    async def _load_payload(
        self, session: AsyncSession, draft_session: DraftSession
    ) -> tuple[list[DraftTeam], list[BalancerTeam]]:
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

        payload = _draft_to_balancer_payload(
            teams,
            roster_by_team,
            await self.feasibility.resolve_shape(session, draft_session),
            await self.rosters.load(session, draft_session, roster_rows),
            pick_by_player_id,
        )
        return teams, payload

    async def export(self, session: AsyncSession, draft_session: DraftSession) -> tuple[DraftSession, int, int]:
        """Export a COMPLETED draft. Returns (session, removed_teams, imported_teams)."""
        if draft_session.status != DraftStatus.COMPLETED.value:
            raise _err("draft_not_completed", "Only a completed draft can be exported")

        teams, payload = await self._load_payload(session, draft_session)
        # Idempotent cleanup + insert + backfill + stamp, all in the shared
        # orchestrator's single transaction (it used to be two: the writer committed
        # the deletes and inserts internally, and the caller committed the backfill).
        linked_ids = [t.exported_team_id for t in teams if t.exported_team_id is not None]

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
            fresh = await inner.get(DraftSession, draft_session.id)
            if fresh is not None:
                fresh.export_status = "failed"

        outcome = await team_materialization.run(
            session,
            ExportPlan(
                tournament_id=draft_session.tournament_id,
                teams=to_materialization_teams(payload),
                prior_team_ids=linked_ids,
                on_unresolved="skip",
                unlink=_unlink,
                finalize=_finalize,
                on_failure=_on_failure,
            ),
        )
        return draft_session, outcome.removed_teams, outcome.imported_teams

    async def export_ranks(self, session: AsyncSession, draft_session: DraftSession) -> int:
        """Re-push ranks onto the players this draft already exported. Never commits.

        Non-destructive counterpart to :meth:`export`: teams stay as they are, so a
        bracket built on them survives. Useful when a rank was fixed in the balancer
        after the export — the payload resolves ranks live except where a pick froze
        one. Returns how many player ranks actually changed.
        """
        if draft_session.status != DraftStatus.COMPLETED.value:
            raise _err("draft_not_completed", "Only a completed draft can be exported")

        _teams, payload = await self._load_payload(session, draft_session)
        return await sync_player_ranks(session, draft_session.tournament_id, to_materialization_teams(payload))


export_service = DraftExportService()
