"""Riot Sign-On: authorize parameters, Basic-auth token exchange, PUUID + Riot ID from account-v1, best-effort cpid."""

import asyncio
import base64
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.schemas.oauth import OAuthProvider  # noqa: E402
from src.services.oauth_providers import RiotOAuthProvider, oauth_providers  # noqa: E402

ACCOUNT = {"puuid": "puuid-abc", "gameName": "Hide on bush", "tagLine": "KR1"}


class _Http:
    """``OAuthHttpClient`` stand-in whose client answers from ``handler`` (no network)."""

    def __init__(self, handler) -> None:
        self.requests: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        self._client = httpx.AsyncClient(transport=httpx.MockTransport(record))

    def client(self) -> httpx.AsyncClient:
        return self._client


@pytest.fixture(autouse=True)
def _riot_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "RIOT_CLIENT_ID": "riot-client",
        "RIOT_CLIENT_SECRET": "riot-secret",
        "RIOT_ACCOUNT_CLUSTER": "europe",
        "OAUTH_REDIRECT": "https://owt.example/auth/callback",
    }.items():
        monkeypatch.setattr(f"src.services.oauth_providers.settings.{name}", value, raising=False)


def _accounts_and_userinfo(userinfo_status: int = 200, account: dict = ACCOUNT, userinfo_body: bytes | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/riot/account/v1/accounts/me":
            return httpx.Response(200, json=account)
        if request.url.path == "/userinfo":
            if userinfo_body is not None:
                return httpx.Response(userinfo_status, content=userinfo_body)
            return httpx.Response(userinfo_status, json={"sub": "x", "cpid": "kr"})
        return httpx.Response(404)

    return handler


def test_the_authorize_url_asks_for_openid_and_cpid() -> None:
    url = urlparse(RiotOAuthProvider(_Http(lambda r: httpx.Response(500))).get_authorization_url("st-1", "verifier"))
    query = parse_qs(url.query)
    assert (url.scheme, url.netloc, url.path) == ("https", "auth.riotgames.com", "/authorize")
    assert query == {
        "client_id": ["riot-client"],
        "redirect_uri": ["https://owt.example/auth/callback"],
        "response_type": ["code"],
        "scope": ["openid cpid"],
        "state": ["st-1"],
    }


def test_the_code_is_exchanged_with_basic_auth() -> None:
    http = _Http(lambda r: httpx.Response(200, json={"access_token": "at", "token_type": "Bearer"}))
    token = asyncio.run(RiotOAuthProvider(http).exchange_code("code-1", state="st-1", code_verifier="verifier"))
    request = http.requests[0]
    assert token["access_token"] == "at"
    assert (request.method, str(request.url)) == ("POST", "https://auth.riotgames.com/token")
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"riot-client:riot-secret").decode()
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["code-1"],
        "redirect_uri": ["https://owt.example/auth/callback"],
    }


def test_the_user_is_the_puuid_named_by_the_riot_id() -> None:
    http = _Http(_accounts_and_userinfo())
    info = asyncio.run(RiotOAuthProvider(http).get_user_info("at"))
    assert (info.provider, info.provider_user_id, info.username, info.display_name, info.email) == (
        OAuthProvider.RIOT,
        "puuid-abc",
        "Hide on bush#KR1",
        "Hide on bush#KR1",
        None,
    )
    assert info.raw_data == {"account": ACCOUNT, "cpid": "kr"}
    assert info.handle == "Hide on bush#KR1"
    assert str(http.requests[0].url) == "https://europe.api.riotgames.com/riot/account/v1/accounts/me"
    assert http.requests[0].headers["Authorization"] == "Bearer at"


def test_a_failed_userinfo_leaves_the_cpid_unknown() -> None:
    info = asyncio.run(RiotOAuthProvider(_Http(_accounts_and_userinfo(userinfo_status=503))).get_user_info("at"))
    assert info.raw_data["cpid"] is None and info.provider_user_id == "puuid-abc"


@pytest.mark.parametrize("body", [b"[]", b"null", b'"kr"', b'{"cpid": 7}'], ids=["list", "null", "string", "int-cpid"])
def test_a_userinfo_that_is_not_an_object_leaves_the_cpid_unknown(body: bytes) -> None:
    http = _Http(_accounts_and_userinfo(userinfo_body=body))
    info = asyncio.run(RiotOAuthProvider(http).get_user_info("at"))
    assert info.raw_data["cpid"] is None and info.provider_user_id == "puuid-abc"


def test_an_account_without_a_puuid_is_refused() -> None:
    http = _Http(_accounts_and_userinfo(account={"gameName": "x", "tagLine": "y"}))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(RiotOAuthProvider(http).get_user_info("at"))
    assert caught.value.status_code == 400


def test_riot_is_offered_only_when_enabled_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    assert OAuthProvider.RIOT not in oauth_providers.available()  # RIOT_OAUTH_ENABLED defaults to False
    monkeypatch.setattr("src.services.oauth_providers.settings.RIOT_OAUTH_ENABLED", True, raising=False)
    assert OAuthProvider.RIOT in oauth_providers.available()
    assert oauth_providers.get("riot").provider_name == "riot"
    assert oauth_providers.PROVIDER_SETTINGS["riot"]["redirect_uri"] == "OAUTH_REDIRECT"
