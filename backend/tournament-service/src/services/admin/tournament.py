"""Admin service layer for tournament CRUD operations"""

from datetime import date
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core import tournament_state
from shared.core.enums import StageType, TournamentStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    ChallongeSourceRepository,
    RegistrationFormRepository,
    StandingRepository,
    TournamentRepository,
)
from shared.services.division_grid import cache as division_grid_cache
from shared.services.division_grid.access import get_workspace_division_grid_version_id
from shared.services.draft_guards import assert_no_active_draft_session
from shared.services.realtime import Resource, Scope, emit
from shared.services.registration_team_guards import assert_no_registered_teams
from shared.services.roster_shape_access import invalidate_roster_shape_cache
from shared.services.tournament.computation import request_bracket_job
from shared.services.tournament.slug import generate_unique_tournament_slug, slugify
from src import models, schemas
from src.clients.challonge import challonge_client
from src.services.admin.stage import stage_service
from src.services.challonge.sync import sync_service
from src.services.tournament.events import (
    STRUCTURE_RESOURCES,
    enqueue_tournament_state_changed,
    publish_tournament_invalidation,
)

GROUP_STAGE_TYPES = {StageType.ROUND_ROBIN, StageType.SWISS}


def _status_value(value: TournamentStatus | str) -> str:
    return value.value if isinstance(value, TournamentStatus) else str(value)


def _normalize_challonge_slug(value: str) -> str:
    slug = value.strip()
    if not slug:
        return ""

    if "://" not in slug and "." not in slug:
        return slug.strip("/")

    candidate = slug if "://" in slug else f"https://{slug}"
    parsed = urlparse(candidate)
    if "challonge.com" in parsed.netloc:
        path = parsed.path.strip("/")
        if path:
            return path.split("/")[-1]

    return slug.strip("/").split("/")[-1]


def _stage_has_ready_inputs(stage: models.Stage) -> bool:
    stage_items = list(getattr(stage, "items", []) or [])
    if not stage_items:
        return False

    for item in stage_items:
        team_count = sum(1 for stage_input in getattr(item, "inputs", []) if stage_input.team_id is not None)
        if team_count < 2:
            return False
    return True


class AdminTournamentService:
    def __init__(
        self,
        *,
        tournament_repo: TournamentRepository = TournamentRepository(),
        challonge_source_repo: ChallongeSourceRepository = ChallongeSourceRepository(),
        standing_repo: StandingRepository = StandingRepository(),
        registration_form_repo: RegistrationFormRepository = RegistrationFormRepository(),
    ) -> None:
        self.tournament_repo = tournament_repo
        self.challonge_source_repo = challonge_source_repo
        self.standing_repo = standing_repo
        self.registration_form_repo = registration_form_repo

    async def _link_tournament_challonge_source(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        challonge_id: int,
        slug: str | None,
    ) -> None:
        """Create/update the tournament-scoped ``challonge_source`` row.

        Replaces the legacy ``tournament.challonge_id`` / ``challonge_slug`` write:
        the normalized ``challonge_source`` (source_type='tournament') is now the
        sole persistence target for the tournament↔Challonge link.
        """
        source = await self.challonge_source_repo.get_tournament_source(session, tournament.id)
        if source is None:
            session.add(
                models.ChallongeSource(
                    tournament_id=tournament.id,
                    challonge_tournament_id=challonge_id,
                    slug=slug,
                    source_type="tournament",
                )
            )
        else:
            source.challonge_tournament_id = challonge_id
            source.slug = slug

    async def _unlink_tournament_challonge_source(self, session: AsyncSession, tournament: models.Tournament) -> None:
        """Drop the tournament-scoped ``challonge_source`` row(s) when the link is cleared."""
        await self.challonge_source_repo.delete_tournament_source(session, tournament.id)

    async def _resolve_division_grid_version_id(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        division_grid_version_id: int | None,
    ) -> int:
        resolved_version_id = division_grid_version_id
        if resolved_version_id is None:
            resolved_version_id = await get_workspace_division_grid_version_id(session, workspace_id)

        if resolved_version_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workspace does not have a default division grid version",
            )

        # Analytical: join + single-column projection across grid/version, not CRUD.
        version_workspace = await session.scalar(
            sa.select(models.DivisionGrid.workspace_id)
            .join(models.DivisionGridVersion, models.DivisionGridVersion.grid_id == models.DivisionGrid.id)
            .where(models.DivisionGridVersion.id == resolved_version_id)
        )
        if version_workspace not in {None, workspace_id}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Division grid version does not belong to this workspace",
            )

        return int(resolved_version_id)

    async def get_tournament(self, session: AsyncSession, tournament_id: int) -> models.Tournament:
        """Get one tournament with stages and its own division grid loaded for admin workspaces."""
        tournament = await self.tournament_repo.get(
            session,
            tournament_id,
            options=[
                selectinload(models.Tournament.stages)
                .selectinload(models.Stage.items)
                .selectinload(models.StageItem.inputs),
                # Eager, because `flows._loaded_relationship` reports an unloaded
                # relationship as None rather than lazy-loading it outside the
                # greenlet. Without this the admin read serializes
                # `division_grid_version: null` even when the tournament pins one,
                # and the hub falls back to the workspace/OW grid.
                selectinload(models.Tournament.division_grid_version),
            ],
        )

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        return tournament

    async def set_tournament_image(
        self, session: AsyncSession, tournament_id: int, *, slot: str, url: str | None
    ) -> models.Tournament:
        """Set (or clear, with ``None``) the tournament's cover banner or square logo.

        Deliberately separate from ``update_tournament``, for the same reason
        ``services/admin/team.py::set_team_image`` is separate from ``update_team``:
        the column is only ever written by the dedicated upload/delete RPC subjects
        *after* S3 accepted the bytes, and ``TournamentUpdate`` carries no image
        fields at all — a PATCH body must not be able to point the banner at an
        arbitrary URL.

        ``tournament.detail`` rather than ``tournament.structure``: an image swap
        changes nothing a bracket or standings recompute would read and adds no
        page section, so neither the cross-service outbox row nor a client route
        refresh is warranted — but the cashews key behind ``flows.get_read``
        (``tournaments/{id}:{entities}``) still has to go, or the public page
        keeps serving the previous banner for the whole TTL and the organizer
        sees the upload "not work".
        """
        tournament = await self.tournament_repo.get(session, tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        if slot == "cover":
            tournament.cover_image_url = url
        else:
            tournament.logo_url = url

        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_DETAIL],
        )
        await session.commit()
        return await self.get_tournament(session, tournament_id)

    async def create_tournament(self, session: AsyncSession, data: schemas.TournamentCreate) -> models.Tournament:
        """Create a new tournament.

        REGISTRATION is refused outright here, with no ``force`` counterpart: the
        registration form belongs to a tournament that does not exist yet, so a
        tournament created straight into REGISTRATION cannot possibly have one.
        Create it (announced, the default) and transition once the form is saved.
        """
        if data.status == TournamentStatus.REGISTRATION:
            raise ApiHTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[
                    ApiExc(
                        code="registration_form_missing",
                        msg=(
                            "A tournament cannot be created with registration already open — it has "
                            "no registration form yet. Create it, save the form, then open registration."
                        ),
                    )
                ],
            )

        existing_tournament = await self.tournament_repo.get_by(
            session,
            workspace_id=data.workspace_id,
            name=data.name,
            is_league=data.is_league,
        )

        if existing_tournament:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tournament with this name already exists in this workspace",
            )

        payload = data.model_dump()
        if data.slug:
            requested_slug = slugify(data.slug)
            slug_taken = await self.tournament_repo.get_by_slug(session, requested_slug)
            redirect_taken = await session.scalar(
                sa.select(models.TournamentSlugRedirect.id).where(
                    models.TournamentSlugRedirect.old_slug == requested_slug
                )
            )
            if slug_taken is not None or redirect_taken is not None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slug already in use")
            payload["slug"] = requested_slug
        else:
            payload["slug"] = await generate_unique_tournament_slug(
                session, data.name, tournament_repo=self.tournament_repo
            )

        payload["division_grid_version_id"] = await self._resolve_division_grid_version_id(
            session,
            workspace_id=data.workspace_id,
            division_grid_version_id=data.division_grid_version_id,
        )

        tournament = await self.tournament_repo.create(session, models.Tournament(**payload))
        await publish_tournament_invalidation(session, tournament.id, STRUCTURE_RESOURCES)
        await session.commit()
        await division_grid_cache.invalidate_tournament(tournament.id)
        await division_grid_cache.invalidate_workspace(tournament.workspace_id)
        return await self.get_tournament(session, tournament.id)

    async def update_tournament(
        self, session: AsyncSession, tournament_id: int, data: schemas.TournamentUpdate
    ) -> models.Tournament:
        """Update tournament fields"""
        tournament = await self.tournament_repo.get(
            session,
            tournament_id,
            options=[
                selectinload(models.Tournament.stages)
                .selectinload(models.Stage.items)
                .selectinload(models.StageItem.inputs)
            ],
        )

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        # Update fields
        update_data = data.model_dump(exclude_unset=True)
        if "team_formation" in update_data and update_data["team_formation"] != tournament.team_formation:
            await assert_no_active_draft_session(session, tournament_id)

        # Both maps are normalized (RosterSlotsField on the way in, this same path on
        # the way out), and dict equality ignores key order -- so a Settings-tab save
        # that resends the current shape is not a change and must not block an
        # unrelated rename mid-draft.
        roster_slots_changed = "roster_slots_json" in update_data and (
            update_data["roster_slots_json"] != tournament.roster_slots_json
        )
        if roster_slots_changed:
            await assert_no_active_draft_session(session, tournament_id, change="roster shape")
            # Registered teams hold slots assigned from the shape in force when their
            # members accepted; changing it afterwards silently invalidates every one
            # of those rosters. Same protection a live draft already gets.
            await assert_no_registered_teams(session, tournament_id, change="the roster shape")

        if "challonge_slug" in update_data:
            raw_slug = update_data.pop("challonge_slug")
            if raw_slug:
                challonge_slug = _normalize_challonge_slug(raw_slug)
                challonge_tournament = await challonge_client.fetch_tournament(challonge_slug)
                await self._link_tournament_challonge_source(
                    session,
                    tournament,
                    challonge_id=challonge_tournament.id,
                    slug=challonge_tournament.url,
                )
            else:
                await self._unlink_tournament_challonge_source(session, tournament)

        if "slug" in update_data:
            requested_slug = update_data.pop("slug")
            new_slug = slugify(requested_slug) if requested_slug else None
            if new_slug and new_slug != tournament.slug:
                slug_taken = await self.tournament_repo.get_by_slug(session, new_slug)
                redirect_taken = await session.scalar(
                    sa.select(models.TournamentSlugRedirect.id).where(
                        models.TournamentSlugRedirect.old_slug == new_slug
                    )
                )
                if slug_taken is not None or redirect_taken is not None:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slug already in use")
                session.add(models.TournamentSlugRedirect(old_slug=tournament.slug, tournament_id=tournament.id))
                tournament.slug = new_slug

        if "division_grid_version_id" in update_data:
            update_data["division_grid_version_id"] = await self._resolve_division_grid_version_id(
                session,
                workspace_id=tournament.workspace_id,
                division_grid_version_id=update_data["division_grid_version_id"],
            )

        should_invalidate_grid = "division_grid_version_id" in update_data and (
            update_data["division_grid_version_id"] != tournament.division_grid_version_id
        )

        for field, value in update_data.items():
            setattr(tournament, field, value)

        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        await session.commit()
        if should_invalidate_grid:
            await division_grid_cache.invalidate_tournament(tournament_id)
            await division_grid_cache.invalidate_workspace(tournament.workspace_id)
        if roster_slots_changed:
            await invalidate_roster_shape_cache(tournament_id=tournament_id)
        return await self.get_tournament(session, tournament_id)

    async def create_tournament_from_challonge(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        is_league: bool,
        start_date: date,
        end_date: date,
        challonge_slug: str,
        division_grid_version_id: int | None = None,
    ) -> models.Tournament:
        """Bootstrap a new tournament from an existing Challonge bracket: fetch it
        (its name/description become the tournament's), create the tournament, link
        the bracket the same way ``update_tournament(challonge_slug=...)`` does, then
        pull its current structure and results in one shot.

        Supersedes parser-service's old ``tournament.create_with_groups`` (which only
        parsed empty ``TournamentGroup`` rows out of the bracket's matches without
        persisting them) -- ``sync_service.import_tournament`` builds the full
        stage/group/stage-item structure AND imports any already-recorded results,
        exactly like a manual "Sync from Challonge" run would.
        """
        challonge_tournament = await challonge_client.fetch_tournament(_normalize_challonge_slug(challonge_slug))

        tournament = await self.create_tournament(
            session,
            schemas.TournamentCreate(
                workspace_id=workspace_id,
                name=challonge_tournament.name,
                description=challonge_tournament.description,
                is_league=is_league,
                start_date=start_date,
                end_date=end_date,
                division_grid_version_id=division_grid_version_id,
            ),
        )
        await self._link_tournament_challonge_source(
            session, tournament, challonge_id=challonge_tournament.id, slug=challonge_tournament.url
        )
        await session.commit()
        await sync_service.import_tournament(session, tournament.id)
        return await self.get_tournament(session, tournament.id)

    async def delete_tournament(self, session: AsyncSession, tournament_id: int) -> None:
        """Delete tournament (cascade deletes groups, teams, etc.)"""
        tournament = await self.tournament_repo.get(session, tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        workspace_id = tournament.workspace_id
        await self.standing_repo.delete_for_tournament(session, tournament_id)
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        await self.tournament_repo.delete(session, tournament)
        await session.commit()
        await division_grid_cache.invalidate_tournament(tournament_id)
        await division_grid_cache.invalidate_workspace(workspace_id)

    async def _stage_has_encounters(self, session: AsyncSession, stage_id: int) -> bool:
        # Analytical: grouped count, not a CRUD row read.
        count = await session.scalar(
            sa.select(sa.func.count(models.Encounter.id)).where(models.Encounter.stage_id == stage_id)
        )
        return bool(count)

    async def _maybe_auto_start_group_stage(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        target_status: TournamentStatus,
    ) -> None:
        if target_status != TournamentStatus.LIVE:
            return

        stages = sorted(getattr(tournament, "stages", []) or [], key=lambda stage: stage.order)
        group_stages = [
            stage
            for stage in stages
            if stage.stage_type in GROUP_STAGE_TYPES and not getattr(stage, "is_completed", False)
        ]
        if not group_stages:
            return

        active_stage = next((stage for stage in group_stages if getattr(stage, "is_active", False)), None)
        target_stage = active_stage or group_stages[0]
        has_encounters = await self._stage_has_encounters(session, target_stage.id)

        if not active_stage:
            if not has_encounters and not _stage_has_ready_inputs(target_stage):
                return
            if has_encounters:
                await stage_service.activate_stage(session, target_stage.id)
            else:
                await request_bracket_job(
                    session,
                    tournament_id=tournament.id,
                    stage_id=target_stage.id,
                    operation="activate_and_generate",
                )
                return

        if not has_encounters and _stage_has_ready_inputs(target_stage):
            await request_bracket_job(
                session,
                tournament_id=tournament.id,
                stage_id=target_stage.id,
                operation="generate_stage",
            )

    async def toggle_finished(self, session: AsyncSession, tournament_id: int) -> models.Tournament:
        """The hub's "mark finished / reopen" button, as a two-way COMPLETED move.

        It used to write ``status``, ``is_finished`` and ``auto_transitions_enabled``
        by hand, which made it a second writer of the lifecycle beside
        ``transition_status`` — same three fields, same two events, no matrix
        validation, and free to drift. It now delegates, so the state machine has
        exactly one entry point.

        ``force=True`` because reopening walks COMPLETED -> LIVE, an edge the matrix
        deliberately omits: this button is the only sanctioned way back, and the
        RPC subject behind it already carries its own permission check.
        """
        tournament = await self.tournament_repo.get(session, tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        target = TournamentStatus.LIVE if tournament.is_finished else TournamentStatus.COMPLETED
        return await self.transition_status(session, tournament_id, target, force=True)

    async def has_registration_form(self, session: AsyncSession, tournament_id: int) -> bool:
        """Whether the tournament has a saved registration form.

        "Saved" is row-existence, the same thing the admin dashboard reports as
        ``registration_form_configured``: the upsert writes one row per
        tournament and there is no half-saved state below it.

        Public because the worker tick asks the same question with a different
        answer in mind — it skips the tournament, where an admin gets a 409.
        """
        return await self.registration_form_repo.get_by_tournament(session, tournament_id) is not None

    async def transition_status(
        self,
        session: AsyncSession,
        tournament_id: int,
        target_status: TournamentStatus,
        *,
        force: bool = False,
        automated: bool = False,
    ) -> models.Tournament:
        """Transition tournament to a new status with state machine validation.

        Manual transitions (``automated=False``) pause time-driven automation by
        setting ``auto_transitions_enabled = False`` in the same transaction, so
        the tick never fights an admin decision.

        REGISTRATION additionally requires a saved registration form. The status
        is what the public page announces and what the register button reads, so
        entering it without a form advertises a sign-up that cannot be completed
        — the exact mismatch ANNOUNCEMENT was added to end. ``force`` bypasses
        this the same way it bypasses the transition matrix: it is the
        superuser-only "I know what I am doing" switch, and a Challonge-sourced
        tournament that never takes its own registrations is the case that needs
        it.
        """
        tournament = await self.tournament_repo.get(
            session,
            tournament_id,
            options=[
                selectinload(models.Tournament.stages)
                .selectinload(models.Stage.items)
                .selectinload(models.StageItem.inputs)
            ],
        )

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        if not force:
            tournament_state.validate_transition(tournament.status, target_status)

        if (
            not force
            and target_status == TournamentStatus.REGISTRATION
            and not await self.has_registration_form(session, tournament_id)
        ):
            # ``ApiExc`` list, not a bare dict: that is the shape the frontend's
            # `parseApiError` reads, so the organizer sees the sentence below
            # instead of a generic "An error occurred".
            raise ApiHTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[
                    ApiExc(
                        code="registration_form_missing",
                        msg=("This tournament has no registration form yet. Save one before opening registration."),
                    )
                ],
            )

        old_status = _status_value(tournament.status)
        tournament.status = target_status
        tournament.is_finished = tournament_state.is_finished_for_status(target_status)
        if not automated:
            tournament.auto_transitions_enabled = False

        await enqueue_tournament_state_changed(
            session,
            tournament,
            old_status=old_status,
            new_status=_status_value(tournament.status),
        )
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        await session.commit()
        await self._maybe_auto_start_group_stage(
            session,
            tournament,
            target_status=target_status,
        )
        return await self.get_tournament(session, tournament_id)


tournament_service = AdminTournamentService()
