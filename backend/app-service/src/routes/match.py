"""Read-only match-log download proxy.

Match write/flow routes live in tournament-service; this endpoint only streams a
previously-uploaded log file from S3. app-service owns the S3 client (see
assets/workspace routes) and can read the shared Match/Encounter models, so the
read-only log proxy lives here under ``/api/v1/core/matches/{id}/log`` (distinct
from tournament-service's bare ``/api/v1/matches`` namespace).
"""

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from shared.clients.s3 import S3Client
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import db

router = APIRouter(prefix="/matches", tags=["matches"])


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3


@router.get("/{match_id}/log")
async def download_match_log(
    match_id: int,
    session: AsyncSession = Depends(db.get_async_session),
    s3: S3Client = Depends(get_s3),
) -> Response:
    """Stream a match's parsed log file from S3 as a download.

    Logs are stored by parser-service under ``logs/{tournament_id}/{log_name}``.
    """
    row = (
        await session.execute(
            sa.select(models.Match.log_name, models.Encounter.tournament_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .where(models.Match.id == match_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match not found")

    log_name, tournament_id = row
    # `log_name` is a bare filename; defend against any path traversal regardless.
    filename = (log_name or "").rsplit("/", 1)[-1]
    if not filename or ".." in filename:
        raise HTTPException(status_code=404, detail="No log available for this match")

    data = await s3.get_object(f"logs/{tournament_id}/{filename}")
    if data is None:
        raise HTTPException(status_code=404, detail="Log file not found")

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
