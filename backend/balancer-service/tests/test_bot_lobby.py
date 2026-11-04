"""A mix's bot lobby: what the game source's callback may carry, who may report a match id, and what create refuses."""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(REPO_BACKEND_ROOT), str(REPO_BACKEND_ROOT / "balancer-service")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core.errors import BaseAPIException  # noqa: E402
from shared.disciplines import DISCIPLINES  # noqa: E402
from shared.disciplines.lobby import (  # noqa: E402
    BotLobbyFailed,
    BotLobbyParty,
    BotLobbyRateLimited,
    IngestStatus,
    LobbyBotSpec,
)
from src.domain.bot_lobby import (  # noqa: E402
    POLL_WINDOW,
    merge_ingest_status,
    parse_match_id,
    secret_matches,
    token_sha256,
)
from src.services import bot_lobby as service  # noqa: E402

NOW = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("123456789", "123456789"),
        ("  123456789\n", "123456789"),
        ('"123456789"', "123456789"),
        ('{"match_id": 123456789}', "123456789"),
        ('{"match_id": "123456789"}', "123456789"),
        # beyond a JavaScript safe integer stays exact.
        ("9223372036854775807", "9223372036854775807"),
        ("", None),
        ("null", None),
        ("true", None),
        ("0", None),
        ("007", None),
        ("12.5", None),
        ("-3", None),
        ('{"match": 5}', None),
        ('{"match_id": null}', None),
        ("[123]", None),
        ("match 123", None),
        ("1" * 20, None),
    ],
)
def test_the_callback_body_is_read_as_a_number_a_string_an_object_or_plain_digits(body, expected):
    assert parse_match_id(body) == expected


def test_a_sender_that_names_a_wrong_secret_is_refused_and_a_missing_header_is_left_to_the_path_token():
    assert secret_matches("s3cret", "s3cret")
    assert not secret_matches("s3cret", "other")
    assert secret_matches("s3cret", None)
    assert secret_matches("s3cret", "")
    assert secret_matches(None, "anything")


def test_an_accounts_statuses_merge_to_an_active_one_or_unknown_never_a_false_inactive():
    active = IngestStatus(True, NOW, 14)
    newer = IngestStatus(True, NOW + timedelta(days=1), 14)
    idle = IngestStatus(False, None, 14)
    assert merge_ingest_status([idle, newer, active, None]) == newer
    assert merge_ingest_status([idle, idle]) == idle
    assert merge_ingest_status([idle, None]) is None
    assert merge_ingest_status([None]) is None
    assert merge_ingest_status([]) is None


class _Repo:
    """The party table: one open party, found only by its token's digest."""

    def __init__(self, row: Any = None) -> None:
        self.row = row
        self.replaced: list[Any] = []

    async def get_awaiting_by_token(self, _session: Any, digest: str) -> Any:
        return self.row if self.row is not None and self.row.callback_token_sha256 == digest else None

    async def replace(self, _session: Any, row: Any) -> Any:
        self.replaced.append(row)
        return row


def _row(*, secret: str | None = "s3cret", created_at: datetime = NOW) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_id=3,
        custom_game_id=8,
        callback_token_sha256=token_sha256("tok"),
        callback_secret=secret,
        match_id=None,
        created_at=created_at,
    )


@pytest.fixture
def emitted(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def emit(_session: Any, workspace_id: int, **kwargs: Any) -> None:
        calls.append({"workspace_id": workspace_id, **kwargs})

    monkeypatch.setattr(service, "emit_pickup_mix_changed", emit)
    return calls


async def _callback(repo: _Repo, *, token="tok", body="123456789", secret="s3cret", now=NOW + timedelta(minutes=5)):
    session = SimpleNamespace(flush=_noop)
    await service.BotLobbyService(bot_lobbies=repo).accept_callback(
        session, token=token, body=body, secret=secret, now=now
    )


async def _noop() -> None:
    return None


def test_a_callback_with_its_token_and_secret_records_the_match_id_and_tells_the_room(emitted):
    row = _row()
    asyncio.run(_callback(_Repo(row)))
    assert row.match_id == "123456789"
    assert emitted == [{"workspace_id": 3, "custom_game_id": 8, "change": "bot_lobby"}]


def test_a_callback_without_the_secret_header_is_accepted_on_the_path_token_alone(emitted):
    row = _row()
    asyncio.run(_callback(_Repo(row), secret=None))
    assert row.match_id == "123456789"


@pytest.mark.parametrize(
    "refused",
    [
        {"token": "guess"},
        {"secret": "wrong"},
        {"body": "not a match id"},
        {"now": NOW + POLL_WINDOW + timedelta(seconds=1)},
    ],
    ids=["unknown token", "wrong secret", "no match id in the body", "expired"],
)
def test_a_refused_callback_changes_nothing_and_says_nothing(emitted, refused):
    row = _row()
    asyncio.run(_callback(_Repo(row), **refused))
    assert row.match_id is None
    assert emitted == []


class _Configs:
    def __init__(self, regions: dict[str, str] | None = None) -> None:
        self.row = None if regions is None else SimpleNamespace(bot_lobby_regions=regions)
        self.created: list[Any] = []
        self.updated: list[dict[str, Any]] = []

    async def get_by_user(self, _session: Any, _user_id: int) -> Any:
        return self.row

    async def create(self, _session: Any, row: Any) -> Any:
        self.created.append(row)
        return row

    async def update_fields(self, _session: Any, _row: Any, fields: dict[str, Any]) -> None:
        self.updated.append(fields)


def _arrange(monkeypatch, *, live: int | None = 40, sizes=(6, 6), create: Any = None):
    """A host-writable mix 8 of Deadlock whose lobby 0 has a live match of ``sizes`` seats; returns what was asked."""
    asked: list[Any] = []
    lobby = SimpleNamespace(live_encounter_id=live, lobby_code=None)
    game = SimpleNamespace(id=8, workspace_id=3, discipline="deadlock")

    async def writable_lobby(_session: Any, **_kwargs: Any) -> tuple[Any, Any]:
        return game, lobby

    async def team_sizes(_session: Any, _encounter_id: int) -> list[int]:
        return list(sizes)

    async def make(request: Any) -> BotLobbyParty:
        asked.append(request)
        return BotLobbyParty("party-1", "KX7Q", "shh")

    monkeypatch.setattr(service.custom_game_service, "writable_lobby", writable_lobby)
    monkeypatch.setattr(service.custom_game_service, "lobbies", SimpleNamespace(team_sizes=team_sizes))
    spec = dataclasses.replace(
        DISCIPLINES["deadlock"],
        lobby_bot=LobbyBotSpec(("europe", "us_east"), "europe", create or make, _noop_match),
    )
    monkeypatch.setitem(service.DISCIPLINES, "deadlock", spec)
    monkeypatch.setattr(service.config, "public_site_url", "https://anak.example")
    return asked, lobby, game


async def _noop_match(_party_id: str) -> None:
    return None


async def _create(service_: service.BotLobbyService, region: str = "europe") -> Any:
    return await service_.create(
        SimpleNamespace(flush=_noop),
        workspace_id=3,
        custom_game_id=8,
        lobby_index=0,
        region=region,
        actor_user_id=70,
    )


def _refused(coro: Any) -> BaseAPIException:
    with pytest.raises(BaseAPIException) as refused:
        asyncio.run(coro)
    return refused.value


def test_a_bot_lobby_is_bound_to_the_live_match_and_its_code_becomes_the_lobby_code(monkeypatch):
    asked, lobby, _game = _arrange(monkeypatch)
    repo, configs = _Repo(), _Configs()

    asyncio.run(_create(service.BotLobbyService(bot_lobbies=repo, configs=configs), "us_east"))

    [request] = asked
    assert (request.region, request.team_size, request.roster_size) == ("us_east", 6, 12)
    assert request.callback_url.startswith("https://anak.example/api/v1/lobby-bot/callback/")
    [party] = repo.replaced
    assert request.callback_url.endswith(party_token_path(party))
    assert (party.encounter_id, party.party_id, party.party_code, party.callback_secret) == (
        40,
        "party-1",
        "KX7Q",
        "shh",
    )
    assert party.created_by_user_id == 70
    # Only the digest is stored, never the token.
    assert len(party.callback_token_sha256) == 64
    assert lobby.lobby_code == "KX7Q"
    # The region is remembered for the host: a new row for a host with none yet.
    [saved] = configs.created
    assert saved.bot_lobby_regions == {"deadlock": "us_east"}


def party_token_path(party: Any) -> str:
    """The token in the callback URL is the one whose digest the party stores."""
    return "/" + next(token for token in _tokens_seen if token_sha256(token) == party.callback_token_sha256)


_tokens_seen: list[str] = []


@pytest.fixture(autouse=True)
def _record_tokens(monkeypatch):
    """The test never sees the token but in the callback URL it hands the source: collect it from there."""
    _tokens_seen.clear()
    real = service.BotLobbyService.callback_url

    def spy(token: str) -> str | None:
        _tokens_seen.append(token)
        return real(token)

    monkeypatch.setattr(service.BotLobbyService, "callback_url", staticmethod(spy))


def test_a_remembered_region_is_replaced_and_other_games_keep_theirs(monkeypatch):
    _arrange(monkeypatch)
    configs = _Configs({"overwatch": "x", "deadlock": "europe"})

    asyncio.run(_create(service.BotLobbyService(bot_lobbies=_Repo(), configs=configs), "us_east"))

    assert configs.updated == [{"bot_lobby_regions": {"overwatch": "x", "deadlock": "us_east"}}]


def test_a_site_without_a_public_address_sends_no_callback_url(monkeypatch):
    asked, _lobby, _game = _arrange(monkeypatch)
    monkeypatch.setattr(service.config, "public_site_url", "http://localhost:3000")

    asyncio.run(_create(service.BotLobbyService(bot_lobbies=_Repo(), configs=_Configs())))

    assert asked[0].callback_url is None


def test_create_refuses_a_region_the_game_does_not_offer_and_a_lobby_without_a_live_match(monkeypatch):
    _arrange(monkeypatch)
    refused = _refused(_create(service.BotLobbyService(bot_lobbies=_Repo(), configs=_Configs()), "mars"))
    assert (refused.status_code, refused.detail) == (422, "invalid_region")

    _arrange(monkeypatch, live=None)
    refused = _refused(_create(service.BotLobbyService(bot_lobbies=_Repo(), configs=_Configs())))
    assert (refused.status_code, refused.detail) == (409, "no_live_match")


def test_create_refuses_a_game_without_a_bot_lobby(monkeypatch):
    _arrange(monkeypatch)
    monkeypatch.setitem(service.DISCIPLINES, "deadlock", dataclasses.replace(DISCIPLINES["deadlock"], lobby_bot=None))
    refused = _refused(_create(service.BotLobbyService(bot_lobbies=_Repo(), configs=_Configs())))
    assert (refused.status_code, refused.detail) == (422, "unsupported_lobby_bot")


def test_a_rate_limited_or_failed_source_is_reported_and_nothing_is_stored(monkeypatch):
    async def limited(_request: Any) -> BotLobbyParty:
        raise BotLobbyRateLimited(120)

    async def down(_request: Any) -> BotLobbyParty:
        raise BotLobbyFailed("deadlock-api answered 500")

    repo, configs = _Repo(), _Configs()
    _arrange(monkeypatch, create=limited)
    refused = _refused(_create(service.BotLobbyService(bot_lobbies=repo, configs=configs)))
    assert (refused.status_code, refused.detail, refused.headers) == (
        429,
        "lobby_bot_rate_limited:120",
        {"Retry-After": "120"},
    )

    _arrange(monkeypatch, create=down)
    refused = _refused(_create(service.BotLobbyService(bot_lobbies=repo, configs=configs)))
    assert (refused.status_code, refused.detail) == (503, "lobby_bot_failed")
    assert repo.replaced == [] and configs.created == []
