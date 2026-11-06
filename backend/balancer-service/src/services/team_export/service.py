"""One orchestrator for every path that materializes tournament teams.

Every caller needs the same destructive, order-sensitive sequence:

    guard -> cleanup prior export -> insert teams+players -> backfill links
          -> stamp the source row (+ maybe emit an event) -> ONE commit

Each caller supplies only what differs: the team list, the prior-export ids to
clean, and callbacks to unlink/stamp its own row.

Transaction ownership
---------------------
This service commits; nothing below it does. The prior export's
``Standing``/``Player``/``Team`` rows are deleted without an intervening commit,
so failure is explicitly **two transactions**: roll back the data work first (the
deletes and partial inserts vanish), then stamp the failure in a fresh, short
transaction. Stamping without the rollback would flush the pending DELETEs and
leave the tournament with its old teams gone and no replacements; rolling back
alone would lose the operator diagnostics.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import ApiExc, ApiHTTPException
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Player, Team
from src.services.team_export.materialization import (
    MaterializationResult,
    MaterializationTeam,
    OnUnresolved,
    materialize_teams,
)

__all__ = ("ExportOutcome", "ExportPlan", "TeamMaterializationService", "team_materialization")

logger = logging.getLogger(__name__)

#: Called after the prior export's rows are deleted, to clear the source rows'
#: ``exported_team_id`` back-links. Synchronous: it only mutates loaded ORM objects.
UnlinkHook = Callable[[], None]
#: Called with the materialized teams keyed by ``balancer_name`` — writes the
#: back-links and stamps the source row, and may enqueue that path's event.
FinalizeHook = Callable[[AsyncSession, Mapping[str, Team]], Awaitable[None]]
#: Called after rollback, in a fresh transaction, to record the failure.
FailureHook = Callable[[AsyncSession, BaseException], Awaitable[None]]


@dataclass
class ExportPlan:
    """What one materialization path contributes to the shared sequence."""

    tournament_id: int
    #: The formation node the teams belong to: the cleanup, the guard and the team reuse touch only its rows.
    formation_node_id: int
    teams: Sequence[MaterializationTeam]
    prior_team_ids: Sequence[int] = ()
    on_unresolved: OnUnresolved = "skip"
    #: Refuse to run when standings exist for teams this export does not own.
    #: Off for the balancer/draft paths, which re-export destructively; on for
    #: registered teams, where re-export after a bracket exists would silently
    #: invalidate it.
    guard_standings: bool = False
    unlink: UnlinkHook | None = None
    finalize: FinalizeHook | None = None
    on_failure: FailureHook | None = None


def _owned(formation_node_id: int) -> sa.ColumnElement[bool]:
    """Teams this node's export may replace or must guard: its own and the legacy ones that predate formation nodes."""
    return sa.or_(Team.formation_node_id == formation_node_id, Team.formation_node_id.is_(None))


@dataclass
class ExportOutcome:
    removed_teams: int = 0
    imported_teams: int = 0
    materialization: MaterializationResult = field(default_factory=MaterializationResult)


class TeamMaterializationService:
    """Runs an :class:`ExportPlan`. Owns the transaction boundary."""

    async def run(self, session: AsyncSession, plan: ExportPlan) -> ExportOutcome:
        try:
            outcome = await self._run(session, plan)
            await session.commit()
            return outcome
        except BaseException as exc:
            # Discard the destructive work: without this rollback the pending
            # DELETEs would be committed by the failure stamp below.
            await session.rollback()
            if plan.on_failure is not None:
                try:
                    await plan.on_failure(session, exc)
                    await session.commit()
                except Exception:  # pragma: no cover - diagnostics must not mask the cause
                    logger.exception("team export failure hook failed for tournament %s", plan.tournament_id)
                    await session.rollback()
            raise

    async def _run(self, session: AsyncSession, plan: ExportPlan) -> ExportOutcome:
        prior_ids = list(plan.prior_team_ids)

        if plan.guard_standings:
            await self._assert_no_foreign_standings(session, plan.formation_node_id, prior_ids)

        if prior_ids:
            # A link may point into another formation's export: only this node's teams go, plus the legacy
            # (NULL-formation) teams the source rows link to -- the export adopts them (spec R2.Q5).
            own_ids = sa.select(Team.id).where(Team.id.in_(prior_ids), _owned(plan.formation_node_id))
            await session.execute(sa.delete(Standing).where(Standing.team_id.in_(own_ids)))
            await session.execute(sa.delete(Player).where(Player.team_id.in_(own_ids)))
            await session.execute(sa.delete(Team).where(Team.id.in_(own_ids)))
            if plan.unlink is not None:
                plan.unlink()
            await session.flush()

        materialization = await materialize_teams(
            session,
            plan.tournament_id,
            plan.formation_node_id,
            plan.teams,
            on_unresolved=plan.on_unresolved,
        )

        # Re-queried rather than taken from ``materialization.created_teams``: a
        # team reused by name keeps whatever ``balancer_name`` it already had, and
        # callers link back only what this query matches.
        by_name: Mapping[str, Team] = {}
        names = [team.balancer_name for team in plan.teams]
        if names:
            rows = (
                await session.scalars(
                    sa.select(Team).where(
                        Team.formation_node_id == plan.formation_node_id,
                        Team.balancer_name.in_(names),
                    )
                )
            ).all()
            by_name = {team.balancer_name: team for team in rows}

        if plan.finalize is not None:
            await plan.finalize(session, by_name)

        return ExportOutcome(
            removed_teams=len(prior_ids),
            imported_teams=len(plan.teams),
            materialization=materialization,
        )

    @staticmethod
    async def _assert_no_foreign_standings(
        session: AsyncSession,
        formation_node_id: int,
        prior_team_ids: Sequence[int],
    ) -> None:
        """Refuse when standings exist for teams of this node that this export will not replace. The legacy
        (NULL-formation) teams the export adopts are in ``prior_team_ids`` and are replaced; any other NULL team is
        not this export's business.

        Re-export is destructive-then-idempotent, not diffed, so a bracket built
        on teams outside ``prior_team_ids`` would be silently invalidated.
        """
        query = (
            sa.select(sa.literal(1))
            .select_from(Standing)
            .join(Team, Team.id == Standing.team_id)
            .where(Team.formation_node_id == formation_node_id)
            .limit(1)
        )
        if prior_team_ids:
            query = query.where(Standing.team_id.notin_(list(prior_team_ids)))
        if await session.scalar(query) is not None:
            raise ApiHTTPException(
                status_code=409,
                detail=[
                    ApiExc(
                        code="standings_exist",
                        msg=(
                            "Standings already exist for this formation's teams; re-exporting them "
                            "would invalidate them. Remove the standings first."
                        ),
                    )
                ],
            )


#: Module-level singleton — the service is stateless.
team_materialization = TeamMaterializationService()
