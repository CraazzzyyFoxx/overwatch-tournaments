"""LoL rank collection decisions and fetches against fakes (no network); seeding and the fetch's reads and writes
against the test DB inside one rolled-back transaction."""

from __future__ import annotations

import asyncio
import itertools
import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import SocialProvider, normalize_social_handle
from shared.disciplines.lol import collector
from shared.models.ranks.rank import RankFetchLog, UserRankSnapshot
from shared.schemas.settings import RankCollectionConfig, settings_schema
from shared.testing import create_test_async_engine
from shared.testing.db import ensure_test_postgres

SOLO = {"queueType": "RANKED_SOLO_5x5", "tier": "DIAMOND", "rank": "I", "leaguePoints": 75, "wins": 120, "losses": 98}
FLEX = {"queueType": "RANKED_FLEX_SR", "tier": "MASTER", "rank": "I", "leaguePoints": 40, "wins": 3, "losses": 1}
ARENA = {"queueType": "CHERRY", "tier": "", "rank": "", "leaguePoints": 0, "wins": 9, "losses": 9}
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def _state(**kw):
    base = {
        "status": "pending",
        "consecutive_failures": 0,
        "last_checked_at": None,
        "last_success_at": None,
        "next_eligible_at": None,
        "last_error": None,
        "handle": "Old#EUW",
        "external_id": None,
        "region": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_league_entries_map_to_solo_and_flex_and_ignore_other_queues() -> None:
    ranks = collector.queue_ranks([SOLO, FLEX, ARENA])
    assert ranks == {
        "solo": collector.QueueRank("solo", "DIAMOND", 1, 75, 120, 98, 2775, True),
        "flex": collector.QueueRank("flex", "MASTER", None, 40, 3, 1, 2840, True),
    }


def test_only_changed_queues_are_written_and_a_lost_rank_writes_one_unranked_row() -> None:
    latest = {
        "solo": collector.QueueRank("solo", "DIAMOND", 1, 75, 120, 98, 2775, True),
        "flex": collector.QueueRank("flex", "GOLD", 2, 10, 1, 1, 1410, True),
    }
    assert collector.changed_queue_ranks({"solo": latest["solo"]}, latest) == [
        collector.QueueRank("flex", None, None, None, None, None, None, False)
    ]
    unranked = {"flex": collector.QueueRank("flex", None, None, None, None, None, None, False)}
    assert collector.changed_queue_ranks({}, unranked) == []


def test_ok_reschedules_on_the_interval_and_resets_failures() -> None:
    state = _state(consecutive_failures=3)
    collector.mark_ok(state, now=NOW, config=collector.LolRankCollectionConfig(jitter_fraction=0))
    assert (state.status, state.consecutive_failures, state.last_success_at) == ("ok", 0, NOW)
    assert state.next_eligible_at == NOW + timedelta(seconds=21600)


def test_not_found_waits_eight_intervals() -> None:
    state = _state()
    collector.mark_not_found(state, now=NOW, config=collector.LolRankCollectionConfig(jitter_fraction=0))
    assert (state.status, state.next_eligible_at) == ("not_found", NOW + timedelta(seconds=8 * 21600))


def test_a_transient_failure_backs_off_capped_and_never_disables() -> None:
    state = _state(consecutive_failures=40)
    config = collector.LolRankCollectionConfig()
    collector.mark_failure(state, now=NOW, config=config, status="error", error="Riot API answered 503", transient=True)
    assert (state.status, state.next_eligible_at) == ("error", NOW + timedelta(hours=6))


def test_a_permanent_failure_disables_after_the_configured_count() -> None:
    state = _state(consecutive_failures=4)
    collector.mark_failure(
        state,
        now=NOW,
        config=collector.LolRankCollectionConfig(),
        status="error",
        error=collector.INVALID_RIOT_ID_ERROR,
        transient=False,
    )
    assert (state.status, state.next_eligible_at, state.consecutive_failures) == ("disabled", None, 5)


def test_league_defaults_and_the_settings_key_validate_with_the_collector_shape() -> None:
    config = collector.LolRankCollectionConfig()
    assert (config.enabled, config.interval_seconds, config.rate_limit_per_minute, config.scope) == (
        False,
        21600,
        50,
        "all",
    )
    assert settings_schema(collector.SETTINGS_KEY) is collector.LolRankCollectionConfig
    assert settings_schema("parser.rank_collection") is RankCollectionConfig
    assert settings_schema("chess.rank_collection") is RankCollectionConfig  # no module owns it: the generic shape
    assert settings_schema("nope") is None


def test_league_needs_one_fetch_worth_of_requests_a_minute_and_overwatch_keeps_its_bounds() -> None:
    league = settings_schema(collector.SETTINGS_KEY)
    with pytest.raises(ValidationError):
        league.model_validate({"rate_limit_per_minute": 1})
    assert league.model_validate({"rate_limit_per_minute": collector.REQUESTS_PER_FETCH}).rate_limit_per_minute == 2
    assert (
        settings_schema("parser.rank_collection").model_validate({"rate_limit_per_minute": 1}).rate_limit_per_minute
        == 1
    )


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)

    async def incr(self, key):
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        return int(self.values[key])

    async def expire(self, key, seconds):
        self.expiry[key] = seconds


class _Session:
    def __init__(self) -> None:
        self.added: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row) -> None:
        self.added.append(row)

    def add_all(self, rows) -> None:
        self.added.extend(rows)

    async def commit(self) -> None:
        return None


class _Http:
    def __init__(self, routes) -> None:
        self.routes, self.calls = routes, []

    async def get(self, url):
        self.calls.append(url)
        status, body, headers = self.routes.get(url, (404, {}, None))
        return httpx.Response(status, json=body, headers=headers or {}, request=httpx.Request("GET", f"https://h{url}"))


def _arrange(monkeypatch, state):
    monkeypatch.setattr(
        collector,
        "collection_config",
        AsyncMock(return_value=collector.LolRankCollectionConfig(enabled=True, jitter_fraction=0)),
    )
    monkeypatch.setattr(
        collector, "_load_target", AsyncMock(return_value=collector._Target(10, 7, "Old#EUW", "p1", None))
    )
    monkeypatch.setattr(collector, "ensure_state", AsyncMock(return_value=state))
    monkeypatch.setattr(collector, "_latest_queue_ranks", AsyncMock(return_value={}))
    monkeypatch.setattr(collector, "_rename", AsyncMock(return_value=True))
    session = _Session()
    return session, (lambda: session)


def test_a_fetch_writes_changed_queues_renames_and_reschedules(monkeypatch) -> None:
    state = _state()
    session, factory = _arrange(monkeypatch, state)
    http = _Http(
        {
            "/riot/account/v1/region/by-game/lol/by-puuid/p1": (200, {"region": "EUW1"}, None),
            "/riot/account/v1/accounts/by-puuid/p1": (200, {"puuid": "p1", "gameName": "New", "tagLine": "EUW"}, None),
            "https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/p1": (200, [SOLO, ARENA], None),
        }
    )
    redis = _Redis()
    asyncio.run(collector.process_fetch({"social_account_id": 10}, redis=redis, http=http, session_factory=factory))
    snapshot = next(row for row in session.added if isinstance(row, UserRankSnapshot))
    assert (
        snapshot.discipline,
        snapshot.queue,
        snapshot.division,
        snapshot.tier,
        snapshot.lp,
        snapshot.wins,
        snapshot.losses,
        snapshot.rank_value,
        snapshot.handle,
        snapshot.role,
        snapshot.platform,
    ) == ("lol", "solo", "DIAMOND", 1, 75, 120, 98, 2775, "New#EUW", None, None)
    assert (state.status, state.external_id, state.region, state.handle) == ("ok", "p1", "euw1", "New#EUW")
    log = next(row for row in session.added if isinstance(row, RankFetchLog))
    assert (log.discipline, log.status, log.snapshots_written) == ("lol", "ok", 1)
    assert not any(key.startswith("lol_rank:fetch:") for key in redis.values)


def test_a_429_sets_the_global_cooldown_and_backs_off(monkeypatch) -> None:
    state = _state()
    session, factory = _arrange(monkeypatch, state)
    http = _Http({"/riot/account/v1/region/by-game/lol/by-puuid/p1": (429, {}, {"Retry-After": "30"})})
    redis = _Redis()
    asyncio.run(collector.process_fetch({"social_account_id": 10}, redis=redis, http=http, session_factory=factory))
    assert (redis.values.get(collector.COOLDOWN_KEY), redis.expiry[collector.COOLDOWN_KEY]) == ("1", 30)
    assert state.status == "rate_limited" and state.consecutive_failures == 1
    assert next(row for row in session.added if isinstance(row, RankFetchLog)).status == "rate_limited"


@pytest.mark.parametrize(
    ("re_resolve", "status", "failures"),
    [
        ((200, {"puuid": "p1"}, None), "error", 1),  # the re-resolved PUUID is rejected too
        ((404, {}, None), "not_found", 0),
        ((429, {}, {"Retry-After": "30"}), "rate_limited", 1),
    ],
)
def test_a_rejected_puuid_is_forgotten_however_its_re_resolve_ends(monkeypatch, re_resolve, status, failures) -> None:
    state = _state(external_id="p1", region="euw1")
    session, factory = _arrange(monkeypatch, state)
    http = _Http(
        {
            "/riot/account/v1/region/by-game/lol/by-puuid/p1": (400, {}, None),
            "/riot/account/v1/accounts/by-riot-id/Old/EUW": re_resolve,
        }
    )
    redis = _Redis()
    asyncio.run(collector.process_fetch({"social_account_id": 10}, redis=redis, http=http, session_factory=factory))
    assert (state.status, state.external_id, state.region, state.consecutive_failures) == (status, None, None, failures)
    assert next(row for row in session.added if isinstance(row, RankFetchLog)).status == status
    assert (collector.COOLDOWN_KEY in redis.values) is (status == "rate_limited")


#: An unplatformed account's fetch: region, Riot ID, league entries — three requests.
_THREE_REQUESTS = {
    "/riot/account/v1/region/by-game/lol/by-puuid/p1": (200, {"region": "EUW1"}, None),
    "/riot/account/v1/accounts/by-puuid/p1": (200, {"puuid": "p1", "gameName": "Old", "tagLine": "EUW"}, None),
    "https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/p1": (200, [SOLO], None),
}


def _budget(monkeypatch, limit: int, used: int = 0) -> _Redis:
    """A per-minute budget of ``limit`` requests, ``used`` of them already spent by other fetches this minute."""
    config = collector.LolRankCollectionConfig(enabled=True, jitter_fraction=0, rate_limit_per_minute=limit)
    monkeypatch.setattr(collector, "collection_config", AsyncMock(return_value=config))
    monkeypatch.setattr(collector, "_now", lambda: NOW)  # minute start: the window resets in 60 s
    redis = _Redis()
    redis.values[f"lol_rank:rl:{int(NOW.timestamp() // 60)}"] = str(used)
    return redis


@pytest.mark.parametrize(("limit", "used"), [(2, 0), (5, 4), (3, 3)])
def test_the_budget_bounds_every_outbound_request_and_defers_the_account_without_a_failure(
    monkeypatch, limit, used
) -> None:
    state = _state(consecutive_failures=2, last_error="Riot API answered 503")
    session, factory = _arrange(monkeypatch, state)
    redis = _budget(monkeypatch, limit, used)
    http = _Http(_THREE_REQUESTS)
    asyncio.run(collector.process_fetch({"social_account_id": 10}, redis=redis, http=http, session_factory=factory))
    assert len(http.calls) == limit - used
    assert (state.status, state.consecutive_failures, state.last_error, state.next_eligible_at) == (
        "pending",
        2,
        "Riot API answered 503",
        NOW + timedelta(seconds=60),
    )
    assert session.added == []  # neither a fetch_log row nor a snapshot


def test_a_fetch_inside_the_budget_spends_one_slot_per_request(monkeypatch) -> None:
    state = _state()
    _, factory = _arrange(monkeypatch, state)
    redis = _budget(monkeypatch, 3)
    http = _Http(_THREE_REQUESTS)
    asyncio.run(collector.process_fetch({"social_account_id": 10}, redis=redis, http=http, session_factory=factory))
    assert (state.status, len(http.calls), redis.values[f"lol_rank:rl:{int(NOW.timestamp() // 60)}"]) == ("ok", 3, "3")


def test_a_re_resolve_is_charged_too_and_a_spent_budget_keeps_the_new_puuid_not_the_rejected_one(monkeypatch) -> None:
    state = _state(external_id="p1", region="euw1", consecutive_failures=1)
    session, factory = _arrange(monkeypatch, state)
    monkeypatch.setattr(
        collector, "_load_target", AsyncMock(return_value=collector._Target(10, 7, "Old#EUW", "p1", "euw1"))
    )
    redis = _budget(monkeypatch, 2)
    http = _Http(
        {
            "/riot/account/v1/accounts/by-puuid/p1": (400, {}, None),
            "/riot/account/v1/accounts/by-riot-id/Old/EUW": (200, {"puuid": "p2"}, None),
            "/riot/account/v1/region/by-game/lol/by-puuid/p2": (200, {"region": "EUW1"}, None),
        }
    )
    asyncio.run(collector.process_fetch({"social_account_id": 10}, redis=redis, http=http, session_factory=factory))
    assert http.calls == ["/riot/account/v1/accounts/by-puuid/p1", "/riot/account/v1/accounts/by-riot-id/Old/EUW"]
    assert (state.status, state.consecutive_failures, state.external_id, state.region) == ("pending", 1, "p2", None)
    assert session.added == []


def _windows(monkeypatch, state, routes, *, subject: str | None, limit: int = 2, bound: int = 5):
    """Fetch the account once per minute window under a ``limit``-request budget until it is ``ok``; returns the session
    and the requests each window sent. The loader reads the state like ``_load_target``: cached PUUID, else the subject."""
    session, factory = _arrange(monkeypatch, state)
    monkeypatch.setattr(
        collector,
        "_load_target",
        AsyncMock(
            side_effect=lambda _session, _id: collector._Target(
                10, 7, state.handle, state.external_id or subject, state.region
            )
        ),
    )
    config = collector.LolRankCollectionConfig(enabled=True, jitter_fraction=0, rate_limit_per_minute=limit)
    monkeypatch.setattr(collector, "collection_config", AsyncMock(return_value=config))
    http, redis, spent = _Http(routes), _Redis(), []
    for window in range(bound):
        monkeypatch.setattr(collector, "_now", lambda window=window: NOW + timedelta(minutes=window))
        before = len(http.calls)
        asyncio.run(collector.process_fetch({"social_account_id": 10}, redis=redis, http=http, session_factory=factory))
        spent.append(len(http.calls) - before)
        if state.status == "ok":
            break
    return session, spent


_BY_RIOT_ID = {"/riot/account/v1/accounts/by-riot-id/Old/EUW": (200, {"puuid": "p1"}, None)}


@pytest.mark.parametrize(
    ("cached", "subject", "routes", "spent"),
    [
        pytest.param({}, "p1", _THREE_REQUESTS, [2, 2], id="verified-puuid-no-platform"),
        pytest.param({}, None, {**_BY_RIOT_ID, **_THREE_REQUESTS}, [2, 2], id="unresolved"),
        pytest.param(
            {"external_id": "old", "region": "euw1"},
            None,
            {"/riot/account/v1/accounts/by-puuid/old": (400, {}, None), **_BY_RIOT_ID, **_THREE_REQUESTS},
            [2, 2, 2],
            id="stale-puuid-recovery",
        ),
    ],
)
def test_a_two_request_budget_resumes_a_cut_fetch_until_its_ranks_are_written(
    monkeypatch, cached, subject, routes, spent
) -> None:
    state = _state(**cached)
    session, used = _windows(monkeypatch, state, routes, subject=subject)
    assert used == spent
    assert (state.status, state.external_id, state.region, state.consecutive_failures) == ("ok", "p1", "euw1", 0)
    assert [row.rank_value for row in session.added if isinstance(row, UserRankSnapshot)] == [2775]
    assert [row.status for row in session.added if isinstance(row, RankFetchLog)] == ["ok"]


def test_the_tick_claims_as_many_fetches_as_the_request_budget_pays_for(monkeypatch) -> None:
    config = collector.LolRankCollectionConfig(enabled=True, rate_limit_per_minute=50)
    monkeypatch.setattr(collector, "acquire_distributed_lock", AsyncMock(return_value="token"))
    monkeypatch.setattr(collector, "release_distributed_lock", AsyncMock())
    monkeypatch.setattr(collector, "collection_config", AsyncMock(return_value=config))
    monkeypatch.setattr(collector, "_seed", AsyncMock(return_value=0))
    monkeypatch.setattr(collector, "_count_in_scope", AsyncMock(return_value=10_000))
    claim = AsyncMock(return_value=[])
    monkeypatch.setattr(collector._states, "claim_due", claim)
    asyncio.run(collector.run_collection_tick(redis=_Redis(), session_factory=lambda: _Session()))
    # 50 requests a minute buy 25 two-request fetches per 60 s tick.
    assert claim.await_args.kwargs["limit"] == 50 // collector.REQUESTS_PER_FETCH == 25


def test_a_lol_player_refresh_enqueues_a_priority_fetch_per_riot_account(monkeypatch) -> None:
    accounts = [(10, "A#EUW"), (11, "B#EUW")]
    monkeypatch.setattr(collector, "_riot_accounts_of", AsyncMock(return_value=accounts))
    monkeypatch.setattr(collector, "ensure_state", AsyncMock())
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr(collector, "enqueue_fetch", enqueue)
    event = {"user_id": 7, "discipline": "lol", "workspace_id": 2, "source": "mix_signup"}
    assert asyncio.run(collector.handle_player_refresh(event, session_factory=lambda: _Session())) == 2
    assert [call.kwargs["priority"] for call in enqueue.await_args_list] == [True, True]
    event["discipline"] = "overwatch"
    assert asyncio.run(collector.handle_player_refresh(event, session_factory=lambda: _Session())) == 0


_TAG = itertools.count()


class LolCollectorDbTests(IsolatedAsyncioTestCase):
    """Every collector session joins one outer transaction through a savepoint; teardown rolls it all back."""

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        ensure_test_postgres()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.tag = f"lolc{os.getpid()}x{next(_TAG)}"
        async with self.sessions() as s:
            user = models.User(name=self.tag)
            s.add(user)
            await s.commit()
            self.user_id = user.id

    async def asyncTearDown(self) -> None:
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    def sessions(self) -> AsyncSession:
        return AsyncSession(bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

    async def account(self, username: str) -> int:
        async with self.sessions() as s:
            account = models.SocialAccount(
                user_id=self.user_id,
                provider=SocialProvider.RIOT,
                username=username,
                username_normalized=normalize_social_handle(SocialProvider.RIOT, username),
            )
            s.add(account)
            await s.commit()
            return account.id

    async def state(self, account_id: int) -> models.RankAccountState:
        async with self.sessions() as s:
            state = models.RankAccountState
            return await s.scalar(sa.select(state).where(state.social_account_id == account_id))

    async def fetch(self, account_id: int, http: _Http, config: collector.LolRankCollectionConfig) -> None:
        with patch.object(collector, "collection_config", AsyncMock(return_value=config)):
            await collector.process_fetch(
                {"social_account_id": account_id}, redis=_Redis(), http=http, session_factory=self.sessions
            )

    async def test_scope_all_seeds_an_untagged_riot_account_and_its_fetch_disables_it(self) -> None:
        account_id = await self.account(self.tag)
        async with self.sessions() as s:
            await collector._seed(s, collector.LolRankCollectionConfig(scope="all"))
            await s.commit()
        seeded = await self.state(account_id)
        self.assertEqual((seeded.discipline, seeded.handle, seeded.external_id), ("lol", self.tag, None))

        config = collector.LolRankCollectionConfig(enabled=True, max_consecutive_failures=1)
        await self.fetch(account_id, _Http({}), config)
        state = await self.state(account_id)
        self.assertEqual((state.status, state.consecutive_failures, state.next_eligible_at), ("disabled", 1, None))
        async with self.sessions() as s:
            log = models.RankFetchLog
            errors = (await s.scalars(sa.select(log.error).where(log.social_account_id == account_id))).all()
        self.assertEqual(errors, [collector.INVALID_RIOT_ID_ERROR])

    async def test_an_unresolved_account_is_fetched_by_its_corrected_riot_id(self) -> None:
        account_id = await self.account(f"{self.tag} # EUW")
        async with self.sessions() as s:
            s.add(models.RankAccountState(discipline="lol", social_account_id=account_id, handle="Old#EUW"))
            await s.commit()
        http = _Http(
            {
                f"/riot/account/v1/accounts/by-riot-id/{self.tag}/EUW": (200, {"puuid": "p9"}, None),
                "/riot/account/v1/region/by-game/lol/by-puuid/p9": (200, {"region": "EUW1"}, None),
                "/riot/account/v1/accounts/by-puuid/p9": (200, {"gameName": self.tag, "tagLine": "EUW"}, None),
                "https://euw1.api.riotgames.com/lol/league/v4/entries/by-puuid/p9": (200, [SOLO], None),
            }
        )
        await self.fetch(account_id, http, collector.LolRankCollectionConfig(enabled=True))
        state = await self.state(account_id)
        self.assertEqual(
            (state.status, state.handle, state.external_id, state.region), ("ok", f"{self.tag}#EUW", "p9", "euw1")
        )
