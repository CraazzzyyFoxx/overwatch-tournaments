"""Maps balancer-service's ``BalancerTeam`` wire payload onto ``team_export``'s ``MaterializationTeam`` input.

Also the plain-import entry point used by the admin teams-import RPC. The export paths (``admin/balancer.py``,
``draft/export.py``) build their own :class:`~src.services.team_export.ExportPlan` because they also need the
destructive cleanup, the ``exported_team_id`` backfill and their own stamp.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.disciplines import DISCIPLINES
from shared.domain.roster_shape import FLEX_SLOT_CODE
from shared.repository import TournamentRepository
from shared.services.balancer_realtime import BALANCER_TEAMS_CHANGED
from src.schemas.team import BalancerTeam, InternalBalancerTeamsPayload
from src.services.balancer.realtime import emit_balancer_data, stage_export_invalidation
from src.services.formation_node import require_forming
from src.services.team_export import (
    ExportOutcome,
    ExportPlan,
    MaterializationMember,
    MaterializationTeam,
    team_materialization,
)

__all__ = ("TeamService", "team_service", "to_materialization_teams")


def to_materialization_teams(payload: Sequence[BalancerTeam]) -> list[MaterializationTeam]:
    """``BalancerTeam`` -> materialization input.

    ``BalancerTeam.name`` is both the stored ``balancer_name`` and, by
    convention, the captain's battle tag; each member's ``name`` is their own
    tag.
    """
    return [
        MaterializationTeam(
            balancer_name=team.name,
            members=tuple(
                MaterializationMember(
                    name=member.name,
                    rank=member.rank,
                    slot_code=FLEX_SLOT_CODE if member.role is None else None,
                    role_ref=member.role,
                    sub_role=member.sub_role,
                )
                for member in team.members
            ),
        )
        for team in payload
    ]


class TeamService:
    async def import_teams(
        self,
        session: AsyncSession,
        tournament_id: int,
        formation_node_id: int,
        payload: Any,
        payload_format: str,
        *,
        actor_user_id: int,
    ) -> ExportOutcome:
        """Import an uploaded teams file into the forming node: create teams/players, no prior-export cleanup, no stamp.

        ``auto`` reads a ``{"data": {"teams": [...]}}`` dict as atravkovs and anything else
        as the internal format. Commits once (the orchestrator owns the boundary).
        """
        use_atravkovs = payload_format == "atravkovs" or (
            payload_format == "auto"
            and isinstance(payload, dict)
            and isinstance(payload.get("data"), dict)
            and "teams" in payload["data"]
        )
        if use_atravkovs:
            teams = [BalancerTeam.model_validate(team) for team in payload["data"]["teams"]]
        else:
            internal_payload = InternalBalancerTeamsPayload.model_validate(payload)
            tournament = await TournamentRepository().get(session, tournament_id)
            dimension = DISCIPLINES[tournament.discipline].rated_dimension.code
            teams = [team.to_balancer_team(dimension) for team in internal_payload.teams]
        await require_forming(session, formation_node_id)
        # ``run`` commits, so the signals are staged first to ride that commit.
        await emit_balancer_data(session, tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=actor_user_id)
        await stage_export_invalidation(session, tournament_id)
        return await team_materialization.run(
            session,
            ExportPlan(
                tournament_id=tournament_id,
                formation_node_id=formation_node_id,
                teams=to_materialization_teams(teams),
                # Lenient: an unresolvable battle tag skips that player rather
                # than failing the whole import.
                on_unresolved="skip",
            ),
        )


team_service = TeamService()
