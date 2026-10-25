"""Data access for stream chronology: ``stream.session`` and the match timings its chapters are cut from.

``StreamSessionRepository`` is the only writer of ``stream.session`` (owned by stream-service): the poll tick
upserts what it saw live and the VOD sync stamps what Helix answered. ``StreamChronologyRepository`` is read-only
over tables other services own (``tournament.*``, ``encounter.*``, ``stats.*``, ``catalog.*``).

Both key everything on ids so a read assembles a whole tournament in a fixed number of statements, never one per
stream or per encounter.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models

__all__ = (
    "ChronologyEncounterRow",
    "ChronologyMapRow",
    "EncounterOwnerRow",
    "PendingVodRow",
    "ResolvedVodRow",
    "StreamChronologyRepository",
    "StreamSessionObservation",
    "StreamSessionRepository",
    "StreamVodSessionRow",
)


class StreamSessionObservation(NamedTuple):
    """One live POV channel as one tournament's poll tick saw it."""

    tournament_id: int
    user_id: int
    channel: str
    broadcaster_id: str
    stream_id: str
    started_at: datetime


class PendingVodRow(NamedTuple):
    id: int
    broadcaster_id: str
    stream_id: str


class ResolvedVodRow(NamedTuple):
    id: int
    vod_id: str


class StreamVodSessionRow(NamedTuple):
    """A session with an alive VOD, as the public chronology reads it."""

    id: int
    user_id: int
    channel: str
    vod_id: str
    started_at: datetime
    last_seen_at: datetime


class EncounterOwnerRow(NamedTuple):
    """``tournament_id`` is ``None`` for a mix's encounter, which no tournament owns."""

    tournament_id: int | None


class ChronologyEncounterRow(NamedTuple):
    """One active seat of a tournament team in an encounter, with the series timing."""

    team_id: int
    encounter_id: int
    name: str
    started_at: datetime | None
    ended_at: datetime | None


class ChronologyMapRow(NamedTuple):
    """One logged map with a trustworthy start time."""

    encounter_id: int
    played_at: datetime
    duration_s: float | None
    map_position: int | None
    map_name: str


class StreamSessionRepository:
    """Reads and writes of ``stream.session``. Not a ``BaseRepository``: every write is set-based."""

    model = models.StreamSession

    async def record_observed(
        self, session: AsyncSession, observations: Sequence[StreamSessionObservation], *, seen_at: datetime
    ) -> None:
        """Upsert one row per ``(tournament_id, stream_id)``: a new broadcast inserts, a known one moves its
        ``last_seen_at`` (and follows a channel rename)."""
        if not observations:
            return
        stmt = insert(self.model).values(
            [{**observation._asdict(), "last_seen_at": seen_at} for observation in observations]
        )
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_stream_session_tournament_stream",
                set_={
                    "last_seen_at": stmt.excluded.last_seen_at,
                    "channel": stmt.excluded.channel,
                    "updated_at": sa.func.now(),
                },
            )
        )

    async def list_unresolved(
        self, session: AsyncSession, *, seen_since: datetime, checked_before: datetime
    ) -> Sequence[PendingVodRow]:
        """Sessions still waiting for a VOD id: seen live since ``seen_since`` and not attempted since
        ``checked_before``. Never-attempted rows first, then the longest-waiting, so a capped caller is fair."""
        row = self.model
        stmt = (
            sa.select(row.id, row.broadcaster_id, row.stream_id)
            .where(
                row.vod_id.is_(None),
                row.vod_gone_at.is_(None),
                row.last_seen_at >= seen_since,
                sa.or_(row.vod_checked_at.is_(None), row.vod_checked_at < checked_before),
            )
            .order_by(row.vod_checked_at.asc().nulls_first(), row.id)
        )
        return [PendingVodRow(*values) for values in (await session.execute(stmt)).all()]

    async def mark_vod_attempts(
        self, session: AsyncSession, *, attempted: Collection[int], resolved: Mapping[int, str], checked_at: datetime
    ) -> None:
        """Stamp ``vod_checked_at`` on every attempted row and set ``vod_id`` on those Helix matched (a subset of
        ``attempted``), in one statement."""
        if not attempted:
            return
        row = self.model
        vod_id = sa.case(dict(resolved), value=row.id, else_=row.vod_id) if resolved else row.vod_id
        await session.execute(
            sa.update(row).where(row.id.in_(list(attempted))).values(vod_checked_at=checked_at, vod_id=vod_id)
        )

    async def list_due_recheck(
        self, session: AsyncSession, *, checked_before: datetime, limit: int
    ) -> Sequence[ResolvedVodRow]:
        """Resolved, alive VODs not checked since ``checked_before``, stalest first."""
        row = self.model
        stmt = (
            sa.select(row.id, row.vod_id)
            .where(
                row.vod_id.isnot(None),
                row.vod_gone_at.is_(None),
                sa.or_(row.vod_checked_at.is_(None), row.vod_checked_at < checked_before),
            )
            .order_by(row.vod_checked_at.asc().nulls_first(), row.id)
            .limit(limit)
        )
        return [ResolvedVodRow(*values) for values in (await session.execute(stmt)).all()]

    async def mark_rechecked(
        self, session: AsyncSession, *, alive: Collection[int], gone: Collection[int], checked_at: datetime
    ) -> None:
        row = self.model
        if alive:
            await session.execute(sa.update(row).where(row.id.in_(list(alive))).values(vod_checked_at=checked_at))
        if gone:
            await session.execute(
                sa.update(row).where(row.id.in_(list(gone))).values(vod_checked_at=checked_at, vod_gone_at=checked_at)
            )

    async def list_alive_vods(self, session: AsyncSession, tournament_id: int) -> Sequence[StreamVodSessionRow]:
        """Every session of ``tournament_id`` with a resolved VOD that has not vanished, newest first."""
        row = self.model
        stmt = (
            sa.select(row.id, row.user_id, row.channel, row.vod_id, row.started_at, row.last_seen_at)
            .where(
                row.tournament_id == tournament_id,
                row.vod_id.isnot(None),
                row.vod_gone_at.is_(None),
            )
            .order_by(row.started_at.desc(), row.id)
        )
        return [StreamVodSessionRow(*values) for values in (await session.execute(stmt)).all()]


class StreamChronologyRepository:
    """Read-only lookups the chronology needs from tables other services own."""

    async def encounter_owner(self, session: AsyncSession, encounter_id: int) -> EncounterOwnerRow | None:
        """``None`` when no such encounter exists."""
        found = (
            await session.execute(sa.select(models.Encounter.tournament_id).where(models.Encounter.id == encounter_id))
        ).one_or_none()
        return None if found is None else EncounterOwnerRow(found.tournament_id)

    async def pov_stream_delay_s(self, session: AsyncSession, tournament_id: int) -> int:
        delay = await session.scalar(
            sa.select(models.Tournament.pov_stream_delay_s).where(models.Tournament.id == tournament_id)
        )
        return int(delay or 0)

    async def team_encounters(
        self,
        session: AsyncSession,
        tournament_id: int,
        team_ids: Collection[int],
        *,
        encounter_id: int | None = None,
    ) -> Sequence[ChronologyEncounterRow]:
        """Every encounter of ``tournament_id`` in which one of ``team_ids`` holds an ACTIVE seat (a replaced
        seat is history, not participation). ``encounter_id`` narrows it to one encounter."""
        if not team_ids:
            return []
        encounter, seat = models.Encounter, models.EncounterTeam
        stmt = (
            sa.select(seat.team_id, encounter.id, encounter.name, encounter.started_at, encounter.ended_at)
            .select_from(seat)
            .join(encounter, encounter.id == seat.encounter_id)
            .where(
                encounter.tournament_id == tournament_id,
                seat.team_id.in_(list(team_ids)),
                seat.active.is_(True),
            )
        )
        if encounter_id is not None:
            stmt = stmt.where(encounter.id == encounter_id)
        return [ChronologyEncounterRow(*values) for values in (await session.execute(stmt)).all()]

    async def logged_maps(self, session: AsyncSession, encounter_ids: Collection[int]) -> Sequence[ChronologyMapRow]:
        """Logged maps of ``encounter_ids`` whose ``played_at`` is a real start time.

        A log time is not one when it is NULL, or when it equals its ingest job's ``created_at``: the Overwatch
        decoder falls back to the job's creation time when the log carries no tz-aware timestamp
        (``shared/disciplines/overwatch/ingest.py``). ``IS DISTINCT FROM`` keeps a match whose job was deleted.
        """
        if not encounter_ids:
            return []
        match, game, entity, job = models.StatsMatch, models.EncounterGame, models.CatalogEntity, models.IngestJob
        stmt = (
            sa.select(match.encounter_id, match.played_at, match.duration_s, game.position, entity.name)
            .select_from(match)
            .join(entity, entity.id == match.map_entity_id)
            .outerjoin(game, game.id == match.encounter_game_id)
            .outerjoin(job, job.id == match.ingest_job_id)
            .where(
                match.encounter_id.in_(list(encounter_ids)),
                match.played_at.isnot(None),
                match.played_at.is_distinct_from(job.created_at),
            )
        )
        return [ChronologyMapRow(*values) for values in (await session.execute(stmt)).all()]
