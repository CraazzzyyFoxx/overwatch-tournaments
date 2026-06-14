"""Domain-specific S3 helpers for match logs and team data.

Delegates to the shared S3Client stored on ``app.state.s3``.
"""

from loguru import logger

from shared.clients.s3 import S3Client


async def get_logs_by_tournament(s3: S3Client, tournament_id: int) -> list[str]:
    return await s3.list_objects(f"logs/{tournament_id}/")


async def get_log_by_filename(s3: S3Client, tournament_id: int, filename: str) -> bytes | None:
    base = f"logs/{tournament_id}/"
    bare = filename.removeprefix(base).removeprefix("logs/")
    if ".." in bare or bare.startswith("/"):
        logger.warning(f"Rejected suspicious filename: {filename!r}")
        return None
    key = f"{base}{bare}"
    return await s3.get_object(key)


async def upload_log(s3: S3Client, tournament_id: int, filename: str, data: bytes) -> bool:
    key = f"logs/{tournament_id}/{filename}"
    folder_key = f"logs/{tournament_id}/"
    await s3.ensure_folder(folder_key)
    return await s3.put_object(key, data)


async def delete_log(s3: S3Client, tournament_id: int, filename: str) -> bool:
    key = f"logs/{tournament_id}/{filename}"
    return await s3.delete_object(key)


async def get_tournament_teams(s3: S3Client, tournament_id: int) -> list[str]:
    return await s3.list_objects(f"{tournament_id}/teams/")


async def get_tournaments_teams(s3: S3Client) -> dict[str, bytes | None]:
    tournaments = await s3.list_objects("teams/tournament")
    result: dict[str, bytes | None] = {}
    for key in tournaments:
        tournament_id = key.split("/")[1]
        data = await s3.get_object(key)
        result[tournament_id] = data
    return result
