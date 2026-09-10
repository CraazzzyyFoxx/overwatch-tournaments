"""Behaviour of one poll tick, with Twitch and Redis faked.

The four things that go wrong here are all invisible in a happy-path test:

- publishing on every tick instead of on a change, which herds hundreds of
  spectators into a refetch every 60 seconds;
- publishing per channel instead of per tournament, which multiplies that herd by
  the number of casters;
- publishing for a hidden tournament, which tells an anonymous subscriber that a
  preview tournament exists;
- writing a live set built from a rate-limited, partial Helix answer, which marks
  channels nobody asked about as offline.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.schemas.settings import StreamCollectionConfig  # noqa: E402
from shared.services.realtime import Resource, Scope  # noqa: E402
from src.services import helix, poller  # noqa: E402
from src.services.state import StreamStateStore  # noqa: E402
from src.services.targets import ParticipantChannel  # noqa: E402


@dataclass(frozen=True)
class _Link:
    url: str
    label: str | None = None


@dataclass(frozen=True)
class _Tournament:
    tournament_id: int
    workspace_id: int
    is_hidden: bool


class _FakePipeline:
    def __init__(self, store: dict[str, Any], ttls: dict[str, int]) -> None:
        self._store = store
        self._ttls = ttls
        self._ops: list[tuple[str, Any, Any]] = []

    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def delete(self, key: str) -> None:
        self._ops.append(("delete", key, None))

    def hset(self, key: str, mapping: dict[str, str] | None = None) -> None:
        self._ops.append(("hset", key, mapping))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(("expire", key, ttl))

    async def execute(self) -> None:
        for op, key, value in self._ops:
            if op == "delete":
                self._store.pop(key, None)
            elif op == "hset":
                self._store.setdefault(key, {}).update(value or {})
            elif op == "expire":
                self._ttls[key] = value
        self._ops.clear()


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}
        self.strings: dict[str, str] = {}

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        return _FakePipeline(self.hashes, self.ttls)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.strings[key] = value

    async def delete(self, key: str) -> None:
        self.strings.pop(key, None)
        self.hashes.pop(key, None)


def _snapshot(login: str, user_id: str | None = None) -> helix.StreamSnapshot:
    return helix.StreamSnapshot(
        channel=login,
        user_id=user_id or f"id-{login}",
        url=f"https://twitch.tv/{login}",
        title="on air",
        game_name="Overwatch 2",
        viewer_count=12,
        thumbnail_url=f"https://static-cdn.jtvnw.net/{login}-440x248.jpg",
        started_at="2026-08-16T12:00:00Z",
    )


class _Fetcher:
    """Stands in for ``HelixClient.fetch_live_streams``; records how it was called."""

    def __init__(self, result: helix.HelixBatchResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> helix.HelixBatchResult:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class _FakeTargetsService:
    """Stands in for ``StreamTargetsService``; wires the poll tick to plain
    in-memory data instead of the shared repositories."""

    def __init__(self) -> None:
        self.tournaments: list[_Tournament] = []
        self.participants: dict[int, list[ParticipantChannel]] = {}
        self.links: dict[int, list[_Link]] = {}

    async def active_tournaments(self, session: Any) -> list[_Tournament]:
        return self.tournaments

    async def participant_channels_bulk(self, session: Any, tournament_ids: list[int]) -> dict[int, list[Any]]:
        return {tid: self.participants.get(tid, []) for tid in tournament_ids}

    async def official_stream_links_bulk(self, session: Any, tournament_ids: list[int]) -> dict[int, list[Any]]:
        return {tid: self.links.get(tid, []) for tid in tournament_ids}


class _FakeSession:
    """Records what the tick staged and that the tick committed it.

    The tick announces through ``emit``, so what a subscriber eventually sees is
    decided by the staged scope/resource/payload plus the commit. How staging
    turns into a published frame is pinned once, in
    ``backend/tests/test_realtime_emit.py``.
    """

    def __init__(self) -> None:
        self.staged: list[dict[str, Any]] = []
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _TickCase(IsolatedAsyncioTestCase):
    """Wires the target queries to plain in-memory data."""

    def setUp(self) -> None:
        self.redis = _FakeRedis()
        self.cfg = StreamCollectionConfig(enabled=True, interval_seconds=60, batch_size=100)
        self.targets = _FakeTargetsService()
        self.session = _FakeSession()

    def _tournament(self, tournament_id: int, *, hidden: bool = False) -> None:
        self.targets.tournaments.append(_Tournament(tournament_id=tournament_id, workspace_id=1, is_hidden=hidden))

    def _participant(
        self, tournament_id: int, login: str, *, player_id: int = 5, source: str = "self_declared"
    ) -> None:
        self.targets.participants.setdefault(tournament_id, []).append(
            ParticipantChannel(
                player_id=player_id,
                login=login,
                provider_user_id=f"id-{login}" if source == "verified" else None,
                source=source,
            )
        )

    def _live(self, tournament_id: int) -> dict[str, dict[str, Any]]:
        return {
            field: json.loads(body)
            for field, body in self.redis.hashes.get(StreamStateStore.live_key(tournament_id), {}).items()
        }

    async def _run(self, fetch: _Fetcher, *, cfg: StreamCollectionConfig | None = None) -> int:
        async def _record(_session: Any, **kwargs: Any) -> None:
            self.session.staged.append(kwargs)

        with patch.object(poller, "emit", _record):
            return await poller.run_poll_tick(
                self.session, self.redis, cfg or self.cfg, fetch=fetch, targets=self.targets
            )


class GateTests(_TickCase):
    async def test_disabled_setting_never_reaches_helix(self) -> None:
        self._tournament(7)
        self._participant(7, "caster")
        fetcher = _Fetcher(helix.HelixBatchResult(snapshots=[]))

        processed = await self._run(fetcher, cfg=StreamCollectionConfig(enabled=False))

        self.assertEqual(processed, 0)
        self.assertEqual(fetcher.calls, [])
        # Not even the cursor moves: a disabled poller has not "run".
        self.assertNotIn("stream:poll:last_run", self.redis.strings)

    async def test_successful_tick_records_the_cursor(self) -> None:
        self._tournament(7)
        self._participant(7, "caster")

        await self._run(_Fetcher(_batch(["caster"], logins=["caster"])))

        self.assertIn("stream:poll:last_run", self.redis.strings)

    async def test_helix_outage_still_records_the_cursor(self) -> None:
        """Otherwise a Twitch outage turns the 30s heartbeat into a retry storm."""
        self._tournament(7)
        self._participant(7, "caster")

        processed = await self._run(_Fetcher(error=helix.HelixUnavailable("boom")))

        self.assertEqual(processed, 0)
        self.assertIn("stream:poll:last_run", self.redis.strings)
        self.assertEqual(self.session.staged, [])

    async def test_missing_credentials_write_nothing(self) -> None:
        self._tournament(7)
        self._participant(7, "caster")
        self.redis.hashes[StreamStateStore.live_key(7)] = {"twitch:caster": json.dumps({"channel": "caster"})}

        processed = await self._run(_Fetcher(error=helix.HelixNotConfigured("no creds")))

        self.assertEqual(processed, 0)
        # An unanswered request is not "everybody went offline".
        self.assertEqual(list(self._live(7)), ["twitch:caster"])


class PublishTests(_TickCase):
    async def test_channel_going_live_publishes_exactly_once_per_tournament(self) -> None:
        self._tournament(7)
        self._participant(7, "castera")
        self._participant(7, "casterb")

        await self._run(_Fetcher(_batch(["castera", "casterb"], logins=["castera", "casterb"])))

        (staged,) = self.session.staged
        self.assertEqual(Scope.tournament(7), staged["scope"])
        self.assertEqual([Resource.TOURNAMENT_STREAMS], staged["invalidates"])
        data = staged["data"]
        self.assertEqual("streams", data.domain)
        self.assertEqual("stream.updated", data.event_type)
        # No replay cursor: a reconnecting spectator refetches the RPC, which
        # is also the only thing that applies the visibility rules.
        self.assertFalse(data.durable)
        self.assertEqual({"tournament_id": 7, "live_count": 2}, dict(data.payload))
        self.assertEqual(1, self.session.commits)

    async def test_unchanged_live_set_does_not_publish(self) -> None:
        self._tournament(7)
        self._participant(7, "caster")
        self.redis.hashes[StreamStateStore.live_key(7)] = {"twitch:caster": json.dumps({"channel": "caster"})}

        await self._run(_Fetcher(_batch(["caster"], logins=["caster"])))

        self.assertEqual(self.session.staged, [])
        # Still rewritten: viewer count, title and the TTL all go stale otherwise.
        self.assertEqual(self.redis.ttls[StreamStateStore.live_key(7)], 3 * self.cfg.interval_seconds)
        self.assertEqual(self._live(7)["twitch:caster"]["viewer_count"], 12)

    async def test_channel_going_offline_publishes_and_clears(self) -> None:
        self._tournament(7)
        self._participant(7, "caster")
        self.redis.hashes[StreamStateStore.live_key(7)] = {"twitch:caster": json.dumps({"channel": "caster"})}

        await self._run(_Fetcher(_batch([], logins=["caster"])))

        (staged,) = self.session.staged
        self.assertEqual(0, staged["data"].payload["live_count"])
        self.assertEqual(self._live(7), {})

    async def test_hidden_tournament_is_stored_but_never_announced(self) -> None:
        self._tournament(7, hidden=True)
        self._participant(7, "caster")

        await self._run(_Fetcher(_batch(["caster"], logins=["caster"])))

        self.assertEqual(list(self._live(7)), ["twitch:caster"])
        self.assertEqual(self.session.staged, [])


class FanOutTests(_TickCase):
    async def test_channel_shared_by_two_tournaments_is_polled_once(self) -> None:
        self._tournament(7)
        self._tournament(8)
        self._participant(7, "caster")
        self._participant(8, "caster")

        fetcher = _Fetcher(_batch(["caster"], logins=["caster"]))
        processed = await self._run(fetcher)

        self.assertEqual(processed, 2)
        self.assertEqual(fetcher.calls[0]["logins"], ["caster"])
        self.assertEqual(list(self._live(7)), ["twitch:caster"])
        self.assertEqual(list(self._live(8)), ["twitch:caster"])
        self.assertEqual(len(self.session.staged), 2)

    async def test_verified_participants_are_queried_by_stable_id(self) -> None:
        self._tournament(7)
        self._participant(7, "caster", source="verified")

        fetcher = _Fetcher(_batch(["caster"], user_ids=["id-caster"]))
        await self._run(fetcher)

        self.assertEqual(fetcher.calls[0]["user_ids"], ["id-caster"])
        self.assertEqual(fetcher.calls[0]["logins"], [])

    async def test_official_link_is_polled_and_attributed_to_the_official_source(self) -> None:
        self._tournament(7)
        self.targets.links[7] = [_Link(url="https://twitch.tv/OWTMain"), _Link(url="https://youtube.com/@owt")]

        fetcher = _Fetcher(_batch(["owtmain"], logins=["owtmain"]))
        await self._run(fetcher)

        # The YouTube link has no live detection and must not be asked about.
        self.assertEqual(fetcher.calls[0]["logins"], ["owtmain"])
        entry = self._live(7)["twitch:owtmain"]
        self.assertEqual(entry["source"], "official")
        self.assertIsNone(entry["player_id"])

    async def test_snapshot_carries_tournament_context(self) -> None:
        self._tournament(7)
        self._participant(7, "caster", player_id=99, source="verified")

        await self._run(_Fetcher(_batch(["caster"], user_ids=["id-caster"])))

        entry = self._live(7)["twitch:caster"]
        self.assertEqual(entry["player_id"], 99)
        self.assertEqual(entry["source"], "verified")
        self.assertEqual(entry["platform"], "twitch")
        self.assertEqual(entry["url"], "https://twitch.tv/caster")


class RateLimitGateTests(_TickCase):
    async def test_uncovered_tournament_is_left_untouched(self) -> None:
        self._tournament(7)
        self._tournament(8)
        self._participant(7, "castera")
        self._participant(8, "casterb")
        self.redis.hashes[StreamStateStore.live_key(8)] = {"twitch:casterb": json.dumps({"channel": "casterb"})}

        # The gate stopped after the batch covering tournament 7 only.
        result = helix.HelixBatchResult(
            snapshots=[_snapshot("castera")],
            ratelimit_remaining=5,
            polled_logins=frozenset({"castera"}),
            truncated=True,
        )
        processed = await self._run(_Fetcher(result))

        self.assertEqual(processed, 1)
        self.assertEqual(list(self._live(7)), ["twitch:castera"])
        # Never polled — must not be recorded as offline.
        self.assertEqual(list(self._live(8)), ["twitch:casterb"])
        self.assertEqual([Scope.tournament(7)], [row["scope"] for row in self.session.staged])


class PollStatusTests(_TickCase):
    """What the admin health panel reads.

    The tick swallows every Helix failure on purpose — an outage must not kill the
    scheduler — so the recorded status is the ONLY way an operator can tell "polling
    works" from "Twitch rejected the credentials". Both otherwise look like a
    tournament page with no live badges.
    """

    async def _status(self) -> dict[str, Any]:
        recorded = await StreamStateStore(self.redis).read_poll_status()
        assert recorded is not None, "the tick recorded no status at all"
        return recorded

    async def test_successful_tick_records_ok_with_counts(self) -> None:
        self._tournament(7)
        self._participant(7, "castera")
        self._participant(7, "casterb")

        await self._run(_Fetcher(_batch(["castera"], logins=["castera", "casterb"])))

        recorded = await self._status()
        self.assertEqual(recorded["status"], "ok")
        self.assertEqual(recorded["tournaments_active"], 1)
        self.assertEqual(recorded["tournaments_updated"], 1)
        self.assertEqual(recorded["channels_polled"], 2)
        self.assertEqual(recorded["live_channels"], 1)
        self.assertEqual(recorded["ratelimit_remaining"], 700)
        self.assertIsInstance(recorded["ran_at"], float)

    async def test_rejected_credentials_are_named_not_swallowed(self) -> None:
        """The one diagnosis the panel exists for: creds present, Twitch said no."""
        self._tournament(7)
        self._participant(7, "caster")

        await self._run(_Fetcher(error=helix.HelixUnauthorized("nope")))

        self.assertEqual((await self._status())["status"], "unauthorized")

    async def test_missing_credentials_are_distinguishable_from_rejected_ones(self) -> None:
        self._tournament(7)
        self._participant(7, "caster")

        await self._run(_Fetcher(error=helix.HelixNotConfigured("no creds")))

        self.assertEqual((await self._status())["status"], "not_configured")

    async def test_no_active_tournaments_is_empty_not_a_failure(self) -> None:
        await self._run(_Fetcher(_batch([])))

        recorded = await self._status()
        self.assertEqual(recorded["status"], "empty")
        self.assertEqual(recorded["tournaments_active"], 0)

    async def test_truncated_poll_says_so(self) -> None:
        self._tournament(7)
        self._participant(7, "caster")
        result = helix.HelixBatchResult(
            snapshots=[_snapshot("caster")],
            ratelimit_remaining=40,
            polled_logins=frozenset({"caster"}),
            truncated=True,
        )

        await self._run(_Fetcher(result))

        recorded = await self._status()
        self.assertEqual(recorded["status"], "truncated")
        self.assertEqual(recorded["ratelimit_remaining"], 40)

    async def test_disabled_setting_records_nothing(self) -> None:
        """A disabled poller has no outcome to report; the panel reads `enabled`
        from the settings row instead and says "paused", not "never ran"."""
        self._tournament(7)
        self._participant(7, "caster")

        await self._run(_Fetcher(_batch([])), cfg=StreamCollectionConfig(enabled=False))

        self.assertIsNone(await StreamStateStore(self.redis).read_poll_status())


def _batch(
    live: list[str],
    *,
    logins: list[str] | None = None,
    user_ids: list[str] | None = None,
) -> helix.HelixBatchResult:
    return helix.HelixBatchResult(
        snapshots=[_snapshot(login) for login in live],
        ratelimit_remaining=700,
        polled_logins=frozenset(logins or []),
        polled_user_ids=frozenset(user_ids or []),
    )
