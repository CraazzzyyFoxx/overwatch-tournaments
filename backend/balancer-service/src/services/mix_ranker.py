"""The mix ranker's state: a workspace's knobs and its members' hidden ratings.

The formulas live in :mod:`src.domain.mix_ranker` (idea and specification by
Dmitriy, @dmelackov -- https://github.com/mixtura-dev/mixtura-ranker). This
module only loads and stores what they read and write.

The hidden book is derived data: a fold over the workspace's ``casual.match``
history in recording order. A recorded match advances it in place; anything
that rewrites history (an undo) or the scale it is expressed in (the hidden
knobs) rebuilds it from scratch, so it never depends on the order edits came in.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from itertools import groupby
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import CasualTeamSide
from shared.models.balancer import WorkspaceBalancerConfig
from shared.repository import (
    CasualMatchRepository,
    MemberHiddenRatingRepository,
    WorkspaceBalancerConfigRepository,
)
from src.domain.mix_ranker import HiddenRating, Ranker, RankerSettings

__all__ = ("MixRankerService", "RatedSeat", "Seat", "mix_ranker_service", "settings_from_json")

#: ``(workspace_member_id, role slot code, rank snapshot)``; the member is
#: ``None`` for a seat whose player has since left the workspace.
Seat = tuple[int | None, str, int]
#: One seat's hidden rating before and after the match.
RatedSeat = tuple[HiddenRating, HiddenRating]

_FIELDS = tuple(field.name for field in dataclasses.fields(RankerSettings))


def settings_from_json(stored: Mapping[str, Any] | None) -> RankerSettings:
    """The stored knobs over the defaults; a key never saved keeps its default."""
    return RankerSettings(**{key: stored[key] for key in _FIELDS if stored and key in stored})


class MixRankerService:
    def __init__(
        self,
        *,
        hidden: MemberHiddenRatingRepository = MemberHiddenRatingRepository(),
        configs: WorkspaceBalancerConfigRepository = WorkspaceBalancerConfigRepository(),
        casual_matches: CasualMatchRepository = CasualMatchRepository(),
    ) -> None:
        self.hidden = hidden
        self.configs = configs
        self.casual_matches = casual_matches

    async def settings(self, session: AsyncSession, workspace_id: int) -> RankerSettings:
        config = await self.configs.get_by_workspace(session, workspace_id)
        return settings_from_json(config.ranker_json if config is not None else None)

    async def effective_ratings(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        open_ranks: Mapping[tuple[int, str], int],
    ) -> dict[tuple[int, str], int]:
        """The rating each ``(member, role)`` is balanced on; its open rank when it has no hidden one yet."""
        if not open_ranks:
            return {}
        ranker = Ranker(await self.settings(session, workspace_id))
        stored = await self.hidden.for_members(
            session, workspace_id=workspace_id, member_ids=sorted({member_id for member_id, _role in open_ranks})
        )
        return {
            key: round(ranker.effective(rank, HiddenRating(*stored[key]))) if key in stored else rank
            for key, rank in open_ranks.items()
        }

    async def rate_match(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        teams: Sequence[Sequence[Seat]],
        winner: int | None,
    ) -> tuple[Ranker, list[list[RatedSeat]]]:
        """Advance the hidden book by one recorded two-team match.

        A seat without a hidden rating yet is seeded from its rank snapshot --
        the rating it was balanced on, which for a newcomer is its open rank.
        """
        ranker = Ranker(await self.settings(session, workspace_id))
        member_ids = sorted({member_id for team in teams for member_id, _role, _rank in team if member_id is not None})
        stored = await self.hidden.for_members(
            session, workspace_id=workspace_id, member_ids=member_ids, for_update=True
        )
        before = [
            [
                HiddenRating(*stored[(member_id, role)])
                if member_id is not None and (member_id, role) in stored
                else ranker.initial(rank)
                for member_id, role, rank in team
            ]
            for team in teams
        ]
        after = ranker.rate(before, winner)
        await self.hidden.upsert_many(
            session,
            workspace_id=workspace_id,
            ratings={
                (member_id, role): tuple(new)
                for team, new_team in zip(teams, after, strict=True)
                for (member_id, role, _rank), new in zip(team, new_team, strict=True)
                if member_id is not None
            },
        )
        return ranker, [list(zip(old, new, strict=True)) for old, new in zip(before, after, strict=True)]

    async def rebuild(self, session: AsyncSession, workspace_id: int) -> tuple[int, int]:
        """Refold the whole hidden book from the match history; ``(matches, ratings)``.

        ponytail: a full replay per undo / knob change -- ~0.1 ms per match in
        OpenSkill, so seconds at 10^4 matches. Rebuild from a checkpoint instead
        if a workspace's history ever makes this slow.
        """
        ranker = Ranker(await self.settings(session, workspace_id))
        rows = await self.casual_matches.replay_seats_for_workspace(session, workspace_id)
        book: dict[tuple[int, str], HiddenRating] = {}
        matches = 0
        for _match_id, seats in groupby(rows, key=lambda row: row[0]):
            sides: dict[str, tuple[int, list[Seat]]] = {}
            for _id, side, score, member_id, role, rank in seats:
                sides.setdefault(side, (score, []))[1].append(
                    # A seat with no role cannot be keyed; it still counts for its team, unstored.
                    (member_id if role is not None else None, role.slot_code if role is not None else "", rank)
                )
            home, away = sides.get(CasualTeamSide.HOME), sides.get(CasualTeamSide.AWAY)
            if home is None or away is None or not home[1] or not away[1]:
                continue
            winner = 1 if home[0] > away[0] else 2 if away[0] > home[0] else None
            teams = (home[1], away[1])
            # A seat never seen before (or one that cannot be stored) enters at its snapshot.
            before = [
                [book.get((member_id, role)) or ranker.initial(rank) for member_id, role, rank in team]
                for team in teams
            ]
            after = ranker.rate(before, winner)
            for team, new_team in zip(teams, after, strict=True):
                for (member_id, role, _rank), new in zip(team, new_team, strict=True):
                    if member_id is not None:
                        book[(member_id, role)] = new
            matches += 1
        await self.hidden.replace_for_workspace(
            session, workspace_id=workspace_id, ratings={key: tuple(value) for key, value in book.items()}
        )
        return matches, len(book)

    async def save_settings(
        self, session: AsyncSession, *, workspace_id: int, settings: RankerSettings, updated_by: int | None
    ) -> bool:
        """Store the workspace's knobs; ``True`` when that forced a rebuild.

        Raises ``ValueError`` for knobs the formulas cannot run on.
        """
        Ranker(settings)
        config = await self.configs.get_by_workspace(session, workspace_id)
        previous = settings_from_json(config.ranker_json if config is not None else None)
        payload = dataclasses.asdict(settings)
        if config is None:
            await self.configs.create(
                session,
                WorkspaceBalancerConfig(
                    workspace_id=workspace_id, config_json={}, ranker_json=payload, updated_by=updated_by
                ),
            )
        else:
            await self.configs.update_fields(session, config, {"ranker_json": payload, "updated_by": updated_by})
        if previous.hidden_scale() == settings.hidden_scale():
            return False
        await self.rebuild(session, workspace_id)
        return True

    async def count(self, session: AsyncSession, workspace_id: int) -> int:
        return await self.hidden.count_for_workspace(session, workspace_id)


mix_ranker_service = MixRankerService()
