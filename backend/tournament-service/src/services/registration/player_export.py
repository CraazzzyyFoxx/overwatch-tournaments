"""The tournament's balancer pool, exported in one of its two wire formats."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import discipline
from shared.domain.roster import PlayerRoster, flex_role_mode
from shared.repository import TournamentRepository
from shared.services.division_grid.access import get_effective_division_grid
from shared.services.roster import roster_engine
from shared.services.team_format import tournament_slot_shape
from src.services.registration.form_service import form_service

__all__ = (
    "PLAYER_EXPORT_DEFAULT_FORMAT",
    "PLAYER_EXPORT_FORMATS",
    "PlayerExportService",
    "player_export_service",
)

#: ``xv-1`` is the solver's own input contract (``player_data_file`` of
#: ``POST /api/v1/balancer/jobs``) and is frozen; ``owt-1`` is our snapshot,
#: a strict superset of it (see ``RosterEngine.full_export``).
PLAYER_EXPORT_FORMATS: tuple[str, ...] = ("xv-1", "owt-1")
PLAYER_EXPORT_DEFAULT_FORMAT = "xv-1"


class PlayerExportService:
    def __init__(self, *, tournament_repo: TournamentRepository = TournamentRepository()) -> None:
        self.tournament_repo = tournament_repo

    async def export(
        self,
        session: AsyncSession,
        tournament_id: int,
        registration_node_id: int,
        *,
        export_format: str,
        include_private: bool,
    ) -> dict[str, Any]:
        """The pool of a registration node in ``export_format``, one of ``PLAYER_EXPORT_FORMATS``."""
        # One payload, one source: the same rosters the balance job and the
        # draft read, serialized by the engine rather than re-derived here.
        rosters = await roster_engine.for_registration_node(session, registration_node_id, pool_only=True)
        if export_format == "xv-1":
            return roster_engine.balancer_input(rosters.values())
        return await self._owt_export(session, tournament_id, rosters.values(), include_private=include_private)

    async def _owt_export(
        self,
        session: AsyncSession,
        tournament_id: int,
        rosters: Iterable[PlayerRoster],
        *,
        include_private: bool,
    ) -> dict[str, Any]:
        """Assemble the ``owt-1`` document: rosters plus the context to replay them.

        The roster shape is what makes a flex tournament exportable at all -- the
        solver reads the flex slot count from the tournament, never from the file,
        so a payload without it cannot be re-run anywhere else.
        """
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")
        workspace_id = tournament.workspace_id
        shape = await tournament_slot_shape(session, tournament_id)
        # ``flex_role_mode`` reads the schema off the current version, which the
        # form reader eager-loads.
        form = await form_service.get_form(session, tournament_id)
        grid = await get_effective_division_grid(session, workspace_id, tournament_id)
        return roster_engine.full_export(
            rosters,
            shape=shape,
            flex_role_mode=flex_role_mode(form),
            dimension=discipline(tournament.discipline).rated_dimension.code,
            grid=grid,
            include_private=include_private,
            source={
                "tournament_id": tournament_id,
                "tournament_name": tournament.name,
                "workspace_id": workspace_id,
                "scope": "pool",
                "division_grid_version_id": grid.version_id,
            },
        )


player_export_service = PlayerExportService()
