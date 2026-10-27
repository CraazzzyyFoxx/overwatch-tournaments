from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import TournamentLinkRepository
from shared.services.realtime import Resource, Scope, emit
from src import schemas

_CONFLICT_DETAIL = "Tournament link with this kind and url already exists for this tournament."


class TournamentLinkService:
    def __init__(
        self,
        *,
        link_repo: TournamentLinkRepository = TournamentLinkRepository(),
    ) -> None:
        self.link_repo = link_repo

    async def list_links(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        active_only: bool = False,
    ) -> list[models.TournamentLink]:
        return list(await self.link_repo.list_for_tournament(session, tournament_id, active_only=active_only))

    async def list_links_bulk(
        self,
        session: AsyncSession,
        tournament_ids: Sequence[int],
        *,
        active_only: bool = False,
    ) -> dict[int, list[models.TournamentLink]]:
        return await self.link_repo.list_for_tournaments(session, tournament_ids, active_only=active_only)

    async def get_link(self, session: AsyncSession, link_id: int) -> models.TournamentLink:
        link = await self.link_repo.get(session, link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tournament link not found.",
            )
        return link

    async def _assert_no_conflict(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        kind: str,
        url: str,
        exclude_id: int | None = None,
    ) -> None:
        # The unique constraint is checked explicitly rather than by catching
        # IntegrityError: a failed flush poisons the session for the rest of the
        # request, and the 409 must carry a domain message, not a driver one.
        existing = await self.link_repo.find_conflict(
            session, tournament_id=tournament_id, kind=kind, url=url, exclude_id=exclude_id
        )
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CONFLICT_DETAIL)

    async def create_link(
        self,
        session: AsyncSession,
        data: schemas.TournamentLinkCreate,
    ) -> models.TournamentLink:
        await self._assert_no_conflict(
            session,
            tournament_id=data.tournament_id,
            kind=data.kind,
            url=str(data.url),
        )

        link = await self.link_repo.create(
            session,
            models.TournamentLink(
                tournament_id=data.tournament_id,
                kind=data.kind,
                label=data.label,
                url=str(data.url),
                sort_order=data.sort_order,
                is_active=data.is_active,
            ),
        )
        await _invalidate(session, link.tournament_id)
        await session.commit()
        await session.refresh(link)
        return link

    async def update_link(
        self,
        session: AsyncSession,
        link_id: int,
        data: schemas.TournamentLinkUpdate,
    ) -> models.TournamentLink:
        link = await self.get_link(session, link_id)
        update_data = data.model_dump(mode="json", exclude_unset=True)

        next_kind = update_data.get("kind", link.kind)
        next_url = update_data.get("url", link.url)
        if next_kind != link.kind or next_url != link.url:
            await self._assert_no_conflict(
                session,
                tournament_id=link.tournament_id,
                kind=next_kind,
                url=next_url,
                exclude_id=link.id,
            )

        for field, value in update_data.items():
            setattr(link, field, value)
        await _invalidate(session, link.tournament_id)
        await session.commit()
        await session.refresh(link)
        return link

    async def deactivate_link(self, session: AsyncSession, link_id: int) -> None:
        link = await self.get_link(session, link_id)
        link.is_active = False
        await _invalidate(session, link.tournament_id)
        await session.commit()


async def _invalidate(session: AsyncSession, tournament_id: int) -> None:
    """``tournament.detail``: the public overview carries the active links and is
    cached under that generation, so a link write without this serves stale
    links and never tells an open page to refetch."""
    await emit(session, scope=Scope.tournament(tournament_id), invalidates=[Resource.TOURNAMENT_DETAIL])


tournament_link_service = TournamentLinkService()
