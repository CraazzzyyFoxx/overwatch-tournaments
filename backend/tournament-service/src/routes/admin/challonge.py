from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import auth, db
from src.services.challonge import service as challonge_service
from src.services.challonge import sync as challonge_sync

router = APIRouter(
    prefix="/challonge",
    tags=["admin", "challonge"],
)


@router.get(path="/tournament")
async def get_tournament_from_challonge(
    tournament_slug: str,
    _user=Depends(auth.require_permission("challonge", "read")),
):
    return await challonge_service.fetch_tournament(tournament_slug)


@router.get(path="/participants")
async def get_participants_from_challonge(
    tournament_id: int,
    _user=Depends(auth.require_permission("challonge", "read")),
):
    return await challonge_service.fetch_participants(tournament_id)


@router.get(path="/matches")
async def get_matches_from_challonge(
    tournament_id: int,
    _user=Depends(auth.require_permission("challonge", "read")),
):
    return await challonge_service.fetch_matches(tournament_id)


# ── Bidirectional sync ───────────────────────────────────────────────────────


@router.post(path="/sync/import/{tournament_id}")
async def import_from_challonge(
    tournament_id: int,
    dry_run: bool = False,
    session: AsyncSession = Depends(db.get_async_session),
    _user=Depends(auth.require_tournament_permission("challonge", "sync")),
):
    """Full import: pull matches from Challonge and update local encounters."""
    return await challonge_sync.import_tournament(session, tournament_id, dry_run=dry_run)


@router.post(path="/sync/export/{tournament_id}")
async def export_to_challonge(
    tournament_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user=Depends(auth.require_tournament_permission("challonge", "sync")),
):
    """Full export: push all completed encounter results to Challonge."""
    return await challonge_sync.export_tournament(session, tournament_id)


@router.post(path="/sync/push-result/{encounter_id}")
async def push_single_result(
    encounter_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    _user=Depends(auth.require_encounter_permission("challonge", "sync")),
):
    """Push a single encounter result to Challonge."""
    await challonge_sync.auto_push_on_confirm(session, encounter_id)
    return {"status": "ok"}


@router.get(path="/sync/log/{tournament_id}")
async def get_sync_log(
    tournament_id: int,
    limit: int = 50,
    session: AsyncSession = Depends(db.get_async_session),
    _user=Depends(auth.require_tournament_permission("challonge", "read")),
):
    """View sync history for a tournament."""
    logs = await challonge_sync.get_sync_log(session, tournament_id, limit)
    return [
        {
            "id": log.id,
            "created_at": log.created_at,
            "source_id": log.source_id,
            "direction": log.direction,
            "operation": log.operation,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "challonge_id": log.challonge_id,
            "status": log.status,
            "conflict_type": log.conflict_type,
            "before_json": log.before_json,
            "after_json": log.after_json,
            "error_message": log.error_message,
        }
        for log in logs
    ]
