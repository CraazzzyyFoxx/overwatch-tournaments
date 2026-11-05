"""The draft's only door to roles and ranks.

One load per request resolves every seat through its owner's engine and keys the answer by ``DraftPlayer.id``, so
the board, feasibility, the pick options, autopick and the export all read the same numbers -- the numbers the
balancer shows -- and none of them derives anything. A tournament seat resolves its registration
(``shared.services.roster``); a mix seat its member, on the host's book (``CustomGameService.draft_rosters``).

Nothing here caches across requests, so the draft never reads a rank the balancer has since changed.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPlayerStatus, MixParticipation
from shared.domain.roster import PlayerRoster
from shared.models.draft import DraftPlayer, DraftSession
from shared.services.roster import RosterEngine, roster_engine
from src.services.custom_game import CustomGameService, custom_game_service

__all__ = ("DraftRosterService", "draft_rosters")


class DraftRosterService:
    def __init__(self, *, engine: RosterEngine = roster_engine, mixes: CustomGameService = custom_game_service) -> None:
        self.engine = engine
        self.mixes = mixes

    async def load(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        players: Collection[DraftPlayer],
    ) -> dict[int, PlayerRoster]:
        """Resolve ``{draft_player.id: PlayerRoster}`` for the given seats.

        Two leniencies, because the two kinds of seat need opposite ones. A seat that is no longer AVAILABLE is
        history and always resolves. An AVAILABLE seat is a draftable option: a tournament registration must still
        pass the panel's pool predicate (``pool_only``), and a mix member who is away does not resolve -- an away
        player leaves the draft pool (spec §9.5). Every consumer reads "no roster" as "not draftable".
        """
        if not players:
            return {}
        if draft_session.custom_game_id is not None:
            game = await self.mixes.games.get(session, draft_session.custom_game_id)
            rosters, away = await self.mixes.draft_rosters(session, game, [p.workspace_member_id for p in players])
            return {
                player.id: rosters[player.workspace_member_id]
                for player in players
                if player.workspace_member_id in rosters
                and not (player.status == DraftPlayerStatus.AVAILABLE.value and player.workspace_member_id in away)
            }
        available: set[int] = set()
        frozen: set[int] = set()
        for player in players:
            target = available if player.status == DraftPlayerStatus.AVAILABLE.value else frozen
            target.add(player.registration_id)
        # ``frozen`` wins over ``available``: a registration seated twice keeps
        # the lenient answer, so its picked seat never loses its roster.
        pool = await self.engine.pool_ids(session, draft_session.formation_node_id, sorted(available - frozen))
        # A seat's roster is its registration's deciding entry upstream of the formation (the newest intake's).
        by_registration = await self.engine.for_node_registrations(
            session, draft_session.formation_node_id, sorted(frozen | pool), include_deleted=True
        )
        return {
            player.id: by_registration[player.registration_id]
            for player in players
            if player.registration_id in by_registration
        }

    async def pool(self, session: AsyncSession, draft_session: DraftSession) -> dict[int, PlayerRoster]:
        """What a seed may seat, resolved and keyed by ``PoolSeat.key``: the formation node's balancer pool by
        registration, or the mix's present, non-benched roster by member."""
        if draft_session.custom_game_id is not None:
            game = await self.mixes.games.get(session, draft_session.custom_game_id)
            rows = [
                row
                for row in await self.mixes.roster.list_for_game(session, game.id)
                if row.participation != MixParticipation.BENCHED and not row.away
            ]
            rosters, _away = await self.mixes.draft_rosters(session, game, [row.workspace_member_id for row in rows])
            return rosters
        return await self.engine.for_node_input(session, draft_session.formation_node_id, pool_only=True)


draft_rosters = DraftRosterService()
