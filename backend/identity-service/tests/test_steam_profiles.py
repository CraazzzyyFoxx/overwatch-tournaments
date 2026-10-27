"""Steam persona names: Steam Web API with a key, deadlock-api without, both keyed back to the stored account id."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx  # noqa: E402

from src.services import steam_profiles  # noqa: E402

KITKAT, RABS = "206464648", "22202"


def _client(requests: list[httpx.Request], *, fail: bool = False) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if fail:
            return httpx.Response(503)
        if request.url.host == "api.steampowered.com":
            # Steam answers by SteamID64 and only for the ids it knows.
            return httpx.Response(
                200,
                json={
                    "response": {
                        "players": [
                            {"steamid": "76561198166730376", "personaname": "KitKat"},
                        ]
                    }
                },
            )
        return httpx.Response(200, json=[{"account_id": int(RABS), "personaname": "Rabscuttle"}])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_with_a_key_asks_steam_by_steamid64_and_maps_back_to_account_ids(monkeypatch) -> None:
    monkeypatch.setattr(steam_profiles.settings, "STEAM_WEB_API_KEY", "k")
    requests: list[httpx.Request] = []
    profiles = asyncio.run(steam_profiles.fetch_profiles(_client(requests), [KITKAT, RABS, KITKAT]))
    assert {account_id: p["personaname"] for account_id, p in profiles.items()} == {KITKAT: "KitKat"}
    assert [r.url.params["steamids"] for r in requests] == ["76561198166730376,76561197960287930"]


def test_without_a_key_falls_back_to_deadlock_api(monkeypatch) -> None:
    monkeypatch.setattr(steam_profiles.settings, "STEAM_WEB_API_KEY", None)
    requests: list[httpx.Request] = []
    profiles = asyncio.run(steam_profiles.fetch_profiles(_client(requests), [RABS]))
    assert profiles[RABS]["personaname"] == "Rabscuttle"
    assert requests[0].url.host == "api.deadlock-api.com"


def test_refresh_writes_new_names_and_keeps_the_last_known_one_on_silence_or_failure(monkeypatch) -> None:
    monkeypatch.setattr(steam_profiles.settings, "STEAM_WEB_API_KEY", "k")
    accounts = [
        SimpleNamespace(id=1, username=KITKAT, display_name="old"),  # renamed on Steam
        SimpleNamespace(id=2, username=RABS, display_name="Rabscuttle"),  # Steam does not answer for it
    ]
    events: list[str] = []

    async def list_by_provider(_session, provider, *, ids=None):
        assert (provider, ids) == ("steam", None)
        return accounts

    async def update_fields(_session, instance, data):
        for field, value in data.items():
            setattr(instance, field, value)

    async def commit():
        events.append("commit")

    fetch = steam_profiles.fetch_profiles

    async def fetch_profiles(http, account_ids):
        events.append("fetch")
        return await fetch(http, account_ids)

    monkeypatch.setattr(steam_profiles._accounts, "list_by_provider", list_by_provider)
    monkeypatch.setattr(steam_profiles._accounts, "update_fields", update_fields)
    monkeypatch.setattr(steam_profiles, "fetch_profiles", fetch_profiles)
    session = SimpleNamespace(commit=commit)

    assert asyncio.run(steam_profiles.refresh_display_names(session, _client([]))) == 1
    assert [a.display_name for a in accounts] == ["KitKat", "Rabscuttle"]

    assert asyncio.run(steam_profiles.refresh_display_names(session, _client([], fail=True))) == 0
    assert [a.display_name for a in accounts] == ["KitKat", "Rabscuttle"]
    # The account read's transaction ends before every HTTP round of a refresh: none is held across the requests.
    assert events == ["commit", "fetch", "commit", "fetch"]
