from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends

from src import schemas
from src.core import db
from src.services.overwatch_rank import read_service

router = APIRouter(tags=["Rank History"])

Granularity = Literal["raw", "daily"]


@router.get("/users/{user_id}/rank-history", response_model=schemas.RankHistoryResponse)
async def get_user_rank_history(
    user_id: int,
    platform: str | None = None,
    role: str | None = None,
    battle_tag_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    granularity: Granularity = "raw",
    session=Depends(db.get_async_session),
) -> schemas.RankHistoryResponse:
    """Rank history for a user across all their battle.net accounts."""
    series = await read_service.get_rank_series(
        session,
        user_id=user_id,
        battle_tag_id=battle_tag_id,
        platform=platform,
        role=role,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
    )
    return schemas.RankHistoryResponse(
        user_id=user_id, series=series, generated_at=datetime.now(UTC)
    )


@router.get("/battle-tags/{battle_tag_id}/rank-history", response_model=schemas.RankHistoryResponse)
async def get_battle_tag_rank_history(
    battle_tag_id: int,
    platform: str | None = None,
    role: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    granularity: Granularity = "raw",
    session=Depends(db.get_async_session),
) -> schemas.RankHistoryResponse:
    """Rank history for a single battle.net account."""
    series = await read_service.get_rank_series(
        session,
        battle_tag_id=battle_tag_id,
        platform=platform,
        role=role,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
    )
    return schemas.RankHistoryResponse(
        user_id=None, series=series, generated_at=datetime.now(UTC)
    )


@router.get("/users/{user_id}/current-ranks", response_model=schemas.CurrentRanksResponse)
async def get_user_current_ranks(
    user_id: int,
    platform: str | None = None,
    session=Depends(db.get_async_session),
) -> schemas.CurrentRanksResponse:
    """Latest known rank per (battle.net, role, platform) for a user."""
    ranks = await read_service.get_current_ranks(
        session, user_id=user_id, platform=platform
    )
    return schemas.CurrentRanksResponse(
        user_id=user_id, ranks=ranks, generated_at=datetime.now(UTC)
    )
