"""One Twitch live-status poll tick.

Shape of the tick, and why:

- **One global batch, not one per tournament.** A caster streaming two
  tournaments in the same evening is one channel; asking Helix about them
  separately doubles the cost against a bucket shared with identity-service's
  OAuth logins. Channels are deduped across every polled tournament, polled once,
  and the answer is fanned back out.
- **Absence means offline.** ``GET /streams`` only returns live channels, so the
  live set is *replaced* per tournament rather than merged. That is also why a
  truncated poll may not be written: a channel nobody asked about would be
  recorded as offline, and viewers would watch badges flicker off mid-tournament.
- **One realtime signal per tournament, never per channel.** A tournament page has
  hundreds of concurrent spectators on one topic; a per-channel fan-out would turn
  a five-caster event into five herd refetches (Risks, "herd refetch").
- **A hidden tournament is polled and stored, but not announced.** The public
  topic has no viewer to authorize against, so publishing there would tell an
  anonymous subscriber that a preview tournament exists.
- **The target set is resolved in FOUR queries total, not four per tournament.**
  ``StreamTargetsService`` batches every active tournament's channels and
  official links into one pair of queries each — see ``_build_plans`` — instead
  of the tick paying one round-trip pair per tournament on every 30s heartbeat.

State lives in ``state.py`` (Redis) — this module owns no persistence and writes
to no Postgres schema.

The tick is a class (``StreamPollTick``) rather than free functions threading a
mutable report through nine of them by hand: the report has to survive every
Helix failure branch (the tick swallows them on purpose — a Twitch outage must
not kill the scheduler), and an instance attribute mutated in place reads more
plainly than a parameter re-passed to every helper that might set it.
``run_poll_tick`` stays a plain function — the stable entry point
``scheduler.py`` and the test suite call — that builds one ``StreamPollTick`` and
runs it.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from shared.schemas.settings import StreamCollectionConfig
from shared.services.realtime import DomainEvent, Resource, Scope, emit
from src.core import metrics
from src.core.config import settings
from src.services.helix import (
    HelixBatchResult,
    HelixClient,
    HelixNotConfigured,
    HelixRateLimited,
    HelixUnauthorized,
    HelixUnavailable,
    StreamSnapshot,
)
from src.services.state import StreamStateStore
from src.services.targets import StreamTargetsService, TournamentPollTarget, twitch_channel_from_url

__all__ = ("STREAM_UPDATED", "StreamPollTick", "run_poll_tick")

STREAM_UPDATED = "stream.updated"

#: Tick outcomes recorded for the admin health panel. Mirrors the ``status`` label
#: on ``STREAM_POLL_TICKS_TOTAL`` so a Grafana series and the panel never disagree.
POLL_STATUS_OK = "ok"
POLL_STATUS_EMPTY = "empty"
POLL_STATUS_TRUNCATED = "truncated"
POLL_STATUS_ERROR = "error"


#: Injection seam for the tick's only network call. Kept loose (``...``) rather
#: than a Protocol because ``HelixClient.fetch_live_streams`` carries defaulted
#: knobs the tick never passes, and a Protocol would have to restate all of them.
LiveStreamFetcher = Callable[..., Awaitable[HelixBatchResult]]


@dataclass(frozen=True, slots=True)
class _Channel:
    """A channel as one tournament sees it — the same login can carry a different
    owner and a different consent source in another tournament."""

    login: str
    player_id: int | None
    provider_user_id: str | None
    source: str  # "official" | "verified" | "self_declared"


@dataclass(frozen=True, slots=True)
class _Plan:
    tournament: TournamentPollTarget
    channels: dict[str, _Channel]


@dataclass(slots=True)
class _TickReport:
    """What the tick did, for ``stream:poll:last_status``.

    An instance attribute on ``StreamPollTick`` rather than a return value: the
    tick already swallows every Helix failure on purpose (a Twitch outage must
    not kill the scheduler), so the only way an operator can learn *which*
    failure happened is if the failing branch records it on the way past.
    """

    status: str = POLL_STATUS_EMPTY
    tournaments_active: int = 0
    tournaments_updated: int = 0
    channels_polled: int = 0
    live_channels: int = 0
    ratelimit_remaining: int | None = None

    def as_status(self, *, ran_at: float) -> dict[str, Any]:
        return {
            "ran_at": ran_at,
            "status": self.status,
            "tournaments_active": self.tournaments_active,
            "tournaments_updated": self.tournaments_updated,
            "channels_polled": self.channels_polled,
            "live_channels": self.live_channels,
            "ratelimit_remaining": self.ratelimit_remaining,
        }


class StreamPollTick:
    """One run of the Twitch live-status poll tick.

    ``fetch`` is injected so the whole tick — dedup, fan-out, diffing, the hidden
    tournament rule — is testable without a network or a Twitch application.
    Defaults to a ``HelixClient`` built from the service's own settings.
    """

    def __init__(
        self,
        session: Any,
        redis: Redis,
        cfg: StreamCollectionConfig,
        *,
        fetch: LiveStreamFetcher | None = None,
        targets: StreamTargetsService = StreamTargetsService(),
        state: StreamStateStore | None = None,
    ) -> None:
        self._session = session
        self._redis = redis
        self._cfg = cfg
        self._targets = targets
        self._state = state or StreamStateStore(redis)
        self._fetch = fetch or self._default_client().fetch_live_streams
        self._report = _TickReport()

    def _default_client(self) -> HelixClient:
        return HelixClient(
            self._redis,
            client_id=settings.twitch_client_id,
            client_secret=settings.twitch_client_secret,
            helix_url=settings.twitch_helix_url,
            token_url=settings.twitch_token_url,
            proxy=settings.proxy_url,
        )

    async def run(self) -> int:
        """Poll every active tournament once. Returns the number of tournaments
        updated."""
        if not self._cfg.enabled:
            logger.debug("Stream collection disabled in settings; skipping tick")
            return 0

        try:
            return await self._run()
        except Exception:
            self._report.status = POLL_STATUS_ERROR
            raise
        finally:
            # Set unconditionally, not only on success. The cursor spaces
            # *attempts*, and a Twitch outage that skipped it would turn the 30s
            # heartbeat into a retry storm on a rate-limit bucket
            # identity-service also needs.
            ran_at = time.time()
            await self._state.set_last_run(ran_at)
            # After the cursor: if this write is the one that fails, the
            # interval is still respected and only the panel goes stale.
            await self._state.write_poll_status(self._report.as_status(ran_at=ran_at))

    async def _run(self) -> int:
        plans = await self._build_plans()
        self._report.tournaments_active = len(plans)
        if not plans:
            metrics.STREAM_POLL_TICKS_TOTAL.labels(status=POLL_STATUS_EMPTY).inc()
            self._report.status = POLL_STATUS_EMPTY
            return 0

        logins, user_ids, query_keys = self._global_targets(plans)
        metrics.STREAM_CHANNELS_POLLED.set(len(query_keys))
        self._report.channels_polled = len(query_keys)

        result = await self._fetch_batch(logins=logins, user_ids=user_ids)
        if result is None:
            return 0

        if result.ratelimit_remaining is not None:
            metrics.STREAM_HELIX_RATELIMIT_REMAINING.set(result.ratelimit_remaining)
            self._report.ratelimit_remaining = result.ratelimit_remaining
        metrics.STREAM_LIVE_CHANNELS.set(len(result.snapshots))
        self._report.live_channels = len(result.snapshots)

        live_by_login = {snapshot.channel: snapshot for snapshot in result.snapshots}
        polled = {
            login
            for login, (param, value) in query_keys.items()
            if value in (result.polled_user_ids if param == "user_id" else result.polled_logins)
        }

        processed = 0
        for plan in plans:
            if not plan.channels.keys() <= polled:
                # Partial coverage is not a partial answer: writing it would mark
                # the unpolled channels offline. Left untouched, they keep the
                # previous tick's state until its TTL (3 x interval) or the next
                # full tick.
                logger.warning(
                    "Rate-limit gate stopped the poll before tournament {}; leaving its live set untouched",
                    plan.tournament.tournament_id,
                )
                continue
            await self._apply(plan, live_by_login)
            processed += 1

        # One commit for the whole tick: emit() publishes from after_commit, and
        # a tick that touched twenty tournaments should pay one round trip, not
        # twenty. The session holds nothing else — live status lives in Redis.
        await self._session.commit()

        self._report.status = POLL_STATUS_TRUNCATED if result.truncated else POLL_STATUS_OK
        self._report.tournaments_updated = processed
        metrics.STREAM_POLL_TICKS_TOTAL.labels(status=self._report.status).inc()
        if result.truncated:
            logger.warning(
                "Helix rate-limit floor reached (remaining={}); polled {}/{} tournaments",
                result.ratelimit_remaining,
                processed,
                len(plans),
            )
        return processed

    async def _build_plans(self) -> list[_Plan]:
        """Resolve every active tournament to its channel set.

        Official links are folded in *after* participants and win the
        ``source`` slot while keeping any player the channel was already
        matched to: a caster who also plays appears once, in the official
        block, still attributed.

        Every tournament's channels and links come from ONE pair of batched
        repository calls, not one pair per tournament — the tick's main
        optimization over polling each tournament's targets individually.
        """
        tournaments = await self._targets.active_tournaments(self._session)
        tournament_ids = [tournament.tournament_id for tournament in tournaments]
        channels_by_tournament = await self._targets.participant_channels_bulk(self._session, tournament_ids)
        links_by_tournament = await self._targets.official_stream_links_bulk(self._session, tournament_ids)

        plans: list[_Plan] = []
        for tournament in tournaments:
            channels: dict[str, _Channel] = {}
            for participant in channels_by_tournament.get(tournament.tournament_id, []):
                channels[participant.login] = _Channel(
                    login=participant.login,
                    player_id=participant.player_id,
                    provider_user_id=participant.provider_user_id,
                    source=participant.source,
                )
            for link in links_by_tournament.get(tournament.tournament_id, []):
                login = twitch_channel_from_url(link.url)
                if login is None:
                    # A YouTube link or a Twitch VOD: renderable, not pollable.
                    # The RPC read serves it with live=None ("no detection"), not
                    # live=False.
                    continue
                known = channels.get(login)
                channels[login] = _Channel(
                    login=login,
                    player_id=known.player_id if known else None,
                    provider_user_id=known.provider_user_id if known else None,
                    source="official",
                )
            plans.append(_Plan(tournament=tournament, channels=channels))
        return plans

    @staticmethod
    def _global_targets(plans: list[_Plan]) -> tuple[list[str], list[str], dict[str, tuple[str, str]]]:
        """Collapse every tournament's channels into one query set.

        Returns the logins to ask by name, the ids to ask by id, and the map from
        login to the identifier actually used — needed afterwards to tell which
        tournaments the rate-limit gate managed to cover.
        """
        query_keys: dict[str, tuple[str, str]] = {}
        for plan in plans:
            for login, channel in plan.channels.items():
                existing = query_keys.get(login)
                if existing is not None and existing[0] == "user_id":
                    continue
                if channel.provider_user_id:
                    # A verified account anywhere upgrades the whole login to an
                    # id lookup: ids survive a channel rename, logins do not.
                    query_keys[login] = ("user_id", channel.provider_user_id)
                elif existing is None:
                    query_keys[login] = ("user_login", login)

        logins = sorted(login for login, (param, _) in query_keys.items() if param == "user_login")
        user_ids = sorted({value for param, value in query_keys.values() if param == "user_id"})
        return logins, user_ids, query_keys

    async def _fetch_batch(self, *, logins: list[str], user_ids: list[str]) -> HelixBatchResult | None:
        """Run the Helix call, mapping every failure onto a metric and a skipped
        tick.

        ``None`` means "we learned nothing" — the caller must not write
        anything, because an empty snapshot set and an unanswered request look
        identical downstream and only one of them means "everybody went offline".
        """
        if not logins and not user_ids:
            # Nothing to ask, but still a real answer: every active tournament
            # has an empty live set, which the fan-out below writes (clearing
            # stale badges).
            return HelixBatchResult(snapshots=[])

        try:
            result: HelixBatchResult = await self._fetch(
                logins=logins,
                user_ids=user_ids,
                batch_size=self._cfg.batch_size,
            )
        except HelixNotConfigured:
            # Expected state, not an incident: the feature ships inert until an
            # operator sets TWITCH_CLIENT_ID/SECRET.
            self._report.status = "not_configured"
            metrics.STREAM_HELIX_ERRORS_TOTAL.labels(kind="not_configured").inc()
            metrics.STREAM_POLL_TICKS_TOTAL.labels(status="not_configured").inc()
            logger.debug("Twitch credentials are not configured; skipping stream poll tick")
            return None
        except HelixRateLimited as exc:
            self._report.status = "rate_limited"
            metrics.STREAM_HELIX_ERRORS_TOTAL.labels(kind="rate_limited").inc()
            metrics.STREAM_POLL_TICKS_TOTAL.labels(status="rate_limited").inc()
            logger.warning("Helix rate-limited the poll tick (reset_at={})", exc.reset_at)
            return None
        except HelixUnauthorized:
            self._report.status = "unauthorized"
            metrics.STREAM_HELIX_ERRORS_TOTAL.labels(kind="unauthorized").inc()
            metrics.STREAM_POLL_TICKS_TOTAL.labels(status="unauthorized").inc()
            logger.error("Twitch rejected the app credentials; stream polling is disabled until they are fixed")
            return None
        except HelixUnavailable as exc:
            self._report.status = "unavailable"
            metrics.STREAM_HELIX_ERRORS_TOTAL.labels(kind="unavailable").inc()
            metrics.STREAM_POLL_TICKS_TOTAL.labels(status="unavailable").inc()
            logger.warning("Helix unavailable during stream poll tick: {}", exc)
            return None
        return result

    async def _apply(self, plan: _Plan, live_by_login: dict[str, StreamSnapshot]) -> None:
        """Store one tournament's live set and, if the *set* changed, announce it."""
        snapshots: dict[str, dict[str, Any]] = {}
        for login, channel in plan.channels.items():
            found = live_by_login.get(login)
            if found is None:
                continue
            body = found.as_dict()
            body["player_id"] = channel.player_id
            body["source"] = channel.source
            snapshots[StreamStateStore.snapshot_field(found.platform, login)] = body

        tournament_id = plan.tournament.tournament_id
        previous = await self._state.read_live(tournament_id)
        # Written every tick even when the membership is unchanged: viewer
        # counts, titles and the key's TTL all go stale otherwise.
        await self._state.write_live(tournament_id, snapshots, ttl_seconds=3 * self._cfg.interval_seconds)

        if previous.keys() == snapshots.keys():
            # Someone's viewer count ticking up is not worth waking every open
            # page.
            return
        if plan.tournament.is_hidden:
            logger.debug("Tournament {} is hidden; live set stored but not published", tournament_id)
            return
        await self._emit(tournament_id, len(snapshots))

    async def _emit(self, tournament_id: int, live_count: int) -> None:
        """Thin ``stream.updated`` plus the ``tournament.streams`` invalidation.

        The data event is non-durable (``event_id=0``, no
        ``realtime.workspace_event`` row) for the same reason as
        ``logs.updated``/``subscription.updated``: a reconnecting client
        refetches anyway, so persisting a row per channel going live buys
        nothing. It carries no channel data — the authoritative read is the RPC,
        which applies the visibility rules this signal has no way to.

        The tick's session is otherwise read-only; the commit in ``_run`` is what
        persists the invalidation row and publishes both.
        """
        await emit(
            self._session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_STREAMS],
            data=DomainEvent(
                domain="streams",
                event_type=STREAM_UPDATED,
                payload={"tournament_id": int(tournament_id), "live_count": int(live_count)},
                durable=False,
            ),
        )


async def run_poll_tick(
    session: Any,
    redis: Redis,
    cfg: StreamCollectionConfig,
    *,
    fetch: LiveStreamFetcher | None = None,
    targets: StreamTargetsService | None = None,
    state: StreamStateStore | None = None,
) -> int:
    """Poll every active tournament once. Returns the number of tournaments
    updated. Thin functional entry point over ``StreamPollTick``, kept so
    ``scheduler.py`` and the admin re-poll path have one stable call shape."""
    tick = StreamPollTick(
        session,
        redis,
        cfg,
        fetch=fetch,
        targets=targets or StreamTargetsService(),
        state=state,
    )
    return await tick.run()
