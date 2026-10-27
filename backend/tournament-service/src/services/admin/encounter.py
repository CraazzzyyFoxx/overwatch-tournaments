"""Admin service layer for encounter CRUD operations"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name
from shared.repository import (
    CatalogEntityRepository,
    EncounterRepository,
    StageItemRepository,
    StageRepository,
    StatsMatchRepository,
    TeamRepository,
)
from shared.repository.stats_reads import MatchReadContext, get_match_reads
from shared.services.encounter.participants import MemberSnapshot, active_teams, place_team, vacate_slot
from shared.services.realtime import Resource, Scope, emit
from shared.services.stats_evidence import capture_stats_evidence, owner_scopes, stage_stats_evidence
from shared.services.stats_owner_delete import capture_owner_delete, stage_owner_delete
from src import schemas
from src.services.bracket.advancement import reset_downstream
from src.services.bracket.swiss_state import remove_swiss_bye_round
from src.services.notifications.lifecycle import after_encounter_teams_changed, lifecycle_notifier
from src.services.tournament.events import enqueue_tournament_recalculation

# ``enqueue_tournament_recalculation`` emits ``tournament.encounters`` (and an
# edit that cannot move standings emits it alone), and the realtime rail drops
# this service's cached encounter reads from that emit's after-commit hook,
# before the event reaches any client -- so these writes do no cache purge of
# their own.

# What an admin may still edit on a lobby: it has no sides, no series score and
# no bracket slot, so every other column of the duel-shaped row is meaningless.
_FFA_EDITABLE_FIELDS = frozenset({"name", "scheduled_at", "started_at", "ended_at"})


def _reject_completed_status(new_status: str | None) -> None:
    """Completion is not a field edit.

    ``COMPLETED`` is reachable only through the result endpoint, which moves
    ``status``, ``result_status``, the score and the audit row together. A plain
    field update landing it could leave ``completed`` + ``disputed`` — a state no
    endpoint can repair.
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
    Out of it, the reopen endpoint owns it: that one clears
    ``result_status``/``confirmed_at``/``result_source`` and unwinds whatever the
    old result advanced downstream. A bare status write would leave
    ``result_status='confirmed'`` beside a non-COMPLETED status, which the
    database refuses (``ck_encounter_confirmed_completed``) with an
    IntegrityError instead of a message naming the endpoint that can do it. The
    standing and the seats are not in this payload: they live on the
    participations, which only the result writer and the slot swap touch.

    Repeating the encounter's current status is not a transition: the admin form
    posts every field, so renaming a completed encounter must not trip the
    completion guard and push admins into flipping the status by hand.
    """
    new_status = update_data.get("status", encounter.status)
    if new_status != encounter.status:
        _reject_completed_status(new_status.value)
    if encounter.status != enums.EncounterStatus.COMPLETED or new_status == encounter.status:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "use_reopen_endpoint: reopen the result via POST "
            "/api/v1/admin/encounters/{encounter_id}/result/reopen before changing a completed "
            "encounter's status"
        ),
    )


async def _roster_snapshot(session: AsyncSession, participation: models.EncounterTeam) -> list[MemberSnapshot]:
    """Re-read one participation's roster as the snapshots ``place_team`` takes.

    A seat that changes slot is a NEW participation, so the line-up it already
    recorded has to be copied onto it; reading the rows back is the only way to
    do that without a second author of the snapshot shape.
    """
    members = await session.execute(
        select(models.EncounterTeamMember).where(
            models.EncounterTeamMember.encounter_team_id == participation.id,
        )
    )
    rows = list(members.scalars().all())
    if not rows:
        return []
    role_rows = await session.execute(
        select(models.EncounterTeamMemberRole)
        .where(models.EncounterTeamMemberRole.team_member_id.in_([row.id for row in rows]))
        .order_by(models.EncounterTeamMemberRole.role_id)
    )
    roles: dict[int, list[tuple[str, str]]] = {}
    for role in role_rows.scalars().all():
        roles.setdefault(role.team_member_id, []).append((role.dimension, role.role))
    return [
        MemberSnapshot(
            workspace_member_id=row.workspace_member_id,
            display_name=row.display_name_snapshot,
            rank=row.rank,
            is_substitute=row.is_substitute,
            roles=tuple(roles.get(row.id, ())),
            is_captain=row.is_captain,
        )
        for row in rows
    ]


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
        match_repo: StatsMatchRepository = StatsMatchRepository(),
        map_repo: CatalogEntityRepository = CatalogEntityRepository("map"),
        stage_repo: StageRepository = StageRepository(),
        stage_item_repo: StageItemRepository = StageItemRepository(),
        team_repo: TeamRepository = TeamRepository(),
    ) -> None:
        self.encounter_repo = encounter_repo
        self.match_repo = match_repo
        self.map_repo = map_repo
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.team_repo = team_repo

    async def get_encounter(
        self, session: AsyncSession, encounter_id: int, *, for_update: bool = False
    ) -> models.Encounter | None:
        """The bare encounter row, ``None`` when missing. ``for_update`` takes its row lock."""
        if for_update:
            return await self.encounter_repo.get_for_update(session, encounter_id)
        return await self.encounter_repo.get(session, encounter_id)

    async def get_match_encounter_id(self, session: AsyncSession, match_id: int) -> int | None:
        return await self.match_repo.get_encounter_id(session, match_id)

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
        """Create a new encounter and seat the teams the payload names."""
        _reject_completed_status(data.status)

        # Two columns, not ``tournament_repo.get``: a tournament row loads its
        # grid version and phase schedule eagerly (four statements).
        tournament = (
            await session.execute(
                select(models.Tournament.workspace_id, models.Tournament.discipline).where(
                    models.Tournament.id == data.tournament_id
                )
            )
        ).first()

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        seats = {seat.slot: seat for seat in data.teams}
        if len(seats) != len(data.teams):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Two seats name the same slot",
            )
        for seat in data.teams:
            if seat.slot > data.slot_count:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Slot {seat.slot} is outside this encounter's seats (1..{data.slot_count})",
                )
            if seat.team_id is not None:
                await self._require_team_in_tournament(
                    session,
                    team_id=seat.team_id,
                    tournament_id=data.tournament_id,
                    label=f"Slot {seat.slot} team",
                )

        stage_id, stage_item_id = await self._resolve_stage_refs(
            session,
            tournament_id=data.tournament_id,
            stage_id=data.stage_id,
            stage_item_id=data.stage_item_id,
        )
        stage = await self.stage_repo.get(session, stage_id)

        try:
            encounter_status = enums.EncounterStatus(data.status)
        except ValueError:
            encounter_status = enums.EncounterStatus.OPEN

        # The workspace, the discipline and the scoring rule are copies of the
        # owner's: an encounter is played under the rule of the stage it sits in.
        encounter = models.Encounter(
            workspace_id=tournament.workspace_id,
            discipline=tournament.discipline,
            tournament_id=data.tournament_id,
            scoring_rule_id=stage.scoring_rule_id,
            name=data.name,
            slot_count=data.slot_count,
            best_of=data.best_of,
            status=encounter_status,
            scheduled_at=data.scheduled_at,
            started_at=data.started_at,
            ended_at=data.ended_at,
            current_game_position=data.current_map_index,
        )

        # Not ``repo.create``: that flushes, and the enqueue below must stay the
        # first write of this transaction (outbox ordering).
        session.add(encounter)
        await enqueue_tournament_recalculation(session, data.tournament_id)
        # After the enqueue, whose flush is what gives the row its id.
        session.add(
            models.BracketEncounter(
                encounter_id=encounter.id,
                tournament_id=data.tournament_id,
                stage_id=stage_id,
                stage_item_id=stage_item_id,
                round=data.round,
            )
        )
        # ``None`` seats nobody: a TBD slot is a slot with no active participation.
        for seat in sorted((row for row in data.teams if row.team_id is not None), key=lambda row: row.slot):
            await place_team(
                session,
                encounter,
                slot=seat.slot,
                team_id=seat.team_id,
                name=await self._team_name(session, seat.team_id) or "TBD",
                seed=None,
                members=(),
            )
        # The notifier applies its own guards -- a slot-less or already-played
        # row tells nobody; a time is not required.
        await lifecycle_notifier.on_encounter_changed(session, encounter)
        await session.commit()
        await session.refresh(encounter)

        return encounter

    async def update_encounter(
        self, session: AsyncSession, encounter_id: int, data: schemas.EncounterUpdate
    ) -> models.Encounter:
        """Update encounter fields.

        The bracket coordinate (``stage``/``stage_item``/``round``) lives on
        ``tournament.bracket_encounter`` and is written there; the seats are not
        in this payload at all (the slot swap owns them).
        """
        encounter = await self.encounter_repo.get_for_update(session, encounter_id)

        if not encounter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        update_data = data.model_dump(exclude_unset=True)
        if encounter.scoring_preset == "points":
            refused = sorted(set(update_data) - _FFA_EDITABLE_FIELDS)
            if refused:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=[ApiExc(code="ffa_field_not_editable", msg=f"A lobby does not take {', '.join(refused)}")],
                )

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
        # A status write on this encounter is a result correction, so it may only
        # land while the qualifications it already fed are still untouched; a
        # pure rename or reschedule is not a correction.
        if "status" in update_data:
            await self._assert_source_correction_allowed(session, encounter)

        position = await session.get(models.BracketEncounter, encounter.id)
        old_coordinate = (position.stage_id, position.stage_item_id, position.round) if position else None
        resolved_stage_id, resolved_stage_item_id = await self._resolve_stage_refs(
            session,
            tournament_id=encounter.tournament_id,
            stage_id=update_data.pop("stage_id", position.stage_id if position else None),
            stage_item_id=update_data.pop("stage_item_id", position.stage_item_id if position else None),
        )
        new_round = update_data.pop("round", position.round if position else 0)
        if position is None:
            session.add(
                models.BracketEncounter(
                    encounter_id=encounter.id,
                    tournament_id=encounter.tournament_id,
                    stage_id=resolved_stage_id,
                    stage_item_id=resolved_stage_item_id,
                    round=new_round,
                )
            )
        else:
            position.stage_id = resolved_stage_id
            position.stage_item_id = resolved_stage_item_id
            position.round = new_round
        # ``current_map_index`` is the wire's name for the live position.
        if "current_map_index" in update_data:
            update_data["current_game_position"] = update_data.pop("current_map_index")

        # Only what standings are computed from asks for a recompute: the status,
        # the bracket coordinate and the series length. A rename, a reschedule or
        # a live-position step does not (the payload carries no scores -- the
        # result endpoint owns them).
        affects_standings = old_coordinate != (resolved_stage_id, resolved_stage_item_id, new_round) or any(
            field in update_data and update_data[field] != getattr(encounter, field) for field in ("status", "best_of")
        )

        tournament_id = encounter.tournament_id
        # Read only when the payload carries the field: an edit that never
        # mentions ``scheduled_at`` cannot have changed it.
        previous_scheduled_at = encounter.scheduled_at if "scheduled_at" in update_data else None
        for field, value in update_data.items():
            setattr(encounter, field, value)

        if "scheduled_at" in update_data and encounter.scheduled_at != previous_scheduled_at:
            await lifecycle_notifier.on_encounter_changed(session, encounter)

        if affects_standings:
            await enqueue_tournament_recalculation(session, tournament_id)
        else:
            await emit(session, scope=Scope.tournament(tournament_id), invalidates=[Resource.TOURNAMENT_ENCOUNTERS])
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
        """Exchange the teams two bracket seats hold, in one transaction.

        The bracket's drag-and-drop: either seat may be empty (that is how a team
        is moved into a TBD slot), and naming the same encounter with another
        slot exchanges two of its own seats. Seeding only -- a settled or running
        encounter is refused rather than silently re-teamed under its result.

        A seat does not change hands in place: the occupant is retired and a new
        participation written, so the games the old one played stay
        attached to the row that played them.

        Both an initial seed and a derived seat may be swapped, so the origin
        travels with the team: the ``EncounterLink`` feeding a derived seat is
        re-pointed at the seat its team moved into. Otherwise the next
        advancement would overwrite the manual move, and -- since the Grand
        Final and its reset are identified by those links -- an internal swap
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
            row = await self.encounter_repo.get_for_update(session, locked_id)
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
        source_position = await session.get(models.BracketEncounter, source.id)
        target_position = await session.get(models.BracketEncounter, target.id)
        source_stage = source_position.stage_id if source_position is not None else None
        target_stage = target_position.stage_id if target_position is not None else None
        if target_stage != source_stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target encounter does not belong to the same stage",
            )

        touched = [source] if source is target else [source, target]
        for encounter in touched:
            _reject_swapping_a_busy_encounter(encounter)
        for encounter, slot in ((source, data.slot), (target, data.target_slot)):
            if slot > encounter.slot_count:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Slot {slot} is outside encounter {encounter.id}'s seats (1..{encounter.slot_count})",
                )

        # Both reads before either write -- on an internal swap the two seats
        # live on the same encounter.
        source_seats = {seat.slot: seat for seat in await active_teams(session, source.id)}
        target_seats = (
            source_seats if target is source else {seat.slot: seat for seat in await active_teams(session, target.id)}
        )
        moving_out = source_seats.get(data.slot)
        moving_in = target_seats.get(data.target_slot)
        if moving_out is None and moving_in is None:
            return source, target
        # The rosters travel with their teams, so they are read while the old
        # participations are still live.
        rosters = {
            seat.id: await _roster_snapshot(session, seat) for seat in (moving_out, moving_in) if seat is not None
        }

        for encounter, slot in ((source, data.slot), (target, data.target_slot)):
            await vacate_slot(session, encounter, slot=slot)
        for encounter, slot, seat in (
            (source, data.slot, moving_in),
            (target, data.target_slot, moving_out),
        ):
            if seat is None:
                continue
            await place_team(
                session,
                encounter,
                slot=slot,
                team_id=seat.team_id,
                name=seat.name,
                seed=seat.seed,
                members=rosters[seat.id],
            )

        for encounter in touched:
            seats = await active_teams(session, encounter.id)
            team_ids = [seat.team_id for seat in seats if seat.team_id is not None]
            if len(set(team_ids)) != len(team_ids):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A team cannot occupy two seats of one encounter",
                )

        await self._move_slot_links(session, source, target, data)

        for encounter in touched:
            # Slot-indexed, so a seat left empty reads TBD in ITS place.
            seated = {seat.slot: seat.name for seat in await active_teams(session, encounter.id)}
            encounter.name = build_encounter_name([seated.get(slot) for slot in range(1, encounter.slot_count + 1)])
            await after_encounter_teams_changed(session, encounter, channel=True)

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
        """Re-point the advancement edges that fed the two swapped seats.

        A derived seat is owned by the ``EncounterLink`` targeting it; moving
        only the team would leave the next advancement writing the old team
        back into it. One query for both sides, both reads before either write
        -- on an internal swap the two links sit on the same encounter.
        """
        rows = await session.execute(
            select(models.EncounterLink).where(models.EncounterLink.target_encounter_id.in_({source.id, target.id}))
        )
        links = list(rows.scalars().all())

        def _link_for(encounter_id: int, slot: int) -> models.EncounterLink | None:
            return next(
                (link for link in links if link.target_encounter_id == encounter_id and link.target_slot == slot),
                None,
            )

        source_link = _link_for(source.id, data.slot)
        target_link = _link_for(target.id, data.target_slot)
        if source_link is not None:
            source_link.target_encounter_id = target.id
            source_link.target_slot = data.target_slot
        if target_link is not None:
            target_link.target_encounter_id = source.id
            target_link.target_slot = data.slot

    async def update_match(
        self,
        session: AsyncSession,
        match_id: int,
        data: schemas.MatchUpdate,
        *,
        actor: models.AuthUser | None = None,
    ) -> MatchReadContext:
        binding = (
            await session.execute(
                select(models.StatsMatch.encounter_game_id, models.StatsMatch.encounter_id).where(
                    models.StatsMatch.id == match_id
                )
            )
        ).first()
        if binding is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
        await session.execute(
            select(models.Encounter.id)
            .where(
                models.Encounter.id == binding.encounter_id,
            )
            .with_for_update()
        )
        if binding.encounter_game_id is not None:
            await session.execute(
                select(models.EncounterGame.id)
                .where(
                    models.EncounterGame.id == binding.encounter_game_id,
                )
                .with_for_update()
            )
        await session.execute(select(models.StatsMatch.id).where(models.StatsMatch.id == match_id).with_for_update())
        read = (await get_match_reads(session, match_ids=[match_id])).get(match_id)
        if read is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")
        changes = data.model_dump(exclude_unset=True)
        if "map_id" in changes and (
            (read.game is not None and changes["map_id"] != read.game.map_id)
            or changes["map_id"] != read.match.map_entity_id
            or read.map.discipline != read.match.discipline
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stats_match_map_binding_conflict")
        scopes = owner_scopes("match", (match_id,))
        source = "admin" if actor is not None else "system"
        participants = {participant.seat.id: participant for participant in read.participants}
        scores = {}
        for fact in changes.get("team_facts") or ():
            participant = participants.get(fact["encounter_team_id"])
            if participant is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="match_participant_unknown"
                )
            if fact["value"] != participant.team_facts.get("score"):
                scores[participant.seat.id] = fact["value"]
        if scores:
            before = await capture_stats_evidence(session, scopes=scopes)
            try:
                await self.match_repo.set_team_scores(
                    session,
                    match_id=match_id,
                    discipline=read.match.discipline,
                    scores=scores,
                )
            except ValueError as error:
                # The discipline declares no ``score`` statistic: nothing to edit, not a server fault.
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
            after = await capture_stats_evidence(session, scopes=scopes)
            await stage_stats_evidence(
                session,
                operation="stats.score_edit",
                before=before,
                after=after,
                workspace_id=read.match.workspace_id,
                entity_type="match",
                entity_id=match_id,
                source=source,
                actor=actor,
            )
        if "duration_s" in changes and changes["duration_s"] != read.match.duration_s:
            before = await capture_stats_evidence(session, scopes=scopes)
            read.match.duration_s = changes["duration_s"]
            await session.flush()
            after = await capture_stats_evidence(session, scopes=scopes)
            await stage_stats_evidence(
                session,
                operation="stats.match_edit",
                before=before,
                after=after,
                workspace_id=read.match.workspace_id,
                entity_type="match",
                entity_id=match_id,
                source=source,
                actor=actor,
            )
        if read.encounter.tournament_id is not None:
            await enqueue_tournament_recalculation(session, read.encounter.tournament_id)
        await session.commit()
        return (await get_match_reads(session, match_ids=[match_id]))[match_id]

    async def delete_encounter(self, session: AsyncSession, encounter_id: int, *, actor_user_id: int | None) -> None:
        """Delete encounter (cascade deletes matches).

        The FK cascade removes this encounter's ``EncounterLink`` rows, but the
        teams and results it already advanced into later matches would outlive
        it as an orphaned bracket -- so the seats it filled are retired through
        the same cascade an admin correction uses before the row goes. That is
        a human act on somebody else's bracket, hence the actor.
        """
        encounter = await self.encounter_repo.get(session, encounter_id)

        if not encounter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        tournament_id = encounter.tournament_id
        position = await session.get(models.BracketEncounter, encounter_id)
        stage = (
            await session.get(models.Stage, position.stage_id)
            if position is not None and position.stage_id is not None
            else None
        )
        # A Swiss bye is bookkeeping for a round that existed; when the round's
        # last encounter goes, so does the bye recorded for it.
        drop_bye_round = (
            stage is not None
            and stage.stage_type == enums.StageType.SWISS
            and not await self._round_has_other_encounters(session, encounter, position)
        )
        await self._assert_source_correction_allowed(session, encounter)
        evidence = await capture_owner_delete(session, encounter_id=encounter_id)
        # ``reset_downstream`` mutates ORM state and leaves flushing to its
        # caller, and ``session.delete`` does not flush either: the enqueue
        # below is still the first write of this transaction (same ordering
        # contract as create).
        await reset_downstream(session, encounter, actor_user_id=actor_user_id)
        await session.delete(encounter)
        if drop_bye_round:
            await remove_swiss_bye_round(session, stage.id, position.stage_item_id, position.round)
        await enqueue_tournament_recalculation(session, tournament_id)
        await stage_owner_delete(
            session,
            evidence,
            workspace_id=encounter.workspace_id,
            entity_type="encounter",
            entity_id=encounter_id,
        )
        await session.commit()

    @staticmethod
    async def _round_has_other_encounters(
        session: AsyncSession, encounter: models.Encounter, position: models.BracketEncounter | None
    ) -> bool:
        """Any sibling left in this encounter's ``(stage, item, round)``."""
        if position is None:
            return False
        rows = await session.execute(
            select(models.BracketEncounter.encounter_id)
            .where(
                models.BracketEncounter.stage_id == position.stage_id,
                models.BracketEncounter.stage_item_id.is_not_distinct_from(position.stage_item_id),
                models.BracketEncounter.round == position.round,
                models.BracketEncounter.encounter_id != encounter.id,
            )
            .limit(1)
        )
        return rows.first() is not None


encounter_service = AdminEncounterService()
