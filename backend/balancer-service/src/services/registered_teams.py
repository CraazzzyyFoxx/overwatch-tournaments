"""Materialize pre-formed registered teams into ``tournament.team``.

Runs the same materialization orchestrator as ``admin/balancer.py`` (balance export)
and ``draft/export.py`` (draft export): balancer-service is the single writer of
``tournament.team``/``tournament.player``.

Two settings differ from those callers, both deliberately:

* ``guard_standings=True``. The balancer and draft exports re-export destructively,
  and their operators expect that. A registered-team re-export after a bracket
  exists would silently invalidate it, so it refuses instead.
* ``on_unresolved="error"``. Registered members arrive with
  ``workspace_member_id`` already set, so a failure to resolve one is a bug rather
  than a data-quality fact. ``"skip"`` would produce an under-sized roster with no
  error anywhere — the exact failure the materialization writer's docstring warns about.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import ApiExc, ApiHTTPException
from shared.repository import RegistrationTeamRepository, TournamentRepository
from shared.services.balancer_realtime import BALANCER_TEAMS_CHANGED
from shared.services.flow_queries import upstream_registration_node_ids
from shared.services.team_format import tournament_slot_shape
from src.services.balancer.realtime import emit_balancer_data, stage_export_invalidation
from src.services.formation_node import require_forming
from src.services.team_export import ExportPlan, team_materialization
from src.services.team_export.registered import SkippedTeam, build_registered_export

__all__ = ("RegisteredExportResult", "RegisteredTeamsService", "registered_teams_service")


@dataclass
class RegisteredExportResult:
    removed_teams: int = 0
    imported_teams: int = 0
    created_players: int = 0
    skipped: list[SkippedTeam] = field(default_factory=list)


def _err(code: str, msg: str, status_code: int = 400) -> ApiHTTPException:
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(msg=msg, code=code)])


class RegisteredTeamsService:
    def __init__(
        self,
        *,
        tournaments: TournamentRepository = TournamentRepository(),
        registration_teams: RegistrationTeamRepository = RegistrationTeamRepository(),
    ) -> None:
        self.tournaments = tournaments
        self.registration_teams = registration_teams

    async def export_registered(
        self,
        session: AsyncSession,
        tournament_id: int,
        formation_node_id: int,
        *,
        team_ids: Sequence[int] | None = None,
        actor_user_id: int,
    ) -> RegisteredExportResult:
        """Export the complete registered teams of this formation's upstream registration nodes. Commits (via the
        orchestrator) or rolls back as one unit; the realtime signals are staged after
        that commit, so the caller commits once more to publish them.

        Nothing to export is a **success with an empty result**, not an error: an
        organizer clicking export before any team completed should be told which teams
        are incomplete, which is exactly what ``skipped`` carries.
        """
        tournament = await self.tournaments.get(session, tournament_id)
        if tournament is None:
            raise _err("not_found", f"Tournament {tournament_id} not found", status_code=404)
        await require_forming(session, formation_node_id, mode="registered")

        shape = await tournament_slot_shape(session, tournament_id)

        upstream = await upstream_registration_node_ids(session, formation_node_id)
        payload = await build_registered_export(session, tournament_id, shape, upstream, team_ids=team_ids)
        if not payload.teams:
            # No transaction at all: there is nothing to delete and nothing to write,
            # so running the orchestrator would only take the standings guard for no
            # reason.
            return RegisteredExportResult(skipped=payload.skipped)

        source_teams = payload.source_teams
        source_ids = [team.id for team in source_teams]

        def _unlink() -> None:
            for team in source_teams:
                team.exported_team_id = None

        async def _finalize(inner: AsyncSession, by_name: Mapping[str, models.Team]) -> None:
            stamped = datetime.now(UTC)
            for source, mapped in zip(source_teams, payload.teams, strict=True):
                public_team = by_name.get(mapped.balancer_name)
                if public_team is not None:
                    source.exported_team_id = public_team.id
                source.exported_at = stamped
                source.export_status = "success"
                source.export_error = None

        async def _on_failure(inner: AsyncSession, exc: BaseException) -> None:
            # Fresh reads: the rollback detached everything the failed attempt loaded.
            # Row-by-row rather than one bulk UPDATE, matching ``draft/export.py``'s
            # failure hook — the count is tens of teams on an error path.
            for source_id in source_ids:
                fresh = await self.registration_teams.get(inner, source_id)
                if fresh is not None:
                    fresh.export_status = "failed"
                    fresh.export_error = str(exc)[:500]

        outcome = await team_materialization.run(
            session,
            ExportPlan(
                tournament_id=tournament_id,
                formation_node_id=formation_node_id,
                teams=payload.teams,
                prior_team_ids=payload.prior_team_ids,
                on_unresolved="error",
                guard_standings=True,
                unlink=_unlink,
                finalize=_finalize,
                on_failure=_on_failure,
            ),
        )
        if outcome.imported_teams:
            await emit_balancer_data(session, tournament_id, BALANCER_TEAMS_CHANGED, actor_user_id=actor_user_id)
            await stage_export_invalidation(session, tournament_id)
        return RegisteredExportResult(
            removed_teams=outcome.removed_teams,
            imported_teams=outcome.imported_teams,
            created_players=outcome.materialization.created_players,
            skipped=payload.skipped,
        )


registered_teams_service = RegisteredTeamsService()
