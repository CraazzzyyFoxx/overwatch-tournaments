"""Reads of the mix rounds recorded on the encounter layer.

A round is one ``encounter.encounter`` owned by a ``mix.custom_game`` plus its ``mix.round`` row.
Who sat where is ``encounter.team_member`` (rated-dimension leaf in ``team_member_role``); what only
the balancer reads per member -- busy next door, the frozen rank delta -- is ``mix.round_member``.

Rounds read in RECORDING order: ``encounter.confirmed_at``, then the encounter id for a tie. Not the id alone -- a
round's encounter is created when its match starts, and two lobbies' matches are recorded in any order.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from shared import models
from shared.core.enums import MapPoolEntryStatus, PickBanKind
from shared.models.stats.ingest import IngestJobStatus
from shared.repository.base import BaseRepository

__all__ = ("CustomGameRoundRepository",)

_LOG_STATE = {
    IngestJobStatus.PENDING: "processing",
    IngestJobStatus.PROCESSING: "processing",
    IngestJobStatus.FAILED: "failed",
    IngestJobStatus.AWAITING_LINK: "failed",
}


class CustomGameRoundRepository(BaseRepository[models.CustomGameRound]):
    def __init__(self) -> None:
        super().__init__(models.CustomGameRound)

    def _of_game(self, custom_game_id: int) -> sa.Select[tuple[models.CustomGameRound]]:
        return (
            self.select()
            .join(models.Encounter, models.Encounter.id == models.CustomGameRound.encounter_id)
            .where(models.Encounter.custom_game_id == custom_game_id)
        )

    async def list_for_custom_game(
        self, session: AsyncSession, custom_game_id: int
    ) -> Sequence[models.CustomGameRound]:
        """Newest first, with what history and rotation read: the two seats, the game (map), the journal
        (recorder) and the per-member rows (played / busy). Eager: async sessions cannot lazy-load."""
        encounter = selectinload(models.CustomGameRound.encounter)
        result = await session.scalars(
            self._of_game(custom_game_id)
            .options(
                encounter.selectinload(models.Encounter.teams),
                encounter.selectinload(models.Encounter.games),
                encounter.selectinload(models.Encounter.result_audit),
                selectinload(models.CustomGameRound.members),
            )
            .order_by(models.Encounter.confirmed_at.desc(), models.Encounter.id.desc())
        )
        return result.all()

    async def get_for_game(
        self, session: AsyncSession, custom_game_id: int, encounter_id: int
    ) -> models.CustomGameRound | None:
        """One round of this mix; ``None`` when the id belongs to another mix (ownership is part of the lookup)."""
        return await session.scalar(
            self._of_game(custom_game_id).where(models.CustomGameRound.encounter_id == encounter_id)
        )

    async def newest_id_for_lobby(self, session: AsyncSession, custom_game_id: int, lobby_index: int) -> int | None:
        """The lobby's most recently recorded round -- the only one undo may take."""
        return await session.scalar(
            sa.select(models.CustomGameRound.encounter_id)
            .join(models.Encounter, models.Encounter.id == models.CustomGameRound.encounter_id)
            .where(models.Encounter.custom_game_id == custom_game_id, models.CustomGameRound.lobby_index == lobby_index)
            .order_by(models.Encounter.confirmed_at.desc(), models.Encounter.id.desc())
            .limit(1)
        )

    async def activity_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, tuple[int, datetime]]:
        """``custom_game_id -> (rounds recorded, newest round time)``; a mix with none is absent."""
        if not custom_game_ids:
            return {}
        rows = await session.execute(
            sa.select(
                models.Encounter.custom_game_id,
                sa.func.count().label("rounds"),
                sa.func.max(models.Encounter.created_at).label("last_at"),
            )
            .join(models.CustomGameRound, models.CustomGameRound.encounter_id == models.Encounter.id)
            .where(models.Encounter.custom_game_id.in_(custom_game_ids))
            .group_by(models.Encounter.custom_game_id)
        )
        return {row.custom_game_id: (row.rounds, row.last_at) for row in rows}

    async def activity_for_lobbies(self, session: AsyncSession, custom_game_id: int) -> dict[int, tuple[int, datetime]]:
        """``lobby_index -> (rounds recorded, newest round time)``; Discord's "game N" counts these."""
        rows = await session.execute(
            sa.select(
                models.CustomGameRound.lobby_index,
                sa.func.count().label("rounds"),
                sa.func.max(models.Encounter.created_at).label("last_at"),
            )
            .join(models.Encounter, models.Encounter.id == models.CustomGameRound.encounter_id)
            .where(models.Encounter.custom_game_id == custom_game_id)
            .group_by(models.CustomGameRound.lobby_index)
        )
        return {row.lobby_index: (row.rounds, row.last_at) for row in rows}

    async def lobby_activity_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, dict[int, tuple[int, datetime]]]:
        """``custom_game_id -> {lobby_index: (rounds recorded, newest round time)}`` for a whole mix list in one
        query: :meth:`activity_for_lobbies` across many mixes. A mix or lobby with no rounds is absent."""
        if not custom_game_ids:
            return {}
        rows = await session.execute(
            sa.select(
                models.Encounter.custom_game_id,
                models.CustomGameRound.lobby_index,
                sa.func.count().label("rounds"),
                sa.func.max(models.Encounter.created_at).label("last_at"),
            )
            .join(models.CustomGameRound, models.CustomGameRound.encounter_id == models.Encounter.id)
            .where(models.Encounter.custom_game_id.in_(custom_game_ids))
            .group_by(models.Encounter.custom_game_id, models.CustomGameRound.lobby_index)
        )
        grouped: dict[int, dict[int, tuple[int, datetime]]] = {}
        for row in rows:
            grouped.setdefault(row.custom_game_id, {})[row.lobby_index] = (row.rounds, row.last_at)
        return grouped

    async def player_counts_for_games(self, session: AsyncSession, custom_game_ids: Sequence[int]) -> dict[int, int]:
        """``custom_game_id -> distinct members seated across its rounds``; a mix with none is absent.

        Seats only: a member who was busy next door the whole night sat in no round of this mix."""
        if not custom_game_ids:
            return {}
        seat = models.EncounterTeamMember
        rows = await session.execute(
            sa.select(
                models.Encounter.custom_game_id,
                sa.func.count(sa.distinct(seat.workspace_member_id)).label("players"),
            )
            .join(models.CustomGameRound, models.CustomGameRound.encounter_id == models.Encounter.id)
            .join(seat, seat.encounter_id == models.Encounter.id)
            .where(models.Encounter.custom_game_id.in_(custom_game_ids))
            .group_by(models.Encounter.custom_game_id)
        )
        return {row.custom_game_id: row.players for row in rows}

    async def maps_for_games(
        self, session: AsyncSession, custom_game_ids: Sequence[int]
    ) -> dict[int, list[tuple[str, str | None]]]:
        """``custom_game_id -> [(map name, image path), ...]``: every distinct map its rounds were played on,
        most recently recorded first. A mix with no mapped round is absent."""
        if not custom_game_ids:
            return {}
        game_map = models.CatalogEntity
        last_recorded = sa.func.max(models.Encounter.confirmed_at).label("last_recorded")
        rows = await session.execute(
            sa.select(models.Encounter.custom_game_id, game_map.name, game_map.image_path, last_recorded)
            .join(models.CustomGameRound, models.CustomGameRound.encounter_id == models.Encounter.id)
            .join(models.EncounterGame, models.EncounterGame.encounter_id == models.Encounter.id)
            .join(game_map, game_map.id == models.EncounterGame.map_id)
            .where(models.Encounter.custom_game_id.in_(custom_game_ids))
            .group_by(models.Encounter.custom_game_id, game_map.id, game_map.name, game_map.image_path)
            .order_by(models.Encounter.custom_game_id, last_recorded.desc(), sa.func.max(models.Encounter.id).desc())
        )
        grouped: dict[int, list[tuple[str, str | None]]] = {}
        for row in rows:
            grouped.setdefault(row.custom_game_id, []).append((row.name, row.image_path))
        return grouped

    @staticmethod
    def seat_rows_select(workspace_id: int) -> sa.Select:
        """The one seat join (unexecuted): a row per seat of this workspace's rounds, with its rated leaf's code and id, its frozen
        rank delta and both sides' scores -- a round stores two scores and no winner flag. ``created_at`` is when the
        match started (it was played then), ``recorded_at`` when its result landed (the order rounds read in). A mix
        seat has at most one rated-dimension leaf, so the outer join never fans out. ``seats()`` executes it; the rank
        overview composes it as a subquery."""
        seat = models.EncounterTeamMember
        side = models.EncounterTeam
        other = aliased(models.EncounterTeam)
        role = models.EncounterTeamMemberRole
        member = models.CustomGameRoundMember
        return (
            sa.select(
                seat.id.label("seat_id"),
                models.Encounter.id.label("encounter_id"),
                models.Encounter.created_at,
                models.Encounter.confirmed_at.label("recorded_at"),
                models.Encounter.custom_game_id,
                models.CustomGameRound.lobby_index,
                models.CustomGameRound.points_per_win_applied,
                side.slot,
                seat.workspace_member_id,
                role.role,
                role.role_id,
                seat.rank,
                member.rank_delta_applied,
                side.score.label("own_score"),
                other.score.label("other_score"),
            )
            .select_from(seat)
            .join(side, side.id == seat.encounter_team_id)
            .join(models.Encounter, models.Encounter.id == seat.encounter_id)
            .join(models.CustomGameRound, models.CustomGameRound.encounter_id == models.Encounter.id)
            .join(other, sa.and_(other.encounter_id == models.Encounter.id, other.id != side.id))
            .outerjoin(
                role,
                sa.and_(
                    role.team_member_id == seat.id,
                    role.dimension_id.in_(
                        sa.select(models.RoleDimension.id).where(
                            models.RoleDimension.discipline == models.Encounter.discipline,
                            models.RoleDimension.rated.is_(True),
                        )
                    ),
                ),
            )
            .outerjoin(
                member,
                sa.and_(
                    member.encounter_id == models.Encounter.id, member.workspace_member_id == seat.workspace_member_id
                ),
            )
            .where(models.Encounter.workspace_id == workspace_id)
        )

    async def seats(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        encounter_id: int | None = None,
        discipline: str | None = None,
        since: datetime | None = None,
    ) -> Sequence[sa.Row]:
        """``seat_rows_select`` of this workspace, oldest recorded round first: the leaderboard, the ranker replay and
        undo all read this. ``since`` windows by when the match was played (``created_at``)."""
        stmt = self.seat_rows_select(workspace_id).order_by(
            models.Encounter.confirmed_at, models.Encounter.id, models.EncounterTeamMember.id
        )
        if encounter_id is not None:
            stmt = stmt.where(models.Encounter.id == encounter_id)
        if discipline is not None:
            stmt = stmt.where(models.Encounter.discipline == discipline)
        if since is not None:
            stmt = stmt.where(models.Encounter.created_at >= since)
        return (await session.execute(stmt)).all()

    async def hero_bans(self, session: AsyncSession, encounter_ids: Sequence[int]) -> dict[int, list[dict[str, int]]]:
        """``encounter_id -> [{slot, item_id}, ...]``: each round's hero bans in the order they were made (spec §8.4)
        -- the room's applied-action order, not the candidates' insertion order. No ids, no query."""
        if not encounter_ids:
            return {}
        entry = models.PickBanEntry
        rows = await session.execute(
            sa.select(entry.encounter_id, models.EncounterTeam.slot, entry.item_id)
            .join(models.PickBanSession, models.PickBanSession.id == entry.session_id)
            .join(models.EncounterTeam, models.EncounterTeam.id == entry.picked_by_team_id)
            .where(
                entry.encounter_id.in_(encounter_ids),
                models.PickBanSession.kind == PickBanKind.HERO,
                entry.status == MapPoolEntryStatus.BANNED,
            )
            .order_by(entry.encounter_id, entry.action_index, entry.id)
        )
        bans: dict[int, list[dict[str, int]]] = {}
        for row in rows:
            bans.setdefault(row.encounter_id, []).append({"slot": row.slot, "item_id": row.item_id})
        return bans

    async def hero_picks(
        self, session: AsyncSession, encounter_ids: Sequence[int]
    ) -> dict[int, list[dict[str, int | str]]]:
        """``encounter_id -> [{slot, member_id, name, item_id}, ...]``: whose hero each pick of a round was (spec §11.6
        R4-11), in pick order. ``member_id`` is the workspace member; the name is the round's snapshot. A team pick
        nobody was assigned is not listed."""
        if not encounter_ids:
            return {}
        entry = models.PickBanEntry
        seat = models.EncounterTeamMember
        rows = await session.execute(
            sa.select(
                entry.encounter_id,
                models.EncounterTeam.slot,
                seat.workspace_member_id,
                seat.display_name_snapshot,
                entry.item_id,
            )
            .join(models.PickBanSession, models.PickBanSession.id == entry.session_id)
            .join(seat, seat.id == entry.picked_for_member_id)
            .join(models.EncounterTeam, models.EncounterTeam.id == seat.encounter_team_id)
            .where(
                entry.encounter_id.in_(encounter_ids),
                models.PickBanSession.kind == PickBanKind.HERO,
                entry.status == MapPoolEntryStatus.PICKED,
            )
            .order_by(entry.encounter_id, entry.action_index, entry.id)
        )
        picks: dict[int, list[dict[str, int | str]]] = {}
        for row in rows:
            picks.setdefault(row.encounter_id, []).append(
                {
                    "slot": row.slot,
                    "member_id": row.workspace_member_id,
                    "name": row.display_name_snapshot,
                    "item_id": row.item_id,
                }
            )
        return picks

    async def match_logs(
        self, session: AsyncSession, encounter_ids: Sequence[int]
    ) -> dict[int, tuple[int | None, str | None]]:
        """``encounter_id -> (stats_match_id, log_state)`` for every id, in ONE read. The match is the newest
        ``stats.match`` bound to the encounter. Only while there is none does the newest ``stats.ingest_job`` hinted at
        it speak: pending/processing -> ``"processing"``, failed/awaiting_link -> ``"failed"``, else ``None``. No ids,
        no query."""
        if not encounter_ids:
            return {}
        match_id = (
            sa.select(sa.func.max(models.StatsMatch.id))
            .where(models.StatsMatch.encounter_id == models.Encounter.id)
            .scalar_subquery()
        )
        job_status = (
            sa.select(models.IngestJob.status)
            .where(models.IngestJob.hint_encounter_id == models.Encounter.id)
            .order_by(models.IngestJob.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = await session.execute(
            sa.select(models.Encounter.id, match_id, job_status).where(models.Encounter.id.in_(encounter_ids))
        )
        return {
            encounter_id: (matched, None if matched is not None else _LOG_STATE.get(status))
            for encounter_id, matched, status in rows
        }

    async def delete_round(self, session: AsyncSession, encounter_id: int) -> None:
        """Undo, or Cancel match: the encounter goes, and seats, game, journal and ``mix.round*`` cascade with it."""
        await session.execute(sa.delete(models.Encounter).where(models.Encounter.id == encounter_id))
