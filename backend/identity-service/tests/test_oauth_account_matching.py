import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _ensure_test_env() -> None:
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "auth_test",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "JWT_SECRET_KEY": "test-secret",
        "DISCORD_CLIENT_ID": "discord-client",
        "DISCORD_CLIENT_SECRET": "discord-secret",
        "TWITCH_CLIENT_ID": "twitch-client",
        "TWITCH_CLIENT_SECRET": "twitch-secret",
        "BATTLENET_CLIENT_ID": "battlenet-client",
        "BATTLENET_CLIENT_SECRET": "battlenet-secret",
        "OAUTH_REDIRECT": "http://localhost:3000/auth/callback",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.models.identity.user import User  # noqa: E402
from src import schemas  # noqa: E402
from src.services.oauth_service import OAuthService  # noqa: E402


class _FakeScalarsResult:
    def __init__(self, values) -> None:
        self._values = list(values)

    def all(self):
        return list(self._values)

    def first(self):
        return self._values[0] if self._values else None

    def unique(self):
        seen = set()
        unique_values = []
        for value in self._values:
            key = getattr(value, "id", id(value))
            if key in seen:
                continue
            seen.add(key)
            unique_values.append(value)
        return _FakeScalarsResult(unique_values)


class _FakeExecuteResult:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = list(scalars or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        if self._scalar is None:
            raise AssertionError("Expected scalar result")
        return self._scalar

    def scalars(self):
        return _FakeScalarsResult(self._scalars)


class _FakeSession:
    def __init__(self, results: list[dict]) -> None:
        self._results = list(results)
        self.added = []
        self.refresh_calls = []
        self.commit_calls = 0
        self.flush_calls = 0

    async def execute(self, stmt):
        if not self._results:
            raise AssertionError("Unexpected execute() call")
        return _FakeExecuteResult(**self._results.pop(0))

    async def scalar(self, stmt):
        if not self._results:
            raise AssertionError("Unexpected scalar() call")
        return _FakeExecuteResult(**self._results.pop(0)).scalar_one_or_none()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1

    async def refresh(self, obj) -> None:
        self.refresh_calls.append(obj)


def test_find_existing_auth_user_ignores_email_only_match() -> None:
    """Fail-closed (review C1/C2): a matching email must NOT reuse an existing
    account. Reuse is anchored solely on a cryptographically-confirmed
    provider_user_id, so an email-only collision resolves to (None, None) and the
    caller provisions a brand-new user instead of silently taking over the
    account. (Previously an email match logged the caller straight into the
    victim's AuthUser — the core account-takeover primitive.)"""
    session = _FakeSession(
        [
            # _find_player_by_provider_record: provider_user_id subject match → none.
            # NOTE: there is deliberately NO email query anymore.
            {"scalars": []},
            # _find_unowned_player_by_handle: no player carries this handle → none.
            {"scalars": []},
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.DISCORD,
        provider_user_id="discord-123",
        email="victim@example.com",  # collides with an existing account's email
        username="attacker",
        display_name="Attacker",
        avatar_url="https://cdn.example/avatar.png",
        raw_data={"verified": True},
    )

    auth_user, matched_player = asyncio.run(OAuthService._find_existing_auth_user(session, oauth_info))

    assert auth_user is None
    assert matched_player is None


def test_find_existing_auth_user_links_unowned_player_by_handle() -> None:
    """Relaxed reconciliation: no verified provider_user_id yet, but an UNOWNED
    player already carries this provider handle (a shadow tournament identity).
    It is returned as matched_player so the caller links it instead of spawning a
    duplicate the admin has to merge by hand."""
    shadow = SimpleNamespace(id=500, auth_user_id=None)
    session = _FakeSession(
        [
            {"scalars": []},  # _find_player_by_provider_record: subject match → none
            {"scalars": [shadow]},  # _find_unowned_player_by_handle → the shadow player
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.BATTLENET,
        provider_user_id="bnet-new",
        email=None,
        username="Shadow#1234",
        display_name="Shadow#1234",
        raw_data={"battletag": "Shadow#1234"},
    )

    auth_user, matched_player = asyncio.run(OAuthService._find_existing_auth_user(session, oauth_info))

    assert auth_user is None
    assert matched_player is shadow


def test_find_unowned_player_by_handle_skips_already_owned_player() -> None:
    """Conservative guard: a player carrying the handle but already owned by
    some auth account is a merge conflict — never auto-claimed by a login with a
    different (unverified) provider subject."""
    owned = SimpleNamespace(id=501, auth_user_id=42)
    session = _FakeSession([{"scalars": [owned]}])
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.DISCORD,
        provider_user_id="discord-x",
        email=None,
        username="TakenHandle",
        display_name="TakenHandle",
        raw_data={},
    )

    result = asyncio.run(OAuthService._find_unowned_player_by_handle(session, oauth_info))

    assert result is None


def test_find_or_create_oauth_user_reuses_existing_user_by_provider_user_id() -> None:
    """The legit repeat path: a player already pinned to this exact
    provider_user_id (a verified social account) resolves to its linked auth
    user, and a fresh OAuthConnection is attached — no new user, no takeover."""
    existing_user = SimpleNamespace(id=21, email="existing@local", username="existing-user")
    # Player already linked to existing_user via players.user.auth_user_id and
    # pinned to this OAuth subject via a verified social account.
    player = SimpleNamespace(id=210, auth_user_id=existing_user.id)
    session = _FakeSession(
        [
            {"scalar": None},  # OAuthConnection lookup → none
            # _find_player_by_provider_record: provider_user_id subject match → player
            {"scalars": [player]},
            # _find_auth_user_for_player: player.auth_user_id set → AuthUser lookup
            {"scalar": existing_user},
            # matched_player.auth_user_id already == auth_user.id → no backfill query
            # _attach_verified_social_account: subject miss then fallback miss → no-op
            {"scalars": []},  # subject match → none
            {"scalar": None},  # players.user.auth_user_id fallback → none
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.BATTLENET,
        provider_user_id="bnet-123",
        email=None,
        username="Existing#1234",
        display_name="Existing#1234",
        raw_data={"battletag": "Existing#1234"},
    )

    auth_user = asyncio.run(
        OAuthService.find_or_create_oauth_user(
            session,
            oauth_info,
            {"access_token": "access-token", "expires_in": 3600},
        )
    )

    assert auth_user is existing_user
    assert session.flush_calls == 0
    assert len(session.added) == 1
    oauth_connection = session.added[0]
    assert oauth_connection.auth_user_id == existing_user.id
    assert oauth_connection.provider == "battlenet"
    assert oauth_connection.provider_user_id == "bnet-123"
    assert session.commit_calls == 1
    assert session.refresh_calls == [existing_user]


# ---------------------------------------------------------------------------
# _link_player_if_unowned: the shared guard behind both OAuth link sites.
# ---------------------------------------------------------------------------


def test_link_player_if_unowned_sets_link_when_unowned() -> None:
    player = SimpleNamespace(id=1, auth_user_id=None)
    auth_user = SimpleNamespace(id=99)

    linked = OAuthService._link_player_if_unowned(player, auth_user)

    assert linked is True
    assert player.auth_user_id == 99


def test_link_player_if_unowned_is_idempotent_for_same_owner() -> None:
    player = SimpleNamespace(id=1, auth_user_id=99)
    auth_user = SimpleNamespace(id=99)

    linked = OAuthService._link_player_if_unowned(player, auth_user)

    assert linked is False
    assert player.auth_user_id == 99


def test_link_player_if_unowned_never_overwrites_a_different_owner() -> None:
    """The conflict case (correction #9's guard): a player already linked to a
    different auth user is left untouched — never silently reassigned."""
    player = SimpleNamespace(id=1, auth_user_id=7)
    auth_user = SimpleNamespace(id=99)

    linked = OAuthService._link_player_if_unowned(player, auth_user)

    assert linked is False
    assert player.auth_user_id == 7


def test_find_or_create_oauth_user_provisions_own_player_when_matched_player_is_foreign_owned() -> None:
    """A brand-new OAuth signup whose provider-record match (e.g. battletag)
    belongs to a *different*, already-linked auth user must still end up with
    its own provisioned ``players.user`` row.

    Before the fix: ``_link_player_if_unowned`` correctly refused to steal the
    foreign player's link (returning False), but the surrounding branch only
    called ``ensure_player_for_auth_user`` in the `else` of `matched_player is
    not None`, so this new auth user silently ended up with NO player at all
    — violating the "every signup path provisions a players.user" invariant.
    """
    other_owner_id = 888
    foreign_player = SimpleNamespace(id=420, auth_user_id=other_owner_id)

    session = _FakeSession(
        [
            {"scalar": None},  # OAuthConnection lookup → none
            # _find_existing_auth_user is patched below (returns no auth_user,
            # but the foreign-owned player as matched_player)
            {"scalar": None},  # username-uniqueness check → free
            {"scalar": None},  # default "user" Role lookup → none present
            # (no user_roles insert query — it's skipped since default_role is None)
            # ensure_player_for_auth_user: existing-by-auth_user_id lookup → none
            {"scalar": None},
            # _attach_verified_social_account: no player found by provider record
            {"scalars": []},  # subject match
            {"scalars": []},  # handle match
            # falls back to players.user.auth_user_id lookup for the NEW auth_user
            # → the player we just provisioned via ensure_player_for_auth_user
            {"scalar": None},
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.BATTLENET,
        provider_user_id="bnet-foreign",
        email=None,
        username="Foreign#1234",
        display_name="Foreign#1234",
        raw_data={"battletag": "Foreign#1234"},
    )

    async def _fake_find_existing(_session, _oauth_info):
        return None, foreign_player

    with patch.object(OAuthService, "_find_existing_auth_user", staticmethod(_fake_find_existing)):
        auth_user = asyncio.run(
            OAuthService.find_or_create_oauth_user(
                session,
                oauth_info,
                {"access_token": "access-token", "expires_in": 3600},
            )
        )

    # The foreign player's link must be left untouched.
    assert foreign_player.auth_user_id == other_owner_id

    # A players.user row was provisioned for the new auth user (added to the
    # session, distinct from the foreign player, and owned by the new user).
    provisioned_players = [obj for obj in session.added if isinstance(obj, User) and obj is not foreign_player]
    assert len(provisioned_players) == 1
    assert provisioned_players[0].auth_user_id == auth_user.id
    assert provisioned_players[0] is not foreign_player


def test_find_or_create_oauth_user_never_overwrites_conflicting_player_link() -> None:
    """A race condition: between ``_find_existing_auth_user`` resolving its
    (auth_user, matched_player) pair and the backfill running, the player got
    linked to a *different* auth user (e.g. a concurrent request). The backfill
    must detect the mismatch and leave the existing link untouched rather than
    overwrite it — no flush attempted for the (non-)update."""
    existing_user = SimpleNamespace(id=31, email="conflict@local", username="conflict-user")
    other_owner_id = 777
    # Simulates the player having been linked to `other_owner_id` concurrently,
    # after _find_existing_auth_user already decided to pair it with existing_user.
    player = SimpleNamespace(id=310, auth_user_id=other_owner_id)
    session = _FakeSession(
        [
            {"scalar": None},  # OAuthConnection lookup → none
            # _attach_verified_social_account: no player found by provider record → no-op
            {"scalars": []},  # subject match
            {"scalars": []},  # handle match
            {"scalar": None},  # players.user.auth_user_id lookup for auth_user → none
        ]
    )
    oauth_info = schemas.OAuthUserInfo(
        provider=schemas.OAuthProvider.BATTLENET,
        provider_user_id="bnet-conflict",
        email=None,
        username="Conflict#1234",
        display_name="Conflict#1234",
        raw_data={"battletag": "Conflict#1234"},
    )

    async def _fake_find_existing(_session, _oauth_info):
        return existing_user, player

    with patch.object(OAuthService, "_find_existing_auth_user", staticmethod(_fake_find_existing)):
        auth_user = asyncio.run(
            OAuthService.find_or_create_oauth_user(
                session,
                oauth_info,
                {"access_token": "access-token", "expires_in": 3600},
            )
        )

    assert auth_user is existing_user
    # The player's link must remain pointed at its original (different) owner —
    # never silently reassigned to existing_user.
    assert player.auth_user_id == other_owner_id
    assert session.flush_calls == 0
