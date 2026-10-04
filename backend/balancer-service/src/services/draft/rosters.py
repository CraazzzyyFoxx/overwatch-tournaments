"""The draft's only door to roles and ranks.

One load per request resolves every seated registration through the engine
(``shared.services.roster``) and keys the answer by ``DraftPlayer.id``, so the
board, feasibility, the pick options, autopick and the team export all read the
same numbers -- the numbers the balancer shows -- and none of them derives
anything.

Nothing here caches across requests: the point of deleting the draft's roles
snapshot was that a cache is exactly what went stale.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPlayerStatus
from shared.domain.roster import PlayerRoster
from shared.models.balancer.draft import DraftPlayer, DraftSession
from shared.services.roster import RosterEngine, roster_engine

__all__ = ("DraftRosterService", "draft_rosters")


class DraftRosterService:
    def __init__(self, *, engine: RosterEngine = roster_engine) -> None:
        self.engine = engine

    async def load(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        players: Collection[DraftPlayer],
    ) -> dict[int, PlayerRoster]:
        """``{draft_player.id: PlayerRoster}`` for the given seats.

        Two leniencies, because the two kinds of seat need opposite ones. A seat
        that is no longer AVAILABLE (picked, removed) is history: a registration
        soft-deleted or excluded mid-draft still has to render on the board and
        keep its frozen picks readable, so it resolves with ``include_deleted``.
        An AVAILABLE seat is a draftable option, so it has to pass ``pool_only``
        -- the panel's own pool predicate -- and a registration excluded,
        unapproved or soft-deleted mid-draft simply stops resolving, which every
        consumer already reads as "no roster" (and therefore not draftable:
        ``resolve_pick_slot`` raises ``player_unranked``).

        They differ only in WHICH registrations resolve, never in how, so the
        pool narrows to ids first and ONE engine pass resolves the union. Running
        the engine once per leniency re-selected, re-ranked and rebuilt every
        registration a second time on every read (2026-09-30).
        """
        if not players:
            return {}
        available: set[int] = set()
        frozen: set[int] = set()
        for player in players:
            target = available if player.status == DraftPlayerStatus.AVAILABLE.value else frozen
            target.add(player.registration_id)
        # ``frozen`` wins over ``available``: a registration seated twice keeps
        # the lenient answer, so its picked seat never loses its roster.
        pool = await self.engine.pool_ids(session, draft_session.tournament_id, sorted(available - frozen))
        by_registration = await self.engine.for_tournament(
            session,
            draft_session.tournament_id,
            registration_ids=sorted(frozen | pool),
            include_deleted=True,
        )
        return {
            player.id: by_registration[player.registration_id]
            for player in players
            if player.registration_id in by_registration
        }

    async def pool(self, session: AsyncSession, tournament_id: int) -> dict[int, PlayerRoster]:
        """The balancer pool, resolved -- what a seed may seat, keyed by registration."""
        return await self.engine.for_tournament(session, tournament_id, pool_only=True)


draft_rosters = DraftRosterService()
