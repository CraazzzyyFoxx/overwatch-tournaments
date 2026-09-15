"""Async Challonge API v1 client.

tournament-service and parser-service each carried their own byte-for-byte
copy of this ~150-line wrapper (client construction, ``_check_response``, and
the six read/write methods) — and only tournament-service's copy had been
patched with slug validation (``_validate_slug``/``_SLUG_RE``) on
``fetch_tournament``: without it, a caller-supplied ``tournament_id`` there is
a Challonge *slug* (not always numeric) interpolated straight into the
request path, so a crafted value like ``../`` could build an arbitrary
``api.challonge.com`` path executed with the service's stored Basic-Auth
credentials. The other five methods take a numeric Challonge id and already
coerce it with ``int(...)``, which is sufficient (raises on anything that
isn't a plain integer). Single source of truth here, with the fix applied
once.
"""

from __future__ import annotations

import re
from typing import Any

from httpx import AsyncClient, BasicAuth
from loguru import logger

from shared.core.errors import ApiExc, ApiHTTPException
from shared.schemas.challonge import ChallongeMatch, ChallongeParticipant, ChallongeTournament

__all__ = ("ChallongeClient",)

# Challonge tournament URLs/slugs are alphanumeric with _ and - (subdomain form
# "sub-slug" included). Anything else (e.g. "../", "?") would let a caller build
# an arbitrary api.challonge.com path executed with our stored credentials.
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_slug(value: str | int) -> str:
    slug = str(value)
    if not _SLUG_RE.fullmatch(slug):
        raise ApiHTTPException(
            status_code=422,
            detail=[ApiExc(code="invalid_slug", msg="Invalid Challonge tournament slug.")],
        )
    return slug


def _check_response(resp: Any, entity: str, entity_id: Any) -> None:
    if resp.status_code not in (200, 201):
        raise ApiHTTPException(
            status_code=400,
            detail=[
                ApiExc(
                    code="challonge_error",
                    msg=f"{entity} with id {entity_id} — Challonge returned {resp.status_code}.",
                )
            ],
        )


class ChallongeClient:
    """Thin async wrapper over the Challonge API v1, one instance per service."""

    def __init__(self, *, username: str, api_key: str, proxy_url: str | None = None, timeout: float = 15) -> None:
        self._http = AsyncClient(
            base_url="https://api.challonge.com/v1/",
            auth=BasicAuth(username=username, password=api_key),
            proxy=proxy_url,
            timeout=timeout,
        )

    @classmethod
    def from_settings(cls, settings: Any) -> ChallongeClient:
        """Build a ``ChallongeClient`` from any settings object exposing
        ``challonge_username``/``challonge_api_key``/``proxy_url``."""
        return cls(
            username=settings.challonge_username,
            api_key=settings.challonge_api_key,
            proxy_url=getattr(settings, "proxy_url", None),
        )

    # ── Read methods ─────────────────────────────────────────────────────

    async def fetch_tournament(self, tournament_id: str) -> ChallongeTournament:
        tournament_id = _validate_slug(tournament_id)
        resp = await self._http.get(f"tournaments/{tournament_id}.json")
        _check_response(resp, "Tournament", tournament_id)
        return ChallongeTournament.model_validate(resp.json()["tournament"])

    async def fetch_participants(self, tournament_id: int) -> list[ChallongeParticipant]:
        tournament_id = int(tournament_id)
        resp = await self._http.get(f"tournaments/{tournament_id}/participants.json")
        _check_response(resp, "Tournament", tournament_id)
        return [ChallongeParticipant.model_validate(p["participant"]) for p in resp.json()]

    async def fetch_matches(self, tournament_id: int) -> list[ChallongeMatch]:
        tournament_id = int(tournament_id)
        resp = await self._http.get(f"tournaments/{tournament_id}/matches.json")
        _check_response(resp, "Tournament", tournament_id)
        return [ChallongeMatch.model_validate(m["match"]) for m in resp.json()]

    # ── Write methods ────────────────────────────────────────────────────

    async def update_match(
        self,
        tournament_id: int,
        match_id: int,
        *,
        scores_csv: str,
        winner_id: int | str,
    ) -> dict:
        """Push match result to Challonge.

        Args:
            tournament_id: Challonge tournament ID.
            match_id: Challonge match ID.
            scores_csv: Score string, e.g. "2-1".
            winner_id: Challonge participant ID of the winner, or "tie" for a draw.
        """
        tournament_id = int(tournament_id)
        match_id = int(match_id)
        logger.info(
            f"Challonge: updating match {match_id} on tournament {tournament_id} scores={scores_csv} winner={winner_id}"
        )
        resp = await self._http.put(
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
        self,
        tournament_id: int,
        *,
        name: str,
        seed: int | None = None,
    ) -> dict:
        """Create a participant in a Challonge tournament."""
        tournament_id = int(tournament_id)
        logger.info(f"Challonge: creating participant '{name}' on tournament {tournament_id}")
        payload: dict = {"participant": {"name": name}}
        if seed is not None:
            payload["participant"]["seed"] = seed
        resp = await self._http.post(
            f"tournaments/{tournament_id}/participants.json",
            json=payload,
        )
        _check_response(resp, "Tournament", tournament_id)
        return resp.json()

    async def update_tournament_state(
        self,
        tournament_id: int,
        *,
        state: str,
    ) -> dict:
        """Update Challonge tournament state (start, finalize, reset).

        Challonge states: 'start', 'finalize', 'reset'.
        """
        tournament_id = int(tournament_id)
        if state not in ("start", "finalize", "reset"):
            raise ApiHTTPException(
                status_code=422,
                detail=[ApiExc(code="invalid_state", msg=f"Invalid Challonge state '{state}'.")],
            )
        logger.info(f"Challonge: {state} tournament {tournament_id}")
        resp = await self._http.post(f"tournaments/{tournament_id}/{state}.json")
        _check_response(resp, "Tournament", tournament_id)
        return resp.json()
