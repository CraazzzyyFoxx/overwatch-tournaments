"""Auth hardening (IdentityOAuthRbac): C4 account listing, permission-delete invalidation, PKCE,
Steam answer binding, provider-token sealing (write, read, startup job)."""

import asyncio
import base64
import hashlib
import importlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import secretbox  # noqa: E402
from shared.repository import AuthUserRepository  # noqa: E402
from src import schemas  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.services.oauth import OAuthFlowService  # noqa: E402
from src.services.oauth_accounts import OAuthAccountService  # noqa: E402
from src.services.oauth_providers import DiscordOAuthProvider, SteamOpenIDProvider, oauth_providers  # noqa: E402
from src.services.oauth_state import oauth_state  # noqa: E402
from src.services.rbac import AuthUserAdminService, PermissionAdminService  # noqa: E402
from tests._fakes import FakeSessionCache, make_root_actor  # noqa: E402

KEY = secretbox.load_key(settings.oauth_token_encryption_key)

# ─── C4: GET /rbac/users ─────────────────────────────────────────────────────


class _Users:
    """``AuthUserRepository`` stand-in recording which query the listing chose."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls: list[tuple[str, object, dict]] = []

    async def list_with_rbac(self, session, params, **filters):
        self.calls.append(("list_with_rbac", params, filters))
        return self.rows, len(self.rows)

    async def lookup(self, session, params, *, search):
        self.calls.append(("lookup", params, {"search": search}))
        return self.rows, len(self.rows)


def _scoped_reader(workspace_id: int = 5) -> SimpleNamespace:
    """``auth_user.read`` in one workspace only."""
    return SimpleNamespace(
        is_superuser=False,
        has_permission=lambda _r, _a: False,
        has_workspace_permission=lambda ws, r, a: ws == workspace_id and (r, a) == ("auth_user", "read"),
    )


def _account(user_id: int = 9) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email="ada@example.com",
        username="ada",
        first_name=None,
        last_name=None,
        is_active=True,
        is_superuser=True,
        is_verified=True,
        created_at=datetime.now(UTC),
        updated_at=None,
        roles=[],
        player=SimpleNamespace(id=3, name="Ada", avatar_url="https://cdn/a.png", created_at=datetime.now(UTC)),
    )


def _list(service, user, **params):
    return asyncio.run(service.list(object(), user, schemas.AuthUserListParams(**params)))


def test_workspace_listing_without_search_is_members_only() -> None:
    users = _Users([_account()])
    response = _list(AuthUserAdminService(users=users), _scoped_reader(), workspace_id=5)

    ((kind, _params, filters),) = users.calls
    assert kind == "list_with_rbac" and filters["member_of_workspace_id"] == 5
    assert response["results"][0].email == "ada@example.com"  # members get full rows


def test_scoped_search_returns_capped_identity_only_rows() -> None:
    users = _Users([_account()])
    response = _list(
        AuthUserAdminService(users=users), _scoped_reader(), workspace_id=5, search="  ada@example.com ", per_page=-1
    )

    ((kind, params, filters),) = users.calls
    assert (kind, filters, params.per_page, params.sort) == ("lookup", {"search": "ada@example.com"}, 20, "username")
    assert response["per_page"] == 20
    assert response["results"][0].model_dump() == {"id": 9, "username": "ada", "avatar_url": "https://cdn/a.png"}


def test_scoped_search_under_three_characters_is_an_empty_page() -> None:
    users = _Users([_account()])
    response = _list(AuthUserAdminService(users=users), _scoped_reader(), workspace_id=5, search="ad")
    assert (users.calls, response["results"], response["total"]) == ([], [], 0)


def test_a_global_reader_keeps_the_full_global_search() -> None:
    users = _Users([_account()])
    _list(AuthUserAdminService(users=users), make_root_actor(), workspace_id=5, search="ada")
    ((kind, _params, filters),) = users.calls
    assert kind == "list_with_rbac" and filters["member_of_workspace_id"] is None and filters["search"] == "ada"


def test_scoped_listing_of_another_workspace_is_forbidden() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _list(AuthUserAdminService(users=_Users()), _scoped_reader(5), workspace_id=6)
    assert exc_info.value.status_code == 403


class _Capture:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(
            unique=lambda: SimpleNamespace(scalars=lambda: SimpleNamespace(all=list)), scalar_one=lambda: 0
        )


def test_lookup_matches_exact_email_and_escaped_username_substring() -> None:
    session = _Capture()
    params = schemas.AuthUserListParams(per_page=20, sort="username")
    asyncio.run(AuthUserRepository().lookup(session, params, search="A_b%"))

    sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "lower(auth.\"user\".email) = 'a_b%'" in sql
    assert "LIKE" in sql and "a/_b/%" in sql.lower()  # wildcards escaped, not a pattern
    assert 'auth."user".email LIKE' not in sql  # no partial email match


# ─── permission deletion ─────────────────────────────────────────────────────


class _Permissions:
    async def get(self, session, permission_id):
        return SimpleNamespace(id=permission_id, name="p", resource="r", action="a", description=None)

    async def role_ids_with_permission(self, session, permission_id):
        return [1]

    async def delete(self, session, permission):
        return None


def test_permission_deletion_invalidates_role_holders_and_deny_holders(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(
        importlib.import_module("src.services.rbac.permission_admin"), "record_operator_audit", no_audit
    )
    cache = FakeSessionCache()
    service = PermissionAdminService(
        permissions=_Permissions(),
        role_grants=SimpleNamespace(user_ids_for_role=lambda s, r: _async([10])),
        denies=SimpleNamespace(user_ids_for_permission=lambda s, p: _async([20, 10])),
        cache=cache,
    )
    session = SimpleNamespace(commit=lambda: _async(None))

    asyncio.run(service.delete(session, make_root_actor(), 4))

    assert sorted(cache.invalidated) == [10, 20]


async def _async(value):
    return value


# ─── PKCE (Discord) ──────────────────────────────────────────────────────────


class _Http:
    def __init__(self, response):
        self.response = response
        self.posts: list[dict] = []

    def client(self):
        return self

    async def post(self, url, data=None, **kwargs):
        self.posts.append(data)
        return self.response


def _verifier() -> str:
    state = oauth_state.encode(origin="https://owt.example", redirect="/", action="login", provider="discord", csrf="c")
    return oauth_state.code_verifier(oauth_state.verify(state))


def test_discord_sends_the_s256_challenge_and_later_the_verifier() -> None:
    verifier = _verifier()
    assert 43 <= len(verifier) <= 128 and verifier != _verifier()  # one per flow

    query = parse_qs(urlparse(oauth_providers.providers["discord"].get_authorization_url("st", verifier)).query)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert (query["code_challenge"], query["code_challenge_method"]) == ([challenge], ["S256"])
    assert verifier not in str(query)

    http = _Http(SimpleNamespace(status_code=200, json=lambda: {"access_token": "at"}))
    asyncio.run(DiscordOAuthProvider(http).exchange_code("code", state="st", code_verifier=verifier))
    assert http.posts[0]["code_verifier"] == verifier


@pytest.mark.parametrize("provider", ["twitch", "battlenet", "riot"])
def test_providers_without_documented_pkce_send_none(provider: str) -> None:
    query = parse_qs(urlparse(oauth_providers.providers[provider].get_authorization_url("st", "v")).query)
    assert "code_challenge" not in query


# ─── Steam answer binding ────────────────────────────────────────────────────

_STEAM_ID = "https://steamcommunity.com/openid/id/76561197960287930"


def _steam_answer(*, return_to: str, issued: datetime) -> str:
    return urlencode(
        {
            "openid.ns": "http://specs.openid.net/auth/2.0",
            "openid.mode": "id_res",
            "openid.op_endpoint": SteamOpenIDProvider.LOGIN_URL,
            "openid.claimed_id": _STEAM_ID,
            "openid.identity": _STEAM_ID,
            "openid.return_to": return_to,
            "openid.response_nonce": issued.strftime("%Y-%m-%dT%H:%M:%SZ") + "Kx1",
            "openid.assoc_handle": "1234567890",
            "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
            "openid.sig": "sig",
        }
    )


def _steam_exchange(answer: str, state: str):
    http = _Http(SimpleNamespace(status_code=200, text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"))
    return http, asyncio.run(SteamOpenIDProvider(http).exchange_code(answer, state=state, code_verifier="v"))


def test_steam_accepts_a_fresh_answer_returning_to_this_flows_state() -> None:
    answer = _steam_answer(return_to=SteamOpenIDProvider._return_to("mine"), issued=datetime.now(UTC))
    _http, token = _steam_exchange(answer, "mine")
    assert token == {"access_token": "76561197960287930"}


@pytest.mark.parametrize(
    "return_to, age",
    [
        pytest.param(SteamOpenIDProvider._return_to("theirs"), timedelta(0), id="other-state"),
        pytest.param(SteamOpenIDProvider._return_to("mine") + "&x=1", timedelta(0), id="extended-return-to"),
        pytest.param(SteamOpenIDProvider._return_to("mine"), timedelta(minutes=6), id="stale-nonce"),
    ],
)
def test_steam_rejects_answers_not_bound_to_this_flow_or_stale(return_to: str, age: timedelta) -> None:
    answer = _steam_answer(return_to=return_to, issued=datetime.now(UTC) - age)
    with pytest.raises(HTTPException) as exc_info:
        _steam_exchange(answer, "mine")
    assert exc_info.value.status_code == 400


# ─── provider tokens at rest ─────────────────────────────────────────────────


class _Connections:
    """``OAuthConnectionRepository`` stand-in: hands out the rows still needing a rewrite once."""

    def __init__(self, rows):
        self.pending = list(rows)

    async def lock_unsealed_tokens(self, session, *, kept_providers, limit):
        batch, self.pending = self.pending[:limit], self.pending[limit:]
        return batch


def test_startup_job_seals_kept_tokens_and_drops_the_rest() -> None:
    already = secretbox.encrypt("old", KEY)
    discord = SimpleNamespace(provider="discord", access_token="clear-at", refresh_token=already)
    twitch = SimpleNamespace(provider="twitch", access_token="tw", refresh_token=None)
    battlenet = SimpleNamespace(provider="battlenet", access_token="bn", refresh_token="bn-r")
    commits = []
    session = SimpleNamespace(commit=lambda: _async(commits.append(1)))
    service = OAuthAccountService(connections=_Connections([discord, twitch, battlenet]))

    changed = asyncio.run(service.seal_stored_tokens(session, batch_size=2))

    assert (changed, len(commits)) == (3, 2)  # batched, a commit per batch
    assert secretbox.decrypt(discord.access_token, KEY) == "clear-at"
    assert discord.refresh_token == already  # never sealed twice
    assert secretbox.decrypt(twitch.access_token, KEY) == "tw" and twitch.refresh_token is None
    assert (battlenet.access_token, battlenet.refresh_token) == (None, None)


def test_identity_refuses_to_start_without_a_key_while_discord_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oauth_token_encryption_key", None)
    monkeypatch.setattr(settings, "DISCORD_OAUTH_ENABLED", True)
    with pytest.raises(RuntimeError):
        OAuthAccountService().token_key()


def test_battlenet_tokens_are_never_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.oauth_accounts import _new_connection
    from tests._fakes import make_oauth_info

    conn = _new_connection(
        SimpleNamespace(id=1), make_oauth_info(provider="battlenet"), {"access_token": "a", "refresh_token": "r"}
    )
    assert (conn.access_token, conn.refresh_token) == (None, None)


class _GuildProvider:
    def __init__(self):
        self.tokens = []

    async def get_user_guilds(self, token):
        self.tokens.append(token)
        return []


def test_discord_guilds_opens_the_sealed_token() -> None:
    conn = SimpleNamespace(access_token=secretbox.encrypt("live-token", KEY), token_expires_at=None)
    provider = _GuildProvider()
    service = OAuthFlowService(
        connections=SimpleNamespace(list_by_user_providers=lambda *a, **k: _async([conn])),
        providers=SimpleNamespace(get=lambda name: provider),
    )
    result = asyncio.run(service.discord_guilds(object(), auth_user_id=1))
    assert result == {"guilds": [], "relink_required": False}
    assert provider.tokens == ["live-token"]
