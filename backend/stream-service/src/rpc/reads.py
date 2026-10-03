"""Public read subscribers (``rpc.stream.tournament_streams``).

Serves ``GET /api/streams/tournament/{tournament_id}`` — the "who is on air"
block of a tournament page, for anonymous viewers.

Two sources, joined here and nowhere else:

* **official** — ``tournament.tournament_link`` rows with ``kind='stream'``, read
  through ``StreamTargetsService.official_stream_links`` so the poll tick and
  this read can never disagree about which links exist or in what order.
  Offline links stay in the response: the link is worth showing whether or not
  anyone is on air.
* **participants** — the Redis live set the poller rebuilds each tick
  (``src.services.state.StreamStateStore``). Only live channels exist there by
  construction, so this list is inherently "currently on air".

URL parsing also comes from ``src.services.targets``: the same function decides
what the poller asks Helix about and what this read calls a Twitch channel,
which is what keeps ``live=False`` ("polled, offline") from being confused with
``live=None`` ("never polled").

This module is READ-ONLY with respect to Postgres. It touches ``tournament.*``
and ``players.*``, both owned by other services
(``backend/docs/tournament-service-write-path-inventory.md``), so there is no
``session.add`` and no ``commit`` anywhere in this path. The batched player
lookup lives in ``shared.repository.StreamTargetRepository.list_roster`` — this
module only ranks and vetoes the rows it gets back.
"""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import urlsplit

from faststream.rabbit.annotations import RabbitMessage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.link import TournamentLink
from shared.repository import StreamTargetRepository
from shared.services.tournament.visibility import ensure_tournament_viewable
from src.core import db
from src.schemas.stream import (
    StreamEntryRead,
    StreamPlatform,
    StreamPlayerRead,
    StreamTeamRead,
    TournamentStreamsRead,
)
from src.services import targets
from src.services.state import StreamStateStore
from src.services.targets import StreamTargetsService

from . import _common as c
from ._clients import realtime_redis

__all__ = ("TournamentStreamsReader", "build_tournament_streams", "register", "tournament_streams")

_PLATFORMS: frozenset[str] = frozenset({"twitch", "youtube", "other"})


def _platform(url: str) -> StreamPlatform:
    """``targets.platform_from_url`` narrowed to the wire Literal."""
    return cast(StreamPlatform, targets.platform_from_url(url))


def _display_channel(url: str, label: str | None) -> str:
    """Channel caption for a link with no pollable login (YouTube, custom hosts).

    The organizer's own label wins; the host is the fallback so the entry never
    renders as an empty string.
    """
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return label or host or url


def _snapshot_platform(field: str, snapshot: dict[str, Any]) -> StreamPlatform:
    raw = str(snapshot.get("platform") or field.split(":", 1)[0])
    # The Literal is the wire contract; an unexpected value from our own writer
    # degrades to "other" rather than 422-ing the whole public block.
    return cast(StreamPlatform, raw if raw in _PLATFORMS else "other")


def _player_id(snapshot: dict[str, Any]) -> int | None:
    raw = snapshot.get("player_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _entry_from_snapshot(
    field: str,
    snapshot: dict[str, Any],
    *,
    player: StreamPlayerRead,
) -> StreamEntryRead:
    """Build a live entry from a Redis snapshot.

    ``live=True`` unconditionally: the hash holds only channels Helix reported as
    live and ``StreamStateStore.write_live`` replaces the whole set each tick, so
    the field's existence IS the liveness signal. The snapshot carries no
    ``live`` key on purpose — an always-true field would invite a reader to
    trust a stale one.

    ``player`` is required, not optional: the caller drops any entry it could not
    resolve a publishable player for (see ``TournamentStreamsReader.build``), so
    an unattributed participant entry is not a state this function can produce.
    """
    channel = str(snapshot.get("channel") or field.split(":", 1)[-1])
    return StreamEntryRead(
        platform=_snapshot_platform(field, snapshot),
        channel=channel,
        url=str(snapshot.get("url") or f"https://twitch.tv/{channel}"),
        live=True,
        title=snapshot.get("title"),
        game_name=snapshot.get("game_name"),
        viewer_count=snapshot.get("viewer_count"),
        thumbnail_url=snapshot.get("thumbnail_url"),
        started_at=snapshot.get("started_at"),
        player=player,
    )


def _official_entry(link: TournamentLink, live: dict[str, dict[str, Any]]) -> StreamEntryRead:
    """Build an entry for one ``kind='stream'`` link, live or not.

    ``player`` stays ``None`` even when the poller matched the channel to a
    participant: this is the organizer's broadcast slot, and attributing it to
    one of the players would misrepresent it.
    """
    url = str(link.url)
    platform = _platform(url)
    channel = targets.twitch_channel_from_url(url)
    snapshot = live.get(StreamStateStore.snapshot_field(platform, channel)) if channel else None
    if snapshot is not None:
        # On air: live metadata from the poller, but the organizer's own URL —
        # theirs may carry query params the snapshot's canonical form drops.
        return StreamEntryRead(
            platform=platform,
            channel=channel or "",
            url=url,
            live=True,
            title=snapshot.get("title"),
            game_name=snapshot.get("game_name"),
            viewer_count=snapshot.get("viewer_count"),
            thumbnail_url=snapshot.get("thumbnail_url"),
            started_at=snapshot.get("started_at"),
        )
    return StreamEntryRead(
        platform=platform,
        channel=channel or _display_channel(url, link.label),
        url=url,
        # False only where a poll actually happens; otherwise unknown. See
        # ``StreamEntryRead.live``.
        live=False if channel else None,
    )


class TournamentStreamsReader:
    """Assembles ``rpc.stream.tournament_streams`` — the public "who is on air"
    block for one tournament."""

    def __init__(
        self,
        *,
        targets: StreamTargetsService = StreamTargetsService(),
        rosters: StreamTargetRepository = StreamTargetRepository(),
    ) -> None:
        self._targets = targets
        self._rosters = rosters

    async def _load_players(
        self,
        session: AsyncSession,
        player_ids: set[int],
        tournament_id: int,
    ) -> dict[int, StreamPlayerRead]:
        """Name, avatar and tournament team for every *publishable* streaming
        participant, in ONE query.

        Batched deliberately: a tournament page can carry dozens of live
        channels and a per-entry lookup would put that many round-trips on a
        public, cacheable read.

        PRIVACY: also the display half of the stream veto. ``stream_visible``
        rides along in the same SELECT (``StreamTargetRepository.list_roster``)
        and a vetoed player is simply left out of the map. The poll-target query
        already keeps them out of Redis, but that only takes effect on the next
        tick — for a privacy switch, a 30-60s window during which the page still
        shows you is not acceptable, and the entries already in the hash have to
        be dropped at read time too.

        Also the roster gate. Before the teams exist, every approved registrant
        who is on air belongs on the page — that is the whole point of streaming
        during ``check_in``. Once the tournament HAS rosters, a participant with
        no team is someone the draft left out, and the block is about the
        tournament being played, so they are dropped. ``rosters_formed`` is the
        tournament-wide flag the same SELECT carries, so this costs no extra
        query and cannot disagree with the team it renders.
        """
        if not player_ids:
            return {}
        rows = await self._rosters.list_roster(session, tournament_id, player_ids)

        # One user can come back on several rows, so the pick has to be total
        # rather than "whatever arrived first": a substitute covering a slot is
        # a SECOND roster row in the same tournament, and a user who belongs to
        # more than one workspace also contributes rows where the roster join
        # matched nothing. Ranking makes the answer a function of the data
        # alone — otherwise identical data would attribute the participant to a
        # different team on every tick, which reads as switching teams
        # mid-broadcast.
        best: dict[int, tuple[tuple[bool, bool, int], Any]] = {}
        for row in rows:
            # PRIVACY: the veto, applied before ranking so a vetoed user cannot
            # even become a map entry. ``is False`` and not ``not
            # row.stream_visible``: only an explicit false is a veto, so a NULL
            # from an older row (or a fake row in a test) fails open rather
            # than silently un-publishing a whole tournament.
            if row.stream_visible is False:
                continue
            # A real roster row beats none, a starter beats a substitute, and
            # the lowest roster id breaks any remaining tie.
            rank = (row.roster_id is None, row.is_substitution, row.roster_id or 0)
            if (previous := best.get(row.user_id)) is None or rank < previous[0]:
                best[row.user_id] = (rank, row)
        # The flag is a property of the tournament, so any row answers for all of
        # them; ``any`` rather than indexing because ``rows`` may be empty.
        rosters_formed = any(row.rosters_formed for row in rows)
        return {
            user_id: StreamPlayerRead(
                id=user_id,
                name=row.name,
                avatar_url=row.avatar_url,
                # Before the draft this is the normal state and the entry still
                # serves; after it, ``rosters_formed`` has already excluded such
                # a player below.
                team=StreamTeamRead(id=row.team_id, name=row.team_name) if row.team_id is not None else None,
            )
            for user_id, (_, row) in best.items()
            if row.team_id is not None or not rosters_formed
        }

    async def build(self, session: AsyncSession, redis: Redis, tournament_id: int) -> TournamentStreamsRead:
        """Assemble the stream block. Caller MUST have gated visibility already."""
        state = StreamStateStore(redis)
        live = await state.read_live(tournament_id)
        links = await self._targets.official_stream_links(session, tournament_id)
        official = [_official_entry(link, live) for link in links]

        # ``source`` is the poller's own dedup marker: a channel that is both
        # the official broadcast and a participant's is stamped "official" and
        # belongs in the official block only, so it is not rendered twice.
        live_participants = [
            (field, snapshot)
            for field, snapshot in live.items()
            if snapshot.get("source") != "official" and _player_id(snapshot) is not None
        ]
        players = await self._load_players(
            session,
            {pid for _, snapshot in live_participants if (pid := _player_id(snapshot)) is not None},
            tournament_id,
        )
        # Fail-closed: an entry survives only when ``_load_players`` returned a
        # player for it. Three distinct cases converge here on purpose:
        #   * vetoed player -- ``_load_players`` withheld them, so the stale
        #     Redis entry goes with them;
        #   * ``player_id`` that matches no ``players.user`` row at all -- we
        #     cannot establish consent for a player we cannot read, so we do
        #     not publish;
        #   * no team once the tournament's rosters exist -- the roster gate in
        #     ``_load_players``.
        # This cannot swallow the organizer's broadcast: official links never
        # come from this list (``source == "official"`` is filtered out above)
        # and are rendered by ``_official_entry``, whose ``player`` is always
        # None by design.
        participants = [
            _entry_from_snapshot(field, snapshot, player=player)
            for field, snapshot in live_participants
            if (player := players.get(cast(int, _player_id(snapshot)))) is not None
        ]
        # Redis hash order is arbitrary; sort so the response is stable across
        # calls (it is served from a TTL cache) and the biggest audience leads.
        participants.sort(key=lambda entry: (-(entry.viewer_count or 0), entry.channel))
        return TournamentStreamsRead(official=official, participants=participants)


_reader = TournamentStreamsReader()


async def build_tournament_streams(
    session: AsyncSession,
    redis: Redis,
    tournament_id: int,
) -> TournamentStreamsRead:
    return await _reader.build(session, redis, tournament_id)


async def tournament_streams(session: AsyncSession, redis: Redis, data: dict[str, Any]) -> TournamentStreamsRead:
    """Gate, then read. The order is the contract, not a style choice.

    ``ensure_tournament_viewable`` runs FIRST, before a single stream row or Redis
    key is touched: the gateway caches this response without the viewer in the key
    (``respcache.TTLOnly``), so an ineligible viewer must be rejected before the
    shared cache is consulted (see ``shared/services/tournament/visibility.py``).
    A hidden tournament answers 404, not 403 — existence itself is not disclosed.
    """
    tournament_id = c.require_path_int(data, "tournament_id")
    await ensure_tournament_viewable(session, c.optional_actor(data), tournament_id)
    return await build_tournament_streams(session, redis, tournament_id)


def register(broker: Any, logger: Any) -> None:
    sf = db.async_session_maker

    @broker.subscriber("rpc.stream.tournament_streams")
    async def _tournament_streams(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_streams(session, realtime_redis, data)

        # exclude_none stays OFF (the envelope default): `live: null` MUST appear
        # on the wire. Dropping it would make "no live detection" indistinguishable
        # from a missing field on the frontend, which is the one distinction this
        # response exists to carry.
        return await c.envelope(logger, "tournament_streams", op, session_factory=sf)
