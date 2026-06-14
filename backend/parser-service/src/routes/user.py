import re

import httpx
from fastapi import APIRouter, Depends, UploadFile

from src.core import db, enums, auth, errors

from src.services.user import flows as user_flows

router = APIRouter(
    prefix="/user",
    tags=[enums.RouteTag.USER],
    dependencies=[Depends(auth.require_role("admin"))],
)

_SHEETS_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
_GID_RE = re.compile(r"[?&#]gid=(\d+)")


def _sheets_to_csv_url(url: str) -> str:
    """Convert a Google Sheets URL to its CSV export URL."""
    match = _SHEETS_ID_RE.search(url)
    if not match:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="invalid_url", msg="Could not extract spreadsheet ID from the provided URL.")],
        )
    spreadsheet_id = match.group(1)
    gid_match = _GID_RE.search(url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"


@router.post(path="/create/csv")
async def bulk_create_users_from_csv(
    battle_tag_row: int,
    discord_row: int,
    twitch_row: int,
    smurf_row: int,
    start_row: int = 0,
    delimiter: str = ",",
    has_discord: bool = True,
    has_smurf: bool = True,
    has_twitch: bool = True,
    data: UploadFile | None = None,
    sheet_url: str | None = None,
    session=Depends(db.get_async_session),
):
    if data is not None:
        raw = await data.read()
        lines = raw.decode("utf-8").split("\n")
        filename = data.filename or "upload.csv"
    elif sheet_url is not None:
        csv_url = _sheets_to_csv_url(sheet_url)
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(csv_url)
        if resp.status_code != 200:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[errors.ApiExc(code="sheet_fetch_failed", msg=f"Failed to fetch Google Sheet (HTTP {resp.status_code}).")],
            )
        lines = resp.text.split("\n")
        filename = sheet_url
    else:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="no_input", msg="Provide either a CSV file upload or a Google Sheets URL.")],
        )

    await user_flows.bulk_create_users_from_csv(
        session,
        filename,
        lines,
        start_row,
        battle_tag_row=battle_tag_row,
        discord_row=discord_row,
        twitch_row=twitch_row,
        smurf_row=smurf_row,
        delimiter=delimiter,
        has_discord=has_discord,
        has_smurf=has_smurf,
        has_twitch=has_twitch,
    )
    return {"success": True}
