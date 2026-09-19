from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.repository.base import BaseRepository


class DivisionGridRepository(BaseRepository[models.DivisionGrid]):
    def __init__(self) -> None:
        super().__init__(models.DivisionGrid)

    async def list_workspace_grids(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.DivisionGrid]:
        result = await session.execute(
            sa.select(models.DivisionGrid)
            .options(selectinload(models.DivisionGrid.versions))
            .where(models.DivisionGrid.workspace_id == workspace_id)
            .order_by(models.DivisionGrid.id.asc())
        )
        return result.unique().scalars().all()


class AchievementRuleRepository(BaseRepository[models.AchievementRule]):
    def __init__(self) -> None:
        super().__init__(models.AchievementRule)

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.AchievementRule]:
        result = await session.execute(
            sa.select(models.AchievementRule)
            .where(models.AchievementRule.workspace_id == workspace_id)
            .order_by(models.AchievementRule.id.asc())
        )
        return result.scalars().all()


class AchievementOverrideRepository(BaseRepository[models.AchievementOverride]):
    def __init__(self) -> None:
        super().__init__(models.AchievementOverride)


class AchievementEvaluationResultRepository(BaseRepository[models.AchievementEvaluationResult]):
    """``achievements.evaluation_result`` — reconcile writes for one rule's diff.

    ``bulk_upsert_ignore_conflicts``'s conflict target mirrors migration
    ``achenc01``'s functional unique index verbatim (``COALESCE(x, 0)`` on the
    nullable dedup columns) — Postgres only matches an ``ON CONFLICT`` target
    against an index whose expressions are syntactically identical, so this
    tuple must never be simplified to a plain ``0`` literal or dropped.
    """

    _DEDUP_INDEX_ELEMENTS = (
        models.AchievementEvaluationResult.achievement_rule_id,
        models.AchievementEvaluationResult.workspace_member_id,
        sa.func.coalesce(models.AchievementEvaluationResult.tournament_id, sa.literal_column("0")),
        sa.func.coalesce(models.AchievementEvaluationResult.encounter_id, sa.literal_column("0")),
        sa.func.coalesce(models.AchievementEvaluationResult.match_id, sa.literal_column("0")),
    )

    def __init__(self) -> None:
        super().__init__(models.AchievementEvaluationResult)

    async def bulk_delete_by_ids(self, session: AsyncSession, ids: Sequence[int]) -> None:
        if not ids:
            return
        await session.execute(sa.delete(models.AchievementEvaluationResult).where(self.model.id.in_(ids)))

    async def delete_for_rules(self, session: AsyncSession, rule_ids: sa.Select) -> int:
        """Delete every result for the rules selected by ``rule_ids`` (a subquery-shaped
        ``sa.Select``, e.g. ``sa.select(AchievementRule.id).where(...)``). Returns the row count."""
        result = await session.execute(sa.delete(self.model).where(self.model.achievement_rule_id.in_(rule_ids)))
        return result.rowcount or 0

    async def bulk_upsert_ignore_conflicts(self, session: AsyncSession, values: list[dict]) -> None:
        if not values:
            return
        await session.execute(
            pg_insert(self.model).values(values).on_conflict_do_nothing(index_elements=self._DEDUP_INDEX_ELEMENTS)
        )


class EvaluationRunRepository(BaseRepository[models.EvaluationRun]):
    def __init__(self) -> None:
        super().__init__(models.EvaluationRun)


class DiscordChannelRepository(BaseRepository[models.TournamentDiscordChannel]):
    def __init__(self) -> None:
        super().__init__(models.TournamentDiscordChannel)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.TournamentDiscordChannel | None:
        return await self.get_by(session, tournament_id=tournament_id)

    async def list_channel_ids_for_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> Sequence[int]:
        """Active channel ids configured for a tournament (0 or 1: unique per tournament)."""
        result = await session.execute(
            sa.select(models.TournamentDiscordChannel.channel_id).where(
                models.TournamentDiscordChannel.tournament_id == tournament_id,
                models.TournamentDiscordChannel.is_active,
            )
        )
        return result.scalars().all()

    async def list_active_with_tournament(
        self,
        session: AsyncSession,
        *,
        finished_cutoff: datetime,
    ) -> Sequence[tuple[models.TournamentDiscordChannel, models.Tournament]]:
        """Channels to keep monitoring: tournament still running, or finished after ``finished_cutoff``.

        Backs the bot's channel-registry reload — a tournament stays watched for
        a short grace period after it finishes so late log uploads still land.
        """
        result = await session.execute(
            sa.select(models.TournamentDiscordChannel, models.Tournament)
            .join(models.Tournament, models.TournamentDiscordChannel.tournament_id == models.Tournament.id)
            .where(
                models.TournamentDiscordChannel.is_active,
                (
                    (~models.Tournament.is_finished)
                    | (
                        models.Tournament.is_finished
                        & (models.Tournament.end_date.is_not(None))
                        & (models.Tournament.end_date >= finished_cutoff)
                    )
                ),
            )
        )
        return list(result.all())


def stalled_conditions(
    *,
    now: datetime,
    pending_after_seconds: int,
    processing_after_seconds: int,
) -> sa.ColumnElement[bool]:
    """WHERE term selecting records no live queue message can still be driving.

    ``updated_at`` is null until a row is first updated, so last-touch falls back
    to ``created_at``. The pending window must exceed the queue TTL: inside it a
    message may still be waiting for a busy consumer, and requeueing then would
    parse the same log twice concurrently.

    Moved verbatim from ``src/services/match_logs/reaper.py`` — that module
    still exposes it (``reaper.stalled_conditions``, re-exported from here) since
    a test constructs it directly to pin the exact WHERE shape.
    """
    record = models.LogProcessingRecord
    last_touch = sa.func.coalesce(record.updated_at, record.created_at)
    return sa.or_(
        sa.and_(
            record.status == models.LogProcessingStatus.pending,
            last_touch < now - timedelta(seconds=pending_after_seconds),
        ),
        sa.and_(
            record.status == models.LogProcessingStatus.processing,
            sa.func.coalesce(record.started_at, last_touch) < now - timedelta(seconds=processing_after_seconds),
        ),
    )


class LogProcessingRepository(BaseRepository[models.LogProcessingRecord]):
    def __init__(self) -> None:
        super().__init__(models.LogProcessingRecord)

    async def exists_done(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        filename: str,
    ) -> bool:
        """Whether this exact (tournament, filename) already finished processing.

        Used to skip re-uploading logs already seen on a channel-history rescan
        (bot restart, newly-added channel).
        """
        result = await session.execute(
            sa.select(models.LogProcessingRecord.id)
            .where(
                models.LogProcessingRecord.tournament_id == tournament_id,
                models.LogProcessingRecord.filename == filename,
                models.LogProcessingRecord.status == models.LogProcessingStatus.done,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_latest_error_message(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        filename: str,
    ) -> str | None:
        result = await session.execute(
            sa.select(models.LogProcessingRecord.error_message)
            .where(
                models.LogProcessingRecord.tournament_id == tournament_id,
                models.LogProcessingRecord.filename == filename,
            )
            .order_by(models.LogProcessingRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_reusable(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        filename: str,
    ) -> models.LogProcessingRecord | None:
        """A pending/failed record for (tournament_id, filename) to refresh on a
        re-upload, rather than forking a duplicate row."""
        result = await session.execute(
            sa.select(models.LogProcessingRecord)
            .where(
                models.LogProcessingRecord.tournament_id == tournament_id,
                models.LogProcessingRecord.filename == filename,
                models.LogProcessingRecord.status.in_(
                    [models.LogProcessingStatus.pending, models.LogProcessingStatus.failed]
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_latest(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        filename: str,
    ) -> models.LogProcessingRecord | None:
        """The most recently created record for (tournament_id, filename), any status."""
        result = await session.execute(
            sa.select(models.LogProcessingRecord)
            .where(
                models.LogProcessingRecord.tournament_id == tournament_id,
                models.LogProcessingRecord.filename == filename,
            )
            .order_by(models.LogProcessingRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_latest_incomplete(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        filename: str,
        statuses: Sequence[models.LogProcessingStatus],
    ) -> models.LogProcessingRecord | None:
        """The most recent record for (tournament_id, filename) still in one of
        ``statuses`` — callers pick which non-terminal states count as "incomplete"
        for their purpose (duplicate finalization vs. an unstarted-log failure)."""
        result = await session.execute(
            sa.select(models.LogProcessingRecord)
            .where(
                models.LogProcessingRecord.tournament_id == tournament_id,
                models.LogProcessingRecord.filename == filename,
                models.LogProcessingRecord.status.in_(statuses),
            )
            .order_by(models.LogProcessingRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def claim_stalled(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        pending_after_seconds: int,
        processing_after_seconds: int,
        limit: int,
    ) -> Sequence[models.LogProcessingRecord]:
        """``SELECT ... FOR UPDATE SKIP LOCKED`` — moved verbatim from
        ``reaper.py``'s ``_claim_stalled``. Locks and returns the stalled rows;
        the caller decides requeue vs. exhausted per row and owns the commit (no
        write happens here, so this is safe to call from a read-locking method
        despite the write-methods-flush-only convention).
        """
        result = await session.execute(
            sa.select(models.LogProcessingRecord)
            .where(
                stalled_conditions(
                    now=now,
                    pending_after_seconds=pending_after_seconds,
                    processing_after_seconds=processing_after_seconds,
                )
            )
            .order_by(models.LogProcessingRecord.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.scalars().all()


class ChallongeMappingRepository:
    sources = BaseRepository(models.ChallongeSource)
    participants = BaseRepository(models.ChallongeParticipantMapping)
    matches = BaseRepository(models.ChallongeMatchMapping)
    logs = BaseRepository(models.ChallongeSyncLog)
