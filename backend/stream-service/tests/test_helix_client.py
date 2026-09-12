"""Decision table of the Helix app-token client, exercised without a network.

Each test here stands for a failure that is invisible in production:

- a comma-joined multi-value parameter returns an empty ``data`` array and no
  error, so every badge silently goes dark;
- an unbatched 150-channel request is rejected wholesale;
- an unpinned ``first`` silently truncates a 100-channel batch to 20;
- a 401 that is not retried after a token refresh disables polling for the token's
  whole remaining lifetime;
- an unsubstituted ``{width}x{height}`` thumbnail renders as a broken image.
"""

from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase

import httpx

from src.services import helix  # noqa: E402
from src.services.state import TOKEN_KEY  # noqa: E402

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_URL = "https://api.twitch.tv/helix"


def _stream_row(login: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "user_id": f"id-{login}",
        "user_login": login,
        "title": f"{login} on air",
        "game_name": "Overwatch 2",
        "viewer_count": 42,
        "thumbnail_url": f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-{{width}}x{{height}}.jpg",
        "started_at": "2026-08-16T12:00:00Z",
    }
    row.update(overrides)
    return row


def _ok(rows: list[dict[str, Any]], *, remaining: int | None = 799) -> httpx.Response:
    headers = {} if remaining is None else {"Ratelimit-Remaining": str(remaining)}
    return httpx.Response(200, json={"data": rows}, headers=headers)


class _Recorder:
    """Injected HTTP callable: replays canned responses, records every call."""

    def __init__(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        data: Any = None,
        headers: Any = None,
    ) -> httpx.Response:
        self.calls.append({"method": method, "url": url, "params": params, "data": data, "headers": headers})
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        return self._responses.pop(0)

    @property
    def gets(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["method"] == "GET"]

    @property
    def posts(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["method"] == "POST"]


class _FakeRedis:
    def __init__(self, **values: str) -> None:
        self.values: dict[str, str] = dict(values)
        self.deleted: list[str] = []
        self.expirations: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.expirations[key] = ex

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.deleted.append(key)


def _client(
    redis: Any,
    *,
    client_id: str | None = "cid",
    client_secret: str | None = "secret",
    helix_url: str = HELIX_URL,
    token_url: str = TOKEN_URL,
    request: helix.HelixRequest | None = None,
) -> helix.HelixClient:
    return helix.HelixClient(
        redis,
        client_id=client_id,
        client_secret=client_secret,
        helix_url=helix_url,
        token_url=token_url,
        request=request,
    )


def _query(call: dict[str, Any]) -> str:
    """The wire form of the request's params — what Twitch actually parses."""
    return str(httpx.QueryParams(call["params"]))


class BatchingTests(IsolatedAsyncioTestCase):
    async def test_over_hundred_logins_split_into_two_requests(self) -> None:
        logins = [f"streamer{i}" for i in range(150)]
        recorder = _Recorder(_ok([]), _ok([]))
        client = _client(_FakeRedis(), request=recorder)

        result = await client.get_live_streams(logins=logins, token="tok", batch_size=100)

        self.assertEqual(len(recorder.gets), 2)
        self.assertEqual(len([p for p in recorder.gets[0]["params"] if p[0] == "user_login"]), 100)
        self.assertEqual(len([p for p in recorder.gets[1]["params"] if p[0] == "user_login"]), 50)
        self.assertEqual(result.polled_logins, frozenset(login.casefold() for login in logins))

    async def test_batch_size_is_capped_at_the_helix_limit(self) -> None:
        recorder = _Recorder(_ok([]), _ok([]))
        client = _client(_FakeRedis(), request=recorder)

        await client.get_live_streams(
            logins=[f"s{i}" for i in range(120)],
            token="tok",
            batch_size=500,  # an operator-supplied value Helix would reject
        )

        self.assertEqual(len(recorder.gets), 2)

    async def test_first_is_pinned_to_the_batch_size(self) -> None:
        """Unset, Helix defaults to 20 and drops the tail of a 100-channel batch."""
        recorder = _Recorder(_ok([]))
        client = _client(_FakeRedis(), request=recorder)

        await client.get_live_streams(logins=[f"s{i}" for i in range(30)], token="tok")

        self.assertIn(("first", "30"), recorder.gets[0]["params"])


class QueryEncodingTests(IsolatedAsyncioTestCase):
    async def test_multi_value_params_repeat_instead_of_comma_joining(self) -> None:
        recorder = _Recorder(_ok([]))
        client = _client(_FakeRedis(), request=recorder)

        await client.get_live_streams(logins=["alpha", "beta"], token="tok")

        query = _query(recorder.gets[0])
        self.assertIn("user_login=alpha", query)
        self.assertIn("user_login=beta", query)
        # `?user_login=alpha,beta` is accepted by Helix and matches nothing.
        self.assertNotIn("alpha%2Cbeta", query)
        self.assertNotIn("alpha,beta", query)

    async def test_user_ids_and_logins_ride_in_one_request(self) -> None:
        recorder = _Recorder(_ok([]))
        client = _client(_FakeRedis(), request=recorder)

        await client.get_live_streams(logins=["alpha"], user_ids=["12345"], token="tok")

        query = _query(recorder.gets[0])
        self.assertEqual(len(recorder.gets), 1)
        self.assertIn("user_id=12345", query)
        self.assertIn("user_login=alpha", query)

    async def test_credentials_travel_in_headers(self) -> None:
        recorder = _Recorder(_ok([]))
        client = _client(_FakeRedis(), client_id="cid", request=recorder)

        await client.get_live_streams(logins=["alpha"], token="tok")

        self.assertEqual(recorder.gets[0]["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(recorder.gets[0]["headers"]["Client-Id"], "cid")


class SnapshotTests(IsolatedAsyncioTestCase):
    async def test_thumbnail_placeholders_are_substituted_in_the_client(self) -> None:
        recorder = _Recorder(_ok([_stream_row("caster")]))
        client = _client(_FakeRedis(), request=recorder)

        result = await client.get_live_streams(logins=["caster"], token="tok")

        snapshot = result.snapshots[0]
        assert snapshot.thumbnail_url is not None
        self.assertIn("440x248", snapshot.thumbnail_url)
        self.assertNotIn("{width}", snapshot.thumbnail_url)
        self.assertNotIn("{height}", snapshot.thumbnail_url)

    async def test_channel_is_lowercased_and_url_derived(self) -> None:
        recorder = _Recorder(_ok([_stream_row("CasterName")]))
        client = _client(_FakeRedis(), request=recorder)

        result = await client.get_live_streams(logins=["CasterName"], token="tok")

        self.assertEqual(result.snapshots[0].channel, "castername")
        self.assertEqual(result.snapshots[0].url, "https://twitch.tv/castername")
        self.assertEqual(result.snapshots[0].platform, "twitch")

    async def test_absent_channel_is_simply_missing_from_the_result(self) -> None:
        """Helix returns only live channels — there is no ``is_live`` field to read."""
        recorder = _Recorder(_ok([_stream_row("live_one")]))
        client = _client(_FakeRedis(), request=recorder)

        result = await client.get_live_streams(logins=["live_one", "offline_one"], token="tok")

        self.assertEqual([s.channel for s in result.snapshots], ["live_one"])
        self.assertEqual(result.polled_logins, frozenset({"live_one", "offline_one"}))


class RateLimitTests(IsolatedAsyncioTestCase):
    async def test_429_raises_with_the_reset_timestamp(self) -> None:
        recorder = _Recorder(httpx.Response(429, json={}, headers={"Ratelimit-Reset": "1780000000"}))
        client = _client(_FakeRedis(), request=recorder)

        with self.assertRaises(helix.HelixRateLimited) as caught:
            await client.get_live_streams(logins=["alpha"], token="tok")

        self.assertEqual(caught.exception.reset_at, 1780000000)

    async def test_remaining_below_the_floor_truncates_the_batch_loop(self) -> None:
        recorder = _Recorder(_ok([], remaining=5), _ok([]))
        client = _client(_FakeRedis(), request=recorder)

        result = await client.get_live_streams(
            logins=[f"s{i}" for i in range(150)],
            token="tok",
            batch_size=100,
            ratelimit_floor=100,
        )

        self.assertEqual(len(recorder.gets), 1)
        self.assertTrue(result.truncated)
        self.assertEqual(result.ratelimit_remaining, 5)
        self.assertEqual(len(result.polled_logins), 100)

    async def test_headroom_keeps_the_loop_running(self) -> None:
        recorder = _Recorder(_ok([], remaining=700), _ok([], remaining=690))
        client = _client(_FakeRedis(), request=recorder)

        result = await client.get_live_streams(logins=[f"s{i}" for i in range(150)], token="tok", batch_size=100)

        self.assertEqual(len(recorder.gets), 2)
        self.assertFalse(result.truncated)


class TokenTests(IsolatedAsyncioTestCase):
    async def test_missing_client_id_raises_not_configured_without_a_request(self) -> None:
        recorder = _Recorder()
        client = _client(_FakeRedis(), client_id="", client_secret="secret", request=recorder)

        with self.assertRaises(helix.HelixNotConfigured):
            await client.get_app_token()

        self.assertEqual(recorder.calls, [])

    async def test_missing_secret_raises_not_configured(self) -> None:
        client = _client(_FakeRedis(), client_id="cid", client_secret=None, request=_Recorder())

        with self.assertRaises(helix.HelixNotConfigured):
            await client.get_app_token()

    async def test_token_is_cached_with_a_renewal_margin(self) -> None:
        redis = _FakeRedis()
        recorder = _Recorder(httpx.Response(200, json={"access_token": "app-token", "expires_in": 5000}))
        client = _client(redis, request=recorder)

        token = await client.get_app_token()

        self.assertEqual(token, "app-token")
        self.assertEqual(redis.values[TOKEN_KEY], "app-token")
        self.assertEqual(redis.expirations[TOKEN_KEY], 5000 - 60)
        self.assertEqual(recorder.posts[0]["data"]["grant_type"], "client_credentials")

    async def test_cached_token_skips_the_token_endpoint(self) -> None:
        redis = _FakeRedis(**{TOKEN_KEY: "cached"})
        recorder = _Recorder()
        client = _client(redis, request=recorder)

        token = await client.get_app_token()

        self.assertEqual(token, "cached")
        self.assertEqual(recorder.calls, [])

    async def test_rejected_credentials_surface_as_unauthorized(self) -> None:
        recorder = _Recorder(httpx.Response(400, json={"message": "invalid client"}))
        client = _client(_FakeRedis(), client_secret="wrong", request=recorder)

        with self.assertRaises(helix.HelixUnauthorized):
            await client.get_app_token()


class TokenRefreshRetryTests(IsolatedAsyncioTestCase):
    async def test_401_drops_the_cached_token_and_retries_once(self) -> None:
        redis = _FakeRedis(**{TOKEN_KEY: "stale"})
        recorder = _Recorder(
            httpx.Response(401, json={}),
            httpx.Response(200, json={"access_token": "fresh", "expires_in": 5000}),
            _ok([_stream_row("caster")]),
        )
        client = _client(redis, request=recorder)

        result = await client.fetch_live_streams(logins=["caster"])

        self.assertEqual([s.channel for s in result.snapshots], ["caster"])
        self.assertEqual(redis.deleted, [TOKEN_KEY])
        self.assertEqual(len(recorder.gets), 2)
        self.assertEqual(recorder.gets[0]["headers"]["Authorization"], "Bearer stale")
        self.assertEqual(recorder.gets[1]["headers"]["Authorization"], "Bearer fresh")

    async def test_second_401_raises_unauthorized(self) -> None:
        redis = _FakeRedis(**{TOKEN_KEY: "stale"})
        recorder = _Recorder(
            httpx.Response(401, json={}),
            httpx.Response(200, json={"access_token": "fresh", "expires_in": 5000}),
            httpx.Response(401, json={}),
        )
        client = _client(redis, request=recorder)

        with self.assertRaises(helix.HelixUnauthorized):
            await client.fetch_live_streams(logins=["caster"])

        self.assertEqual(len(recorder.gets), 2)


class TransportTests(IsolatedAsyncioTestCase):
    async def test_transport_failure_becomes_unavailable(self) -> None:
        async def _boom(*args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectTimeout("proxy is down")

        client = _client(_FakeRedis(), request=_boom)

        with self.assertRaises(helix.HelixUnavailable):
            await client.get_live_streams(logins=["alpha"], token="tok")

    async def test_5xx_becomes_unavailable(self) -> None:
        client = _client(_FakeRedis(), request=_Recorder(httpx.Response(503, json={})))

        with self.assertRaises(helix.HelixUnavailable):
            await client.get_live_streams(logins=["alpha"], token="tok")
