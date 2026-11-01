"""The deadlock-api match search: a round's private lobby matches as sides of known accounts, and its "not yet"."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from shared.disciplines.deadlock import search
from shared.disciplines.ingest import MatchCandidate, MatchFetchNotReady, MatchQuery

QUERY = MatchQuery(
    identities=frozenset({"11", "12", "not-an-account"}),
    started_from=datetime(2026, 11, 1, 19, 55, tzinfo=UTC),
    started_until=datetime(2026, 11, 1, 20, 40, tzinfo=UTC),
)


class _Client:
    def __init__(self, response: httpx.Response, seen: list[dict]) -> None:
        self.response, self.seen = response, seen

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get(self, path: str, **kwargs: object) -> httpx.Response:
        self.seen.append({"path": path, **kwargs})
        return self.response


def _run(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> tuple[list[MatchCandidate], list[dict]]:
    seen: list[dict] = []
    monkeypatch.setattr(search, "deadlock_client", lambda: _Client(response, seen))
    return asyncio.run(search.search_matches(QUERY)), seen


def test_a_match_is_its_sides_of_known_accounts_and_the_query_is_the_window_and_the_accounts(monkeypatch) -> None:
    players = [
        {"account_id": 11, "team": "Team0"},
        {"account_id": 0, "team": "Team0"},  # a private profile
        {"account_id": 12, "team": "Team1"},
        {"account_id": 13, "team": "Team1"},
    ]
    found, seen = _run(monkeypatch, httpx.Response(200, json=[{"match_id": 4242, "players": players}]))

    assert found == [MatchCandidate(external_id="4242", teams=(frozenset({"11"}), frozenset({"12", "13"})))]
    [request] = seen
    assert request["path"] == "/v1/matches/metadata"
    assert request["params"]["match_mode"] == "private_lobby"
    assert request["params"]["account_ids"] == "11,12"
    assert (request["params"]["min_unix_timestamp"], request["params"]["max_unix_timestamp"]) == (
        int(QUERY.started_from.timestamp()),
        int(QUERY.started_until.timestamp()),
    )


def test_none_found_is_an_empty_answer_and_a_busy_source_is_not_yet(monkeypatch) -> None:
    assert _run(monkeypatch, httpx.Response(404, json={"error": "No matches found"}))[0] == []
    for status in (429, 503):
        with pytest.raises(MatchFetchNotReady):
            _run(monkeypatch, httpx.Response(status))
