"""Admin service layer for encounter CRUD operations"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    EncounterRepository,
    MapRepository,
    MatchRepository,
    StageItemRepository,
    StageRepository,
    TeamRepository,
    TournamentRepository,
)
from src import models, schemas
from src.core import enums
from src.services.encounter.pick_ban_session import pick_ban_session_service
from src.services.tournament.events import enqueue_tournament_recalculation

# ``enqueue_tournament_recalculation`` emits ``tournament.encounters``, and the
# realtime rail drops this service's cached encounter reads from that emit's
# after-commit hook, before the event reaches any client. The explicit
# post-commit purge these writes used to do was the same drop, minus that
# ordering guarantee.


def _reject_completed_status(new_status: str | None) -> None:
    """Completion is not a field edit.

    ``COMPLETED`` is now reachable only through the result endpoint, which moves
    ``status``, ``result_status``, the score and the audit row together. Letting
    a plain field update land it here is what allowed ``completed`` +
    ``disputed`` — a state no endpoint could repair.
    """
    if new_status is not None and new_status.lower() == enums.EncounterStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "use_result_endpoint: complete an encounter via POST /api/v1/admin/encounters/{encounter_id}/result"
            ),
        )


class AdminEncounterService:
    def __init__(
        self,
        *,
        encounter_repo: EncounterRepository = EncounterRepository(),
        match_repo: MatchRepository = MatchRepository(),
        map_repo: MapRepository = MapRepository(),
        stage_repo: StageRepository = StageRepository(),
        stage_item_repo: StageItemRepository = StageItemRepository(),
        team_repo: TeamRepository = TeamRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
    ) -> None:
        self.encounter_repo = encounter_repo
        self.match_repo = match_repo
        self.map_repo = map_repo
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.team_repo = team_repo
        self.tournament_repo = tournament_repo

    async def _resolve_stage_refs(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        stage_id: int | None,
        stage_item_id: int | None,
    ) -> tuple[int, int | None]:
        if stage_id is None and stage_item_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Encounter must be linked to a stage",
            )

        if stage_item_id is not None:
            resolved_stage_item = await self.stage_item_repo.get(
                session, stage_item_id, options=[selectinload(models.StageItem.stage)]
            )
            if not resolved_stage_item:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Stage item not found",
                )
            if resolved_stage_item.stage.tournament_id != tournament_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Stage item does not belong to this tournament",
                )
            if stage_id is None:
                stage_id = resolved_stage_item.stage_id
            elif stage_id != resolved_stage_item.stage_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Stage item does not belong to the selected stage",
                )

        resolved_stage = await self.stage_repo.get_by(session, id=stage_id, tournament_id=tournament_id)
        if not resolved_stage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")

        return stage_id, stage_item_id

    async def _require_team_in_tournament(
        self, session: AsyncSession, *, team_id: int, tournament_id: int, label: str
    ) -> models.Team:
        """Resolve a team and enforce that it belongs to the given tournament.

        Tenant-isolation guard: encounter/match writes are authorized against the
        encounter's own tournament workspace, so any team reference in the payload
        must live in that same tournament (mirrors the stage-refs validation).
        """
        team = await self.team_repo.get(session, team_id)
        if not team:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found")
        if team.tournament_id != tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label} does not belong to this tournament",
            )
        return team

    async def create_encounter(self, session: AsyncSession, data: schemas.EncounterCreate) -> models.Encounter:
        """Create a new encounter"""
        _reject_completed_status(data.status)

        # Verify tournament exists
        tournament = await self.tournament_repo.get(session, data.tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        # Verify selected teams exist and belong to this tournament when provided
        if data.home_team_id is not None:
            await self._require_team_in_tournament(
                session, team_id=data.home_team_id, tournament_id=data.tournament_id, label="Home team"
            )

        if data.away_team_id is not None:
            await self._require_team_in_tournament(
                session, team_id=data.away_team_id, tournament_id=data.tournament_id, label="Away team"
            )

        stage_id, stage_item_id = await self._resolve_stage_refs(
            session,
            tournament_id=data.tournament_id,
            stage_id=data.stage_id,
            stage_item_id=data.stage_item_id,
        )

        # Parse status
        try:
            encounter_status = enums.EncounterStatus(data.status)
        except ValueError:
            encounter_status = enums.EncounterStatus.OPEN

        # Create encounter
        encounter = models.Encounter(
            name=data.name,
            tournament_id=data.tournament_id,
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            home_team_id=data.home_team_id,
            away_team_id=data.away_team_id,
            round=data.round,
            best_of=data.best_of,
            home_score=data.home_score,
            away_score=data.away_score,
            status=encounter_status,
            scheduled_at=data.scheduled_at,
            started_at=data.started_at,
            ended_at=data.ended_at,
            current_map_index=data.current_map_index,
        )

        # Not ``repo.create``: that flushes, and the enqueue below must stay the
        # first write of this transaction (see the outbox-ordering regression test).
        session.add(encounter)
        await enqueue_tournament_recalculation(session, data.tournament_id)
        await session.commit()
        await session.refresh(encounter)

        return encounter

    async def update_encounter(
        self, session: AsyncSession, encounter_id: int, data: schemas.EncounterUpdate
    ) -> models.Encounter:
        """Update encounter fields"""
        _reject_completed_status(data.status)

        encounter = await self.encounter_repo.get_for_update(
            session,
            encounter_id,
            options=[
                selectinload(models.Encounter.home_team),
                selectinload(models.Encounter.away_team),
                selectinload(models.Encounter.stage),
                selectinload(models.Encounter.stage_item),
            ],
        )

        if not encounter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        # Update fields
        update_data = data.model_dump(exclude_unset=True)

        if "home_team_id" in update_data and update_data["home_team_id"] is not None:
            await self._require_team_in_tournament(
                session,
                team_id=update_data["home_team_id"],
                tournament_id=encounter.tournament_id,
                label="Home team",
            )

        if "away_team_id" in update_data and update_data["away_team_id"] is not None:
            await self._require_team_in_tournament(
                session,
                team_id=update_data["away_team_id"],
                tournament_id=encounter.tournament_id,
                label="Away team",
            )

        resolved_stage_id, resolved_stage_item_id = await self._resolve_stage_refs(
            session,
            tournament_id=encounter.tournament_id,
            stage_id=update_data.get("stage_id", encounter.stage_id),
            stage_item_id=update_data.get("stage_item_id", encounter.stage_item_id),
        )
        update_data["stage_id"] = resolved_stage_id
        update_data["stage_item_id"] = resolved_stage_item_id

        # Handle status conversion
        if "status" in update_data:
            try:
                update_data["status"] = enums.EncounterStatus(update_data["status"].lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status. Must be one of: {', '.join([s.value for s in enums.EncounterStatus])}",
                )

        tournament_id = encounter.tournament_id
        previous_teams = (encounter.home_team_id, encounter.away_team_id)
        for field, value in update_data.items():
            setattr(encounter, field, value)

        if (encounter.home_team_id, encounter.away_team_id) != previous_teams:
            # Admin re-assigned a team slot: sync map/hero pick-ban sessions
            # (ensure when both teams are now known, reset a stale existing one).
            await pick_ban_session_service.sync_all_pick_ban_sessions_after_team_change(session, encounter)

        await enqueue_tournament_recalculation(session, tournament_id)
        await session.commit()
        await session.refresh(encounter)

        return encounter

    async def update_match(
        self,
        session: AsyncSession,
        match_id: int,
        data: schemas.MatchUpdate,
    ) -> models.Match:
        """Update a single Match (map) belonging to an encounter."""
        match = await self.match_repo.get(session, match_id, options=[selectinload(models.Match.encounter)])
        if not match:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")

        update_data = data.model_dump(exclude_unset=True)

        match_tournament_id = match.encounter.tournament_id if match.encounter else None

        if "home_team_id" in update_data:
            if update_data["home_team_id"] is None or match_tournament_id is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Home team not found")
            await self._require_team_in_tournament(
                session,
                team_id=update_data["home_team_id"],
                tournament_id=match_tournament_id,
                label="Home team",
            )
        if "away_team_id" in update_data:
            if update_data["away_team_id"] is None or match_tournament_id is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Away team not found")
            await self._require_team_in_tournament(
                session,
                team_id=update_data["away_team_id"],
                tournament_id=match_tournament_id,
                label="Away team",
            )
        if "map_id" in update_data and update_data["map_id"] is not None:
            if await self.map_repo.get(session, update_data["map_id"]) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Map not found")

        for field, value in update_data.items():
            setattr(match, field, value)

        tournament_id = match.encounter.tournament_id if match.encounter else None

        if tournament_id is not None:
            await enqueue_tournament_recalculation(session, tournament_id)
        await session.commit()
        await session.refresh(match)

        return match

    async def delete_encounter(self, session: AsyncSession, encounter_id: int) -> None:
        """Delete encounter (cascade deletes matches)"""
        encounter = await self.encounter_repo.get(session, encounter_id)

        if not encounter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        tournament_id = encounter.tournament_id
        # Not ``repo.delete``: that flushes, and the enqueue below must stay the
        # first write of this transaction (same ordering contract as create).
        await session.delete(encounter)
        await enqueue_tournament_recalculation(session, tournament_id)
        await session.commit()


encounter_service = AdminEncounterService()
