from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from src import schemas
from src.core import db
from src.services.overwatch_rank import read_service

router = APIRouter(tags=["Rank History"])

Granularity = Literal["raw", "daily", "hourly"]


def _resolve_date_range(
    granularity: Granularity,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime, datetime]:
    """Apply per-granularity defaults and enforce max range for hourly/raw."""
    now = datetime.now(tz=UTC)
    resolved_to = date_to or now
    default_days = 7 if granularity == "daily" else 3
    max_days = None if granularity == "daily" else 7
    resolved_from = date_from or (resolved_to - timedelta(days=default_days))
    if max_days is not None and (resolved_to - resolved_from).total_seconds() > max_days * 86400:
        raise HTTPException(
            status_code=422,
            detail=f"Date range for '{granularity}' granularity must not exceed {max_days} days.",
        )
    return resolved_from, resolved_to


@router.get("/users/{user_id}/rank-history", response_model=schemas.RankHistoryResponse)
async def get_user_rank_history(
    user_id: int,
    platform: str | None = None,
    role: str | None = None,
    battle_tag_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    granularity: Granularity = "daily",
    session=Depends(db.get_async_session),
) -> schemas.RankHistoryResponse:
    """Rank history for a user across all their battle.net accounts."""
    date_from, date_to = _resolve_date_range(granularity, date_from, date_to)
    service_granularity = "daily" if granularity == "daily" else "raw"
    series = await read_service.get_rank_series(
        session,
        user_id=user_id,
        battle_tag_id=battle_tag_id,
        platform=platform,
        role=role,
        date_from=date_from,
        date_to=date_to,
        granularity=service_granularity,
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
    granularity: Granularity = "daily",
    session=Depends(db.get_async_session),
) -> schemas.RankHistoryResponse:
    """Rank history for a single battle.net account."""
    date_from, date_to = _resolve_date_range(granularity, date_from, date_to)
    service_granularity = "daily" if granularity == "daily" else "raw"
    series = await read_service.get_rank_series(
        session,
        battle_tag_id=battle_tag_id,
        platform=platform,
        role=role,
        date_from=date_from,
        date_to=date_to,
        granularity=service_granularity,
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
