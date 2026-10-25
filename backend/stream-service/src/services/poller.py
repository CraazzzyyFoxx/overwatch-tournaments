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
  a five-caster event into five herd refetches.
- **A hidden tournament is polled and stored, but not announced.** The public
  topic has no viewer to authorize against, so publishing there would tell an
  anonymous subscriber that a preview tournament exists.
- **The target set is resolved in FOUR queries total, not four per tournament.**
  ``StreamTargetsService`` batches every active tournament's channels and
  official links into one pair of queries each — see ``_build_plans``.
- **Every live POV broadcast is recorded, then its VOD is chased.** After the
  live set is stored, each participant channel on air (never an official cast)
  upserts a ``stream.session`` row; the VOD sync that follows every tick — active
  tournaments or not, since completed tournaments' VODs still expire — resolves
  pending broadcasts to their Twitch VOD and re-checks resolved VODs once a day.
  The VOD sync shares the tick's slot but not its outcome: its Helix failures are
  logged and swallowed, never written to the recorded tick status.

Live state lives in ``state.py`` (Redis). The one Postgres table this module
writes is ``stream.session``, through ``StreamSessionRepository``.

``run_poll_tick`` is the entry point ``scheduler.py`` and the tests call; it runs
one ``StreamPollTick``.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from shared.repository import StreamSessionObservation, StreamSessionRepository
from shared.schemas.settings import StreamCollectionConfig
from shared.services.realtime import DomainEvent, Resource, Scope, emit
from src.core import metrics
from src.core.config import settings
from src.services.helix import (
    HelixBatchResult,
    HelixClient,
    HelixError,
    HelixNotConfigured,
    HelixRateLimited,
    HelixUnauthorized,
    HelixUnavailable,
    HelixVideosResult,
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


#: Injection seams for the tick's network calls. Loose (``...``) because the
#: ``HelixClient.fetch_*`` methods carry defaulted knobs the tick never passes.
LiveStreamFetcher = Callable[..., Awaitable[HelixBatchResult]]
VideosFetcher = Callable[..., Awaitable[HelixVideosResult]]

#: VOD sync bounds. A broadcast is chased for a day after it was last seen live —
#: the archive exists from the first minute of the broadcast, so one still missing
#: a day later was never kept — and at most every 10 minutes, one Helix call per
#: broadcaster, at most 20 broadcasters a tick.
VOD_RESOLVE_WINDOW = timedelta(hours=24)
VOD_RESOLVE_RETRY = timedelta(minutes=10)
VOD_RESOLVE_MAX_BROADCASTERS = 20
#: A resolved VOD is re-checked daily, in batches of 100 ids, at most 5 batches a tick.
VOD_RECHECK_INTERVAL = timedelta(hours=24)
VOD_RECHECK_MAX_IDS = 500


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
    """One run of the Twitch live-status poll tick, then the VOD sync.

    ``fetch`` (and ``fetch_archives``/``fetch_videos`` for the VOD sync) are
    injected so the whole tick — dedup, fan-out, diffing, the hidden tournament
    rule, session recording — is testable without a network or a Twitch
    application. They default to one ``HelixClient`` built from the service's
    own settings.
    """

    def __init__(
        self,
        session: Any,
        redis: Redis,
        cfg: StreamCollectionConfig,
        *,
        fetch: LiveStreamFetcher | None = None,
        fetch_archives: VideosFetcher | None = None,
        fetch_videos: VideosFetcher | None = None,
        targets: StreamTargetsService = StreamTargetsService(),
        sessions: StreamSessionRepository = StreamSessionRepository(),
        state: StreamStateStore | None = None,
    ) -> None:
        self._session = session
        self._redis = redis
        self._cfg = cfg
        self._targets = targets
        self._sessions = sessions
        self._state = state or StreamStateStore(redis)
        client = self._default_client()
        self._fetch = fetch or client.fetch_live_streams
        self._fetch_archives = fetch_archives or client.fetch_archive_videos
        self._fetch_videos = fetch_videos or client.fetch_videos
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
        """Poll every active tournament once, then sync VODs. Returns the number
        of tournaments updated."""
        if not self._cfg.enabled:
            logger.debug("Stream collection disabled in settings; skipping tick")
            return 0

        try:
            processed = await self._run()
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

        # After the status is recorded: that status describes the live poll, and
        # nothing the VOD sync does may rewrite it.
        await self._sync_vods()
        return processed

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
        observations: dict[tuple[int, str], StreamSessionObservation] = {}
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
            observations.update(
                ((observation.tournament_id, observation.stream_id), observation)
                for observation in self._observations(plan, live_by_login)
            )
            processed += 1

        # One commit for the live sets: emit() publishes from after_commit, and a
        # tick that touched twenty tournaments should pay one round trip, not
        # twenty.
        await self._session.commit()
        if observations:
            await self._sessions.record_observed(self._session, list(observations.values()), seen_at=datetime.now(UTC))
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
        repository calls, not one pair per tournament.
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

    @staticmethod
    def _observations(plan: _Plan, live_by_login: dict[str, StreamSnapshot]) -> Iterator[StreamSessionObservation]:
        """The plan's live POV broadcasts worth recording: a participant's own
        channel (an official cast is out of scope, even when a player runs it)
        carrying everything a VOD is later matched by."""
        for login, channel in plan.channels.items():
            found = live_by_login.get(login)
            if found is None or channel.player_id is None or channel.source == "official":
                continue
            if not (found.stream_id and found.user_id and found.started_at):
                continue
            yield StreamSessionObservation(
                tournament_id=plan.tournament.tournament_id,
                user_id=channel.player_id,
                channel=login,
                broadcaster_id=found.user_id,
                stream_id=found.stream_id,
                started_at=datetime.fromisoformat(found.started_at),
            )

    async def _emit(self, tournament_id: int, live_count: int) -> None:
        """Thin ``stream.updated`` plus the ``tournament.streams`` invalidation.

        The data event is non-durable (``event_id=0``, no
        ``realtime.workspace_event`` row) for the same reason as
        ``logs.updated``/``subscription.updated``: a reconnecting client
        refetches anyway, so persisting a row per channel going live buys
        nothing. It carries no channel data — the authoritative read is the RPC,
        which applies the visibility rules this signal has no way to.

        The commit in ``_run`` that closes the live sets is what persists the
        invalidation row and publishes both.
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

    async def _sync_vods(self) -> None:
        """Resolve recorded broadcasts to their VOD, then re-check resolved VODs.

        Commits only when it wrote something, so an idle sync costs its two
        SELECTs and nothing else.
        """
        now = datetime.now(UTC)
        resolved = await self._resolve_vods(now)
        rechecked = await self._recheck_vods(now)
        if resolved or rechecked:
            await self._session.commit()

    async def _resolve_vods(self, now: datetime) -> bool:
        """One archive lookup per broadcaster (deduped across tournaments), the
        longest-waiting first; every row of an answered broadcaster is stamped
        attempted, and the ones whose ``stream_id`` Helix lists get their VOD."""
        pending = await self._sessions.list_unresolved(
            self._session, seen_since=now - VOD_RESOLVE_WINDOW, checked_before=now - VOD_RESOLVE_RETRY
        )
        rows_of: dict[str, list[Any]] = {}
        for row in pending:
            rows_of.setdefault(row.broadcaster_id, []).append(row)
        if not rows_of:
            return False
        result = await self._videos(
            self._fetch_archives(user_ids=list(rows_of)[:VOD_RESOLVE_MAX_BROADCASTERS]), "archive lookup"
        )
        if result is None:
            return False
        vod_of_stream = {video.stream_id: video.id for video in result.videos if video.stream_id}
        attempted = [row for broadcaster in result.polled for row in rows_of.get(broadcaster, [])]
        await self._sessions.mark_vod_attempts(
            self._session,
            attempted=[row.id for row in attempted],
            resolved={row.id: vod_of_stream[row.stream_id] for row in attempted if row.stream_id in vod_of_stream},
            checked_at=now,
        )
        return bool(attempted)

    async def _recheck_vods(self, now: datetime) -> bool:
        """Ask Helix which resolved VODs still exist; the ones it was asked about
        and did not return are gone."""
        due = await self._sessions.list_due_recheck(
            self._session, checked_before=now - VOD_RECHECK_INTERVAL, limit=VOD_RECHECK_MAX_IDS
        )
        if not due:
            return False
        result = await self._videos(self._fetch_videos(ids=sorted({row.vod_id for row in due})), "VOD re-check")
        if result is None:
            return False
        alive = {video.id for video in result.videos}
        checked = [row for row in due if row.vod_id in result.polled]
        await self._sessions.mark_rechecked(
            self._session,
            alive=[row.id for row in checked if row.vod_id in alive],
            gone=[row.id for row in checked if row.vod_id not in alive],
            checked_at=now,
        )
        return bool(checked)

    @staticmethod
    async def _videos(call: Awaitable[HelixVideosResult], what: str) -> HelixVideosResult | None:
        """Await a VOD-sync Helix call; a failure is logged and means "learned nothing"."""
        try:
            return await call
        except HelixNotConfigured:
            # The live poll already records this as the tick's status.
            return None
        except HelixError as exc:
            logger.warning("Helix {} failed during the VOD sync: {!r}", what, exc)
            return None


async def run_poll_tick(
    session: Any,
    redis: Redis,
    cfg: StreamCollectionConfig,
    *,
    fetch: LiveStreamFetcher | None = None,
    fetch_archives: VideosFetcher | None = None,
    fetch_videos: VideosFetcher | None = None,
    targets: StreamTargetsService | None = None,
    sessions: StreamSessionRepository | None = None,
    state: StreamStateStore | None = None,
) -> int:
    """Poll every active tournament once via ``StreamPollTick``. Returns the
    number of tournaments updated."""
    tick = StreamPollTick(
        session,
        redis,
        cfg,
        fetch=fetch,
        fetch_archives=fetch_archives,
        fetch_videos=fetch_videos,
        targets=targets or StreamTargetsService(),
        sessions=sessions or StreamSessionRepository(),
        state=state,
    )
    return await tick.run()
