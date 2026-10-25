"""Read model for a tournament's "who is on air" block.

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

READ-ONLY with respect to Postgres: ``tournament.*`` and ``players.*`` are owned by
other services, so there is no ``session.add`` and no ``commit`` in this path. The
batched player lookup is ``StreamTargetRepository.list_roster``; this module only
ranks and vetoes the rows it gets back.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import urlsplit

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.link import TournamentLink
from shared.repository import StreamRosterRow, StreamTargetRepository
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

__all__ = ("TournamentStreamsReader", "publishable_players", "tournament_streams_reader")

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
    live and ``StreamStateStore.write_live`` rewrites the whole set each tick, so
    the field's existence IS the liveness signal. The snapshot carries no
    ``live`` key on purpose — an always-true field would invite a reader to
    trust a stale one.

    ``player`` is required: the caller drops any entry it could not resolve a
    publishable player for (see ``TournamentStreamsReader.build``).
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


def publishable_players(rows: Sequence[StreamRosterRow]) -> dict[int, StreamPlayerRead]:
    """Name, avatar and team for every *publishable* user among ``list_roster`` rows.

    PRIVACY: the display half of the stream veto. The poll-target query keeps a
    vetoed player out of Redis only from the next tick on, so entries already in
    the hash are dropped here too: a vetoed player never becomes a map entry.

    Roster gate: before the tournament has rosters every approved registrant on
    air is a participant (streaming during ``check_in``); once ``rosters_formed``
    (carried by the same SELECT), a teamless participant is dropped.

    Shared with the VOD chronology read, so a player renders with the same team on
    the live block and under their past broadcasts.
    """
    # One user can come back on several rows (a substitute's second roster row,
    # or a multi-workspace user's unmatched join). The pick is ranked so it is a
    # function of the data alone — otherwise the participant would switch teams
    # mid-broadcast from tick to tick.
    best: dict[int, tuple[tuple[bool, bool, int], StreamRosterRow]] = {}
    for row in rows:
        # PRIVACY: the veto, applied before ranking. ``is False`` on purpose: only
        # an explicit false is a veto, so a NULL fails open rather than silently
        # un-publishing a whole tournament.
        if row.stream_visible is False:
            continue
        # A real roster row beats none, a starter beats a substitute, and
        # the lowest roster id breaks any remaining tie.
        rank = (row.roster_id is None, row.is_substitution, row.roster_id or 0)
        if (previous := best.get(row.user_id)) is None or rank < previous[0]:
            best[row.user_id] = (rank, row)
    # Tournament-wide flag, so any row answers for all; ``any`` because ``rows``
    # may be empty.
    rosters_formed = any(row.rosters_formed for row in rows)
    return {
        user_id: StreamPlayerRead(
            id=user_id,
            name=row.name,
            avatar_url=row.avatar_url,
            team=StreamTeamRead(id=row.team_id, name=row.team_name) if row.team_id is not None else None,
        )
        for user_id, (_, row) in best.items()
        if row.team_id is not None or not rosters_formed
    }


class TournamentStreamsReader:
    """Assembles the public "who is on air" block for one tournament."""

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
        """``publishable_players`` for ``player_ids``, in ONE query — a public,
        cacheable page can carry dozens of live channels."""
        if not player_ids:
            return {}
        return publishable_players(await self._rosters.list_roster(session, tournament_id, player_ids))

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
        # player for it — which drops a vetoed player's stale Redis entry, a
        # ``player_id`` with no readable ``players.user`` row (no readable consent),
        # and a teamless player once rosters exist. Official links never come from
        # this list, so the organizer's broadcast cannot be swallowed here.
        participants = [
            _entry_from_snapshot(field, snapshot, player=player)
            for field, snapshot in live_participants
            if (player := players.get(cast(int, _player_id(snapshot)))) is not None
        ]
        # Redis hash order is arbitrary; sort so the response is stable across
        # calls (it is served from a TTL cache) and the biggest audience leads.
        participants.sort(key=lambda entry: (-(entry.viewer_count or 0), entry.channel))
        return TournamentStreamsRead(official=official, participants=participants)


tournament_streams_reader = TournamentStreamsReader()
