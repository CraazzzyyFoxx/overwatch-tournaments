"""Admin service layer for tournament CRUD operations"""

from datetime import date
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core import tournament_state
from shared.core.enums import StageType, TournamentStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.tournament_slug import slugify
from shared.repository import (
    ChallongeSourceRepository,
    RegistrationFormRepository,
    StandingRepository,
    TournamentRepository,
    WorkspaceRepository,
)
from shared.schemas.team_format import TeamFormatWrite
from shared.services.division_grid import cache as division_grid_cache
from shared.services.division_grid.access import get_workspace_division_grid_version_id, require_event_grid
from shared.services.ontology import assert_discipline_enabled
from shared.services.realtime import Resource, Scope, emit
from shared.services.stats_owner_delete import capture_owner_delete, stage_owner_delete
from shared.services.team_format import copy_for_tournament, save_tournament_format
from shared.services.tournament.computation import request_bracket_job
from shared.services.tournament.slug import generate_unique_tournament_slug
from src import schemas
from src.clients.challonge import challonge_client
from src.services.admin.stage import stage_service
from src.services.draft_guards import assert_no_active_draft_session

# ``src.services.challonge.sync`` is loaded inside ``create_tournament_from_challonge``:
# importing a remote bracket is one path out of this whole service, and at
# module scope it would make every tournament write depend on the exporter.
from src.services.notifications.lifecycle import lifecycle_notifier
from src.services.registration_team_guards import assert_no_registered_teams
from src.services.tournament.events import (
    STRUCTURE_RESOURCES,
    enqueue_tournament_state_changed,
    publish_tournament_invalidation,
)

GROUP_STAGE_TYPES = {StageType.ROUND_ROBIN, StageType.SWISS, StageType.FFA_LEAGUE}


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

        That row (source_type='tournament') is the sole persistence target for the
        tournament↔Challonge link.
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
        discipline: str,
        division_grid_version_id: int | None,
    ) -> int:
        resolved_version_id = division_grid_version_id
        if resolved_version_id is None:
            resolved_version_id = await get_workspace_division_grid_version_id(
                session, workspace_id, discipline=discipline
            )
        if resolved_version_id is not None:
            owner = (
                await session.execute(
                    sa.select(models.DivisionGrid.workspace_id, models.DivisionGrid.discipline)
                    .join(models.DivisionGridVersion, models.DivisionGridVersion.grid_id == models.DivisionGrid.id)
                    .where(models.DivisionGridVersion.id == resolved_version_id)
                )
            ).one_or_none()
            if owner is None or owner[0] not in {None, workspace_id}:
                raise HTTPException(status_code=400, detail="Division grid version does not belong to this workspace")
            if owner[1] != discipline:
                raise HTTPException(
                    status_code=422,
                    detail=f"division_grid_discipline_mismatch: the grid is {owner[1]!r}, the tournament {discipline!r}",
                )
        await require_event_grid(session, version_id=resolved_version_id, discipline=discipline)
        if resolved_version_id is None:
            raise HTTPException(status_code=400, detail="Workspace does not have a default division grid version")
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
        refresh is warranted — but the ``DETAIL`` generation behind
        ``flows.get_read`` still has to move, or the public page keeps serving
        the previous banner for the whole TTL and the organizer sees the upload
        "not work".
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

        workspace = await WorkspaceRepository().get(session, data.workspace_id)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        assert_discipline_enabled(workspace, data.discipline)

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
            payload["slug"] = await generate_unique_tournament_slug(session, data.name)

        payload["division_grid_version_id"] = await self._resolve_division_grid_version_id(
            session,
            workspace_id=data.workspace_id,
            discipline=data.discipline,
            division_grid_version_id=data.division_grid_version_id,
        )

        tournament = await self.tournament_repo.create(session, models.Tournament(**payload))
        await copy_for_tournament(session, tournament)
        await publish_tournament_invalidation(session, tournament.id, STRUCTURE_RESOURCES)
        await session.commit()
        await division_grid_cache.invalidate_tournament(tournament.id)
        await division_grid_cache.invalidate_workspace(tournament.workspace_id)
        return await self.get_tournament(session, tournament.id)

    async def get_team_format_scope(self, session: AsyncSession, tournament_id: int) -> sa.Row:
        """The three columns a team-format read uses, not the admin tournament load
        (its stage tree and grid are five more statements this never reads)."""
        tournament = await self.tournament_repo.get_format_scope_row(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        return tournament

    async def replace_team_format(
        self, session: AsyncSession, tournament_id: int, body: TeamFormatWrite
    ) -> models.Tournament:
        """Replace the tournament copy only before drafts or registered teams hold slots."""
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
        await assert_no_active_draft_session(session, tournament_id, change="the team format")
        await assert_no_registered_teams(session, tournament_id, change="the team format")
        await save_tournament_format(session, tournament, body.to_domain(tournament.discipline))
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        await session.commit()
        return tournament

    async def update_tournament(
        self, session: AsyncSession, tournament_id: int, data: schemas.TournamentUpdate
    ) -> models.Tournament:
        """Apply an admin edit.

        Linking a Challonge bracket asks Challonge first (up to 15 s), and that
        wait must not hold a pooled server connection idle in a transaction. So
        the caller's read-only transaction (its permission lookup) ends before
        the call: nothing has been flushed yet, so a rollback loses nothing but
        the pending rows it staged -- the CRUD engine's audit row -- which are
        put back afterwards. A caller must not have flushed writes before this.
        """
        update_data = data.model_dump(exclude_unset=True)
        challonge_tournament = None
        if update_data.get("challonge_slug"):
            pending = list(session.new)
            await session.rollback()
            challonge_tournament = await challonge_client.fetch_tournament(
                _normalize_challonge_slug(update_data["challonge_slug"])
            )
            session.add_all(pending)

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

        if "team_formation" in update_data and update_data["team_formation"] != tournament.team_formation:
            await assert_no_active_draft_session(session, tournament_id)

        # Same lock, one level down: the session snapshots the format at create
        # time, so an edit mid-draft would promise a change the running board
        # will never honour. Both sides are normalized (DraftFormatField in,
        # this same path out), so a Settings-tab resend is not a change.
        if "draft_format_json" in update_data and update_data["draft_format_json"] != tournament.draft_format_json:
            await assert_no_active_draft_session(session, tournament_id, change="the draft format")

        if "challonge_slug" in update_data:
            update_data.pop("challonge_slug")
            if challonge_tournament is not None:
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
                discipline=tournament.discipline,
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
        return await self.get_tournament(session, tournament_id)

    async def create_tournament_from_challonge(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        discipline: str,
        is_league: bool,
        start_date: date,
        end_date: date,
        challonge_slug: str,
        division_grid_version_id: int | None = None,
    ) -> models.Tournament:
        """Bootstrap a new tournament from an existing Challonge bracket: fetch it
        (its name/description become the tournament's), create the tournament, link
        the bracket the same way ``update_tournament(challonge_slug=...)`` does, then
        pull its current structure and results in one shot, exactly like a manual
        "Sync from Challonge" run would.
        """
        challonge_tournament = await challonge_client.fetch_tournament(_normalize_challonge_slug(challonge_slug))

        tournament = await self.create_tournament(
            session,
            schemas.TournamentCreate(
                workspace_id=workspace_id,
                discipline=discipline,
                name=challonge_tournament.name,
                description=challonge_tournament.description,
                is_league=is_league,
                start_date=start_date,
                end_date=end_date,
                logs_official=False,  # an imported bracket never starts accepting ingest evidence
                division_grid_version_id=division_grid_version_id,
            ),
        )
        await self._link_tournament_challonge_source(
            session, tournament, challonge_id=challonge_tournament.id, slug=challonge_tournament.url
        )
        await session.commit()
        from src.services.challonge.sync import sync_service  # noqa: PLC0415

        await sync_service.import_tournament(session, tournament.id)
        return await self.get_tournament(session, tournament.id)

    async def delete_tournament(self, session: AsyncSession, tournament_id: int) -> None:
        """Delete tournament (cascade deletes groups, teams, etc.)"""
        tournament = await self.tournament_repo.get(session, tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        workspace_id = tournament.workspace_id
        evidence = await capture_owner_delete(session, tournament_id=tournament_id)
        await self.standing_repo.delete_for_tournament(session, tournament_id)
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        await self.tournament_repo.delete(session, tournament)
        await stage_owner_delete(
            session,
            evidence,
            workspace_id=workspace_id,
            entity_type="tournament",
            entity_id=tournament_id,
        )
        await session.commit()
        await division_grid_cache.invalidate_tournament(tournament_id)
        await division_grid_cache.invalidate_workspace(workspace_id)

    async def _stage_has_encounters(self, session: AsyncSession, stage_id: int) -> bool:
        # Analytical: grouped count, not a CRUD row read. An encounter's stage is
        # its bracket POSITION, so the count is over that table.
        count = await session.scalar(
            sa.select(sa.func.count(models.BracketEncounter.encounter_id)).where(
                models.BracketEncounter.stage_id == stage_id
            )
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

        group_stages = [
            stage
            for stage in getattr(tournament, "stages", []) or []
            if stage.stage_type in GROUP_STAGE_TYPES and not getattr(stage, "is_completed", False)
        ]
        if not group_stages:
            return

        # Stages sharing an ``order`` are one phase and run in parallel (Low /
        # High divisions), so the whole wave starts, not just its first stage.
        phase = min(stage.order for stage in group_stages)
        wave = [stage for stage in group_stages if stage.order == phase]
        active = [stage for stage in wave if getattr(stage, "is_active", False)]
        for stage in active or wave:
            await self._auto_start_stage(session, tournament, stage)

    async def _auto_start_stage(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        stage: models.Stage,
    ) -> None:
        has_encounters = await self._stage_has_encounters(session, stage.id)

        if not getattr(stage, "is_active", False):
            if not has_encounters and not _stage_has_ready_inputs(stage):
                return
            if has_encounters:
                await stage_service.activate_stage(session, stage.id, commit=False)
            else:
                await request_bracket_job(
                    session,
                    tournament_id=tournament.id,
                    stage_id=stage.id,
                    operation="activate_and_generate",
                )
                return

        if not has_encounters and _stage_has_ready_inputs(stage):
            await request_bracket_job(
                session,
                tournament_id=tournament.id,
                stage_id=stage.id,
                operation="generate_stage",
            )

    async def toggle_finished(self, session: AsyncSession, tournament_id: int) -> models.Tournament:
        """The hub's "mark finished / reopen" button, as a two-way COMPLETED move.

        Delegates to ``transition_status`` so the lifecycle state machine has
        exactly one writer.

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
        entering it without a form advertises a sign-up that cannot be completed.
        ``force`` bypasses this the same way it bypasses the transition matrix: it
        is the superuser-only "I know what I am doing" switch, and a
        Challonge-sourced tournament that never takes its own registrations is the
        case that needs it.
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
        await lifecycle_notifier.on_status_entered(session, tournament)
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        # Before the commit: the bracket job it requests is a row in this
        # session, and neither caller (the RPC envelope, the worker tick)
        # commits after us.
        await self._maybe_auto_start_group_stage(
            session,
            tournament,
            target_status=target_status,
        )
        await session.commit()
        return await self.get_tournament(session, tournament_id)


tournament_service = AdminTournamentService()
