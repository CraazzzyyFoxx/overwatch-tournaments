"""The captain's pick queue ("My list"): a private autopick priority.

Stored on ``draft_team.pick_queue`` and deliberately absent from
``DraftTeamRead`` and every realtime payload: the board is public and the
broadcast topic is read by everyone in the room, so a captain's shortlist would
be a scouting report for the table. It reaches exactly one audience -- the team
that owns it (and an organizer with ``team.create``) -- through these two reads.

The queue is a PRIORITY, not a promise: ``DraftSelectionService.autopick``
consults it first and falls back to the session's fit strategy, and the preview
returned here is that same call, so what a captain sees is what the clock does.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPlayerStatus, DraftStatus
from shared.models.balancer.draft import DraftSession, DraftTeam
from shared.repository.draft import DraftPickRepository
from src import schemas
from src.domain.draft.entities import DraftSnapshot
from src.services.draft._errors import err as _err
from src.services.draft.feasibility import DraftFeasibilityService, feasibility_service
from src.services.draft.selection import DraftSelectionService, selection_service

__all__ = ("DraftQueueService", "queue_service")

#: A queue only means anything while the board can still move.
_CLOSED_STATUSES = (DraftStatus.COMPLETED.value, DraftStatus.CANCELLED.value)
#: The clock only runs for a team in these two; PAUSED counts, because the
#: pick is still theirs and resuming hands it straight back to them.
_ON_CLOCK_STATUSES = (DraftStatus.LIVE.value, DraftStatus.PAUSED.value)


class DraftQueueService:
    def __init__(
        self,
        *,
        picks_repo: DraftPickRepository = DraftPickRepository(),
        feasibility: DraftFeasibilityService = feasibility_service,
        selection: DraftSelectionService = selection_service,
    ) -> None:
        self.picks_repo = picks_repo
        self.feasibility = feasibility
        self.selection = selection

    async def read(
        self, session: AsyncSession, draft_session: DraftSession, team: DraftTeam
    ) -> schemas.DraftTeamQueueResponse:
        snapshot = await self.feasibility.load_snapshot(session, draft_session)
        return await self._response(session, draft_session, team, snapshot, list(team.pick_queue or []))

    async def write(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        team: DraftTeam,
        player_ids: Sequence[int],
    ) -> schemas.DraftTeamQueueResponse:
        if draft_session.status in _CLOSED_STATUSES:
            raise _err("draft_closed", "This draft is over; its queues are read-only")
        snapshot = await self.feasibility.load_snapshot(session, draft_session)
        seatable = {
            player.id
            for player in snapshot.players
            if player.status == DraftPlayerStatus.AVAILABLE.value and not player.is_captain
        }
        # Dedupe keeping the captain's first placement: a list that says "him
        # first, and also him fourth" means him first.
        cleaned: list[int] = []
        for player_id in player_ids:
            if player_id in cleaned:
                continue
            if player_id not in seatable:
                raise _err(
                    "player_not_queueable",
                    f"Player {player_id} is not an available player of this draft",
                    status_code=422,
                )
            cleaned.append(player_id)
        # New list, never in-place: an in-place mutation of a JSONB column is
        # invisible to the unit of work and the write silently vanishes.
        team.pick_queue = cleaned
        await session.flush()
        return await self._response(session, draft_session, team, snapshot, cleaned)

    async def _response(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        team: DraftTeam,
        snapshot: DraftSnapshot,
        stored: list[int],
    ) -> schemas.DraftTeamQueueResponse:
        # Filtered on READ rather than pruned on write: a player picked by
        # somebody else simply stops showing, and a rollback puts them back
        # where the captain had them.
        available = {
            player.id for player in snapshot.players if player.status == DraftPlayerStatus.AVAILABLE.value
        }
        return schemas.DraftTeamQueueResponse(
            team_id=team.id,
            player_ids=[player_id for player_id in stored if player_id in available],
            autopick_preview=await self._preview(session, draft_session, team.id, snapshot),
        )

    async def _preview(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        team_id: int,
        snapshot: DraftSnapshot,
    ) -> schemas.DraftAutopickPreview | None:
        """What autopick would take for this team RIGHT NOW, or ``None``.

        Only while the team is genuinely on the clock: off the clock there is no
        pick to preview, and answering for the next one would be a guess at an
        order that has not happened yet.
        """
        if draft_session.status not in _ON_CLOCK_STATUSES or draft_session.current_pick_id is None:
            return None
        pick = await self.picks_repo.get(session, draft_session.current_pick_id)
        if pick is None or pick.draft_team_id != team_id:
            return None
        choice = await self.selection.autopick_choice(session, draft_session, pick, snapshot=snapshot)
        if choice is None:
            return None
        shape = await self.feasibility.resolve_shape(session, draft_session)
        return schemas.DraftAutopickPreview(
            player_id=choice.player_id,
            role=choice.role.slot_code if shape.has_role_slots else None,
            source=choice.source,
        )


queue_service = DraftQueueService()
