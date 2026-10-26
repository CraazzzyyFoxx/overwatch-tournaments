"""Async Challonge API v1 client.

tournament-service and stats-service each carried their own byte-for-byte
copy of this ~150-line wrapper (client construction, ``_check_response``, and
the read/write methods) — and only tournament-service's copy had been
patched with slug validation (``_validate_slug``/``_SLUG_RE``) on
``fetch_tournament``: without it, a caller-supplied ``tournament_id`` there is
a Challonge *slug* (not always numeric) interpolated straight into the
request path, so a crafted value like ``../`` could build an arbitrary
``api.challonge.com`` path executed with the service's stored Basic-Auth
credentials. The other methods take a numeric Challonge id and already
coerce it with ``int(...)``, which is sufficient (raises on anything that
isn't a plain integer). Single source of truth here, with the fix applied
once.
"""

from __future__ import annotations

import re
from typing import Any

from httpx import AsyncClient, BasicAuth, RequestError
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
    if resp.status_code in (200, 201):
        return
    if resp.status_code == 404:
        raise ApiHTTPException(
            status_code=404,
            detail=[ApiExc(code="challonge_not_found", msg=f"{entity} with id {entity_id} is not on Challonge.")],
        )
    # Rate limit or Challonge's own failure: the request was fine, a later retry may land (503 ``unavailable``).
    # Anything else is Challonge refusing this request, which a retry cannot change.
    unavailable = resp.status_code == 429 or resp.status_code >= 500
    raise ApiHTTPException(
        status_code=503 if unavailable else 400,
        detail=[
            ApiExc(
                code="challonge_unavailable" if unavailable else "challonge_error",
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

    async def _request(self, method: str, path: str, entity: str, entity_id: Any, **kwargs: Any) -> Any:
        """One call's decoded JSON; a refusal or no answer at all is an ``ApiHTTPException`` (404, 400 or 503)."""
        try:
            resp = await self._http.request(method, path, **kwargs)
        except RequestError as exc:
            # Unreachable, timed out, connection dropped: as retryable as Challonge's own 5xx.
            raise ApiHTTPException(
                status_code=503,
                detail=[
                    ApiExc(
                        code="challonge_unavailable",
                        msg=f"{entity} with id {entity_id} — Challonge did not answer ({type(exc).__name__}).",
                    )
                ],
            ) from exc
        _check_response(resp, entity, entity_id)
        return resp.json()

    # ── Read methods ─────────────────────────────────────────────────────

    async def fetch_tournament(self, tournament_id: str) -> ChallongeTournament:
        tournament_id = _validate_slug(tournament_id)
        data = await self._request("GET", f"tournaments/{tournament_id}.json", "Tournament", tournament_id)
        return ChallongeTournament.model_validate(data["tournament"])

    async def fetch_participants(self, tournament_id: int) -> list[ChallongeParticipant]:
        tournament_id = int(tournament_id)
        path = f"tournaments/{tournament_id}/participants.json"
        data = await self._request("GET", path, "Tournament", tournament_id)
        return [ChallongeParticipant.model_validate(p["participant"]) for p in data]

    async def fetch_matches(self, tournament_id: int) -> list[ChallongeMatch]:
        tournament_id = int(tournament_id)
        data = await self._request("GET", f"tournaments/{tournament_id}/matches.json", "Tournament", tournament_id)
        return [ChallongeMatch.model_validate(m["match"]) for m in data]

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
        return await self._request(
            "PUT",
            f"tournaments/{tournament_id}/matches/{match_id}.json",
            "Match",
            match_id,
            json={
                "match": {
                    "scores_csv": scores_csv,
                    "winner_id": winner_id,
                }
            },
        )
