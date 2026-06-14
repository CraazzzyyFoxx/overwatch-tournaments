from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
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


class DiscordChannelRepository(BaseRepository[models.TournamentDiscordChannel]):
    def __init__(self) -> None:
        super().__init__(models.TournamentDiscordChannel)

    async def get_by_tournament(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> models.TournamentDiscordChannel | None:
        return await self.get_by(session, tournament_id=tournament_id)


class LogProcessingRepository(BaseRepository[models.LogProcessingRecord]):
    def __init__(self) -> None:
        super().__init__(models.LogProcessingRecord)


class ChallongeMappingRepository:
    sources = BaseRepository(models.ChallongeSource)
    participants = BaseRepository(models.ChallongeParticipantMapping)
    matches = BaseRepository(models.ChallongeMatchMapping)
    logs = BaseRepository(models.ChallongeSyncLog)


class AnalyticsStateRepository:
    algorithms = BaseRepository(models.AnalyticsAlgorithm)
    jobs = BaseRepository(models.AnalyticsJob)
    model_artifacts = BaseRepository(models.MLModelArtifact)
    feature_store = BaseRepository(models.MLFeatureStore)
    performance = BaseRepository(models.AnalyticsPerformance)
    standings_distribution = BaseRepository(models.AnalyticsStandingsDistribution)
    match_quality = BaseRepository(models.AnalyticsMatchQuality)
    player_anomaly = BaseRepository(models.AnalyticsPlayerAnomaly)
    explanations = BaseRepository(models.AnalyticsExplanation)
