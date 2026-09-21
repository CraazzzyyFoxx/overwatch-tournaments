"""Admin service layer for encounter CRUD operations"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name
from shared.repository import (
    EncounterRepository,
    MapRepository,
    MatchRepository,
    StageItemRepository,
    StageRepository,
    TeamRepository,
    TournamentRepository,
)
from shared.services.bracket.advancement import reset_encounter_result
from shared.services.bracket.swiss_settings import remove_swiss_bye_round
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


def _reject_settled_result_edits(encounter: models.Encounter, update_data: dict) -> None:
    """Completion is not a field edit -- in either direction.

    Into ``COMPLETED``: the result endpoint owns it (``_reject_completed_status``).
    Out of it -- or rewiring a settled encounter's team slots -- the reopen
    endpoint owns it: that one clears ``result_status``/``confirmed_at``/score and
    unwinds whatever the old result advanced downstream. The bare status write
    this used to allow left ``result_status='confirmed'`` beside a non-COMPLETED
    status, which the database refuses outright
    (``ck_encounter_result_status_matches_status``), so the edit died on an
    IntegrityError instead of on a message naming the endpoint that can do it.

    Repeating the encounter's current status is not a transition: the admin form
    posts every field, so renaming a completed encounter must not trip the
    completion guard and push admins into flipping the status by hand.
    """
    new_status = update_data.get("status", encounter.status)
    if new_status != encounter.status:
        _reject_completed_status(new_status.value)
    if encounter.status != enums.EncounterStatus.COMPLETED:
        return
    teams_changed = any(
        field in update_data and update_data[field] != getattr(encounter, field)
        for field in ("home_team_id", "away_team_id")
    )
    if new_status == encounter.status and not teams_changed:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "use_reopen_endpoint: reopen the result via POST "
            "/api/v1/admin/encounters/{encounter_id}/result/reopen before changing a completed "
            "encounter's status or teams"
        ),
    )


def _reject_swapping_a_busy_encounter(encounter: models.Encounter) -> None:
    """A slot swap rewires team slots -- the edit ``_reject_settled_result_edits``
    already sends to the reopen endpoint, and the one a running series must not
    see under it.

    ``result_status`` alone is enough to refuse: a disputed or
    pending-confirmation encounter is not ``COMPLETED`` yet its reports are
    already keyed by the current team pair, so swapping a slot would orphan
    them.
    """
    if encounter.status == enums.EncounterStatus.COMPLETED or (
        encounter.result_status != enums.EncounterResultStatus.NONE
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "use_reopen_endpoint: reopen the result via POST "
                "/api/v1/admin/encounters/{encounter_id}/result/reopen before swapping a settled "
                "encounter's team slots"
            ),
        )
    if encounter.started_at is not None and encounter.ended_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="encounter_in_progress: the encounter is live; end it before swapping its team slots",
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

        # Status first: the completion guards must fire before any other
        # validation or write this method does.
        if "status" in update_data:
            try:
                update_data["status"] = enums.EncounterStatus(update_data["status"].lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status. Must be one of: {', '.join([s.value for s in enums.EncounterStatus])}",
                )
        _reject_settled_result_edits(encounter, update_data)
        # A score/status/team write on this encounter is a result correction, so
        # it may only land while the qualifications it already fed are still
        # untouched; a pure rename or reschedule is not a correction.
        if any(
            field in update_data for field in ("home_score", "away_score", "status", "home_team_id", "away_team_id")
        ):
            await self._assert_source_correction_allowed(session, encounter)

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

    @staticmethod
    async def _assert_source_correction_allowed(session: AsyncSession, encounter: models.Encounter) -> None:
        """409 unless the downstream qualifications this result fed can still be
        re-resolved. Imported lazily -- ``admin.stage`` pulls in the whole
        bracket generation stack, which imports this module's siblings.
        """
        from src.services.admin.stage import stage_service as admin_stage_service

        await admin_stage_service.assert_source_correction_allowed(session, encounter)

    async def _team_name(self, session: AsyncSession, team_id: int | None) -> str | None:
        """``None`` for an empty slot -- ``build_encounter_name`` renders it as TBD."""
        if not team_id:
            return None
        team = await self.team_repo.get(session, team_id)
        return team.name if team else None

    async def swap_slots(
        self, session: AsyncSession, encounter_id: int, data: schemas.EncounterSwapSlotInput
    ) -> tuple[models.Encounter, models.Encounter]:
        """Exchange the team ids two bracket slots hold, in one transaction.

        The bracket's drag-and-drop: either slot may be empty (that is how a team
        is moved into a TBD slot), and naming the same encounter with the other
        slot flips home/away. Seeding only -- a settled or running encounter is
        refused rather than silently re-teamed under its result.

        Both an initial seed and a derived slot may be swapped, so the origin
        travels with the team: the ``EncounterLink`` feeding a derived slot is
        re-pointed at the slot its team moved into. Otherwise the next
        advancement would overwrite the manual move, and -- since the Grand
        Final and its reset are identified by those links -- a home/away flip
        would hide the Grand Final from the reset rule.
        """
        if data.target_encounter_id == encounter_id and data.target_slot == data.slot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot swap a slot with itself",
            )

        # Ascending id order: two admins dragging the same pair in opposite
        # directions would otherwise take the two row locks in opposite orders
        # and deadlock.
        locked: dict[int, models.Encounter] = {}
        for locked_id in sorted({encounter_id, data.target_encounter_id}):
            row = await self.encounter_repo.get_for_update(
                session,
                locked_id,
                options=[
                    selectinload(models.Encounter.home_team),
                    selectinload(models.Encounter.away_team),
                ],
            )
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
            locked[locked_id] = row

        source = locked[encounter_id]
        target = locked[data.target_encounter_id]

        if target.tournament_id != source.tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target encounter does not belong to this tournament",
            )
        if target.stage_id != source.stage_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target encounter does not belong to the same stage",
            )

        touched = [source] if source is target else [source, target]
        for encounter in touched:
            _reject_swapping_a_busy_encounter(encounter)

        previous = {encounter.id: (encounter.home_team_id, encounter.away_team_id) for encounter in touched}
        source_field = f"{data.slot}_team_id"
        target_field = f"{data.target_slot}_team_id"
        # Both reads before either write -- on a home/away flip the two slots
        # live on the same row. ``or None`` so a 0 left by an older writer and a
        # NULL both land as the empty slot the column actually stores.
        source_team_id = getattr(source, source_field) or None
        target_team_id = getattr(target, target_field) or None
        setattr(source, source_field, target_team_id)
        setattr(target, target_field, source_team_id)

        for encounter in touched:
            if encounter.home_team_id is not None and encounter.home_team_id == encounter.away_team_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A team cannot occupy both slots of one encounter",
                )

        await self._move_slot_links(session, source, target, data)

        for encounter in touched:
            if (encounter.home_team_id, encounter.away_team_id) == previous[encounter.id]:
                continue
            encounter.name = build_encounter_name(
                await self._team_name(session, encounter.home_team_id),
                await self._team_name(session, encounter.away_team_id),
            )
            await pick_ban_session_service.sync_all_pick_ban_sessions_after_team_change(session, encounter)

        await enqueue_tournament_recalculation(session, source.tournament_id)
        await session.commit()

        return source, target

    @staticmethod
    async def _move_slot_links(
        session: AsyncSession,
        source: models.Encounter,
        target: models.Encounter,
        data: schemas.EncounterSwapSlotInput,
    ) -> None:
        """Re-point the advancement edges that fed the two swapped slots.

        A derived slot is owned by the ``EncounterLink`` targeting it; moving
        only the team would leave the next advancement writing the old team
        back into it. One query for both sides, both reads before either write
        -- on a home/away flip the two links sit on the same encounter.
        """
        rows = await session.execute(
            select(models.EncounterLink).where(models.EncounterLink.target_encounter_id.in_({source.id, target.id}))
        )
        links = list(rows.scalars().all())
        source_slot = enums.EncounterLinkSlot(data.slot)
        target_slot = enums.EncounterLinkSlot(data.target_slot)

        def _link_for(encounter_id: int, slot: enums.EncounterLinkSlot) -> models.EncounterLink | None:
            return next(
                (link for link in links if link.target_encounter_id == encounter_id and link.target_slot == slot),
                None,
            )

        source_link = _link_for(source.id, source_slot)
        target_link = _link_for(target.id, target_slot)
        if source_link is not None:
            source_link.target_encounter_id = target.id
            source_link.target_slot = target_slot
        if target_link is not None:
            target_link.target_encounter_id = source.id
            target_link.target_slot = source_slot

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
        """Delete encounter (cascade deletes matches).

        The FK cascade removes this encounter's ``EncounterLink`` rows, but the
        teams and results it already advanced into later matches would outlive
        it as an orphaned bracket -- so the result is voided through the same
        cascade an admin correction uses before the row goes.
        """
        encounter = await self.encounter_repo.get(session, encounter_id)

        if not encounter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        tournament_id = encounter.tournament_id
        stage = await session.get(models.Stage, encounter.stage_id) if encounter.stage_id else None
        # A Swiss bye is bookkeeping for a round that existed; when the round's
        # last encounter goes, so does the bye recorded for it.
        drop_bye_round = (
            stage is not None
            and stage.stage_type == enums.StageType.SWISS
            and not await self._round_has_other_encounters(session, encounter)
        )
        await self._assert_source_correction_allowed(session, encounter)
        # ``reset_encounter_result`` mutates ORM state and leaves flushing to its
        # caller, and ``session.delete`` does not flush either: the enqueue below
        # is still the first write of this transaction (same ordering contract as
        # create).
        await reset_encounter_result(session, encounter)
        await session.delete(encounter)
        if drop_bye_round:
            remove_swiss_bye_round(stage, encounter.stage_item_id, encounter.round)
        await enqueue_tournament_recalculation(session, tournament_id)
        await session.commit()

    @staticmethod
    async def _round_has_other_encounters(session: AsyncSession, encounter: models.Encounter) -> bool:
        """Any sibling left in this encounter's ``(stage, item, round)``."""
        rows = await session.execute(
            select(models.Encounter.id)
            .where(
                models.Encounter.stage_id == encounter.stage_id,
                models.Encounter.stage_item_id == encounter.stage_item_id,
                models.Encounter.round == encounter.round,
                models.Encounter.id != encounter.id,
            )
            .limit(1)
        )
        return rows.first() is not None


encounter_service = AdminEncounterService()
