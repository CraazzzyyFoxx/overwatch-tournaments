from loguru import logger
from httpx import AsyncClient, BasicAuth

from src import schemas
from src.core import config, errors


challonge_client = AsyncClient(
    base_url="https://api.challonge.com/v1/",
    auth=BasicAuth(
        username=config.settings.challonge_username,
        password=config.settings.challonge_api_key,
    ),
    proxy=config.settings.proxy_url,
    timeout=15,
)


def _check_response(resp, entity: str, entity_id) -> None:
    if resp.status_code not in (200, 201):
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="challonge_error",
                    msg=f"{entity} with id {entity_id} — Challonge returned {resp.status_code}.",
                )
            ],
        )


# ── Read methods ─────────────────────────────────────────────────────────────


async def fetch_tournament(tournament_id: str) -> schemas.ChallongeTournament:
    resp = await challonge_client.get(f"tournaments/{tournament_id}.json")
    _check_response(resp, "Tournament", tournament_id)
    return schemas.ChallongeTournament.model_validate(resp.json()["tournament"])


async def fetch_participants(tournament_id: int) -> list[schemas.ChallongeParticipant]:
    resp = await challonge_client.get(f"tournaments/{tournament_id}/participants.json")
    _check_response(resp, "Tournament", tournament_id)
    return [
        schemas.ChallongeParticipant.model_validate(p["participant"])
        for p in resp.json()
    ]


async def fetch_matches(tournament_id: int) -> list[schemas.ChallongeMatch]:
    resp = await challonge_client.get(f"tournaments/{tournament_id}/matches.json")
    _check_response(resp, "Tournament", tournament_id)
    return [
        schemas.ChallongeMatch.model_validate(m["match"])
        for m in resp.json()
    ]


# ── Write methods ────────────────────────────────────────────────────────────


async def update_match(
    tournament_id: int,
    match_id: int,
    *,
    scores_csv: str,
    winner_id: int,
) -> dict:
    """Push match result to Challonge.

    Args:
        tournament_id: Challonge tournament ID.
        match_id: Challonge match ID.
        scores_csv: Score string, e.g. "2-1".
        winner_id: Challonge participant ID of the winner.
    """
    logger.info(
        f"Challonge: updating match {match_id} on tournament {tournament_id} "
        f"scores={scores_csv} winner={winner_id}"
    )
    resp = await challonge_client.put(
        f"tournaments/{tournament_id}/matches/{match_id}.json",
        json={
            "match": {
                "scores_csv": scores_csv,
                "winner_id": winner_id,
            }
        },
    )
    _check_response(resp, "Match", match_id)
    return resp.json()


async def create_participant(
    tournament_id: int,
    *,
    name: str,
    seed: int | None = None,
) -> dict:
    """Create a participant in a Challonge tournament."""
    logger.info(f"Challonge: creating participant '{name}' on tournament {tournament_id}")
    payload: dict = {"participant": {"name": name}}
    if seed is not None:
        payload["participant"]["seed"] = seed
    resp = await challonge_client.post(
        f"tournaments/{tournament_id}/participants.json",
        json=payload,
    )
    _check_response(resp, "Tournament", tournament_id)
    return resp.json()


async def update_tournament_state(
    tournament_id: int,
    *,
    state: str,
) -> dict:
    """Update Challonge tournament state (start, finalize, reset).

    Challonge states: 'start', 'finalize', 'reset'.
    """
    logger.info(f"Challonge: {state} tournament {tournament_id}")
    resp = await challonge_client.post(
        f"tournaments/{tournament_id}/{state}.json",
    )
    _check_response(resp, "Tournament", tournament_id)
    return resp.json()
