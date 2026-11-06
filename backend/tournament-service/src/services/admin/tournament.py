"""Admin service layer for tournament CRUD operations"""

from datetime import date
from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core.enums import FlowNodeKind, FlowNodeStatus, TournamentStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.flow.legacy import X_STEP
from shared.domain.tournament_slug import slugify
from shared.repository import (
    ChallongeSourceRepository,
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
from shared.services.tournament.slug import generate_unique_tournament_slug
from src import schemas
from src.clients.challonge import challonge_client
from src.services.draft_guards import assert_no_active_draft_session
from src.services.flow.lifecycle import flow_node_service

# ``src.services.challonge.sync`` is loaded inside ``create_tournament_from_challonge``:
# importing a remote bracket is one path out of this whole service, and at
# module scope it would make every tournament write depend on the exporter.
from src.services.registration_team_guards import assert_no_registered_teams
from src.services.tournament.events import (
    STRUCTURE_RESOURCES,
    enqueue_tournament_state_changed,
    publish_tournament_invalidation,
)


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


class AdminTournamentService:
    def __init__(
        self,
        *,
        tournament_repo: TournamentRepository = TournamentRepository(),
        challonge_source_repo: ChallongeSourceRepository = ChallongeSourceRepository(),
        standing_repo: StandingRepository = StandingRepository(),
    ) -> None:
        self.tournament_repo = tournament_repo
        self.challonge_source_repo = challonge_source_repo
        self.standing_repo = standing_repo

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
        """Create a new tournament, announced until a node of its flow starts."""
        existing_tournament = await self.tournament_repo.get_by(
            session,
            workspace_id=data.workspace_id,
            name=data.name,
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
        registration = models.FlowNode(
            tournament_id=tournament.id,
            kind=FlowNodeKind.REGISTRATION,
            name="Registration",
            status=FlowNodeStatus.DRAFT,
            config={"check_in": False, "intake": "solo"},
        )
        formation = models.FlowNode(
            tournament_id=tournament.id,
            kind=FlowNodeKind.FORMATION,
            name="Teams",
            status=FlowNodeStatus.DRAFT,
            config={"mode": "balancer"},
            position_x=X_STEP,
        )
        session.add_all([registration, formation])
        await session.flush()
        session.add(
            models.FlowEdge(
                tournament_id=tournament.id,
                source_node_id=registration.id,
                source_port="participants",
                target_node_id=formation.id,
                target_port="players",
            )
        )
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

    @staticmethod
    async def _release_flow_node_references(session: AsyncSession, tournament_id: int) -> None:
        """Clear every row that points at the tournament's flow nodes with ``ON DELETE RESTRICT``.

        Deleting the tournament cascades to its nodes and to those rows as siblings, and Postgres fires sibling
        cascades in an order that depends on object ids: a node cascade that fires first sees the entries, the
        sheet feed and the registration teams still there and fails the whole delete. So they go first, here.
        Teams and players only lose their formation node (they are deleted by the tournament cascade itself).
        """
        node_ids = sa.select(models.FlowNode.id).where(models.FlowNode.tournament_id == tournament_id)
        await session.execute(
            sa.delete(models.RegistrationEntry).where(models.RegistrationEntry.registration_node_id.in_(node_ids))
        )
        await session.execute(
            sa.delete(models.RegistrationGoogleSheetFeed).where(
                models.RegistrationGoogleSheetFeed.tournament_id == tournament_id
            )
        )
        await session.execute(
            sa.delete(models.RegistrationTeam).where(models.RegistrationTeam.tournament_id == tournament_id)
        )
        await session.execute(
            sa.update(models.Player).where(models.Player.tournament_id == tournament_id).values(formation_node_id=None)
        )
        await session.execute(
            sa.update(models.Team).where(models.Team.tournament_id == tournament_id).values(formation_node_id=None)
        )

    async def delete_tournament(self, session: AsyncSession, tournament_id: int) -> None:
        """Delete tournament (cascade deletes groups, teams, etc.)"""
        tournament = await self.tournament_repo.get(session, tournament_id)

        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        workspace_id = tournament.workspace_id
        evidence = await capture_owner_delete(session, tournament_id=tournament_id)
        await self._release_flow_node_references(session, tournament_id)
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

    async def set_archived(self, session: AsyncSession, tournament_id: int, archived: bool) -> models.Tournament:
        """The only writer of ``archived`` (spec §9): archiving needs ``completed``, unarchiving returns to it.

        ``is_finished`` is untouched: both statuses are finished. Commits.
        """
        tournament = await flow_node_service.lock_tournament(session, tournament_id)
        required, target = (
            (TournamentStatus.COMPLETED, TournamentStatus.ARCHIVED)
            if archived
            else (TournamentStatus.ARCHIVED, TournamentStatus.COMPLETED)
        )
        if tournament.status != required:
            code = "tournament_not_completed" if archived else "tournament_not_archived"
            raise ApiHTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[ApiExc(code=code, msg=f"Only a {required.value} tournament can be made {target.value}")],
            )
        old_status = tournament.status
        tournament.status = target
        await enqueue_tournament_state_changed(
            session, tournament, old_status=old_status.value, new_status=target.value
        )
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)
        await session.commit()
        return await self.get_tournament(session, tournament_id)


tournament_service = AdminTournamentService()
