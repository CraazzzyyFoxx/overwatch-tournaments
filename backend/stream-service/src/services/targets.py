"""Which channels the poll tick asks Twitch about, and where they come from.

Read-only, always. This service owns no table in ``tournament.*``, ``balancer.*``
or ``players.*`` and writes to none of them — the boundary rule in
``backend/docs/tournament-service-write-path-inventory.md``. Every query behind
this module lives in ``shared.repository`` (``TournamentRepository``,
``TournamentLinkRepository``, ``StreamTargetRepository``); this module owns the
domain rules on top of them — which statuses count as "active", and how a
channel's two consent sources merge when they name the same login.

Two consented sources, deliberately no third:

- **self-declared** — the registrant's ``identity_twitch`` answer behind
  ``stream_pov``, the per-tournament "yes, show my POV" checkbox players
  already tick;
- **verified** — an OAuth-proven ``social_account`` that is globally visible.

Verified wins a login collision: it carries ``provider_user_id``, which survives
a channel rename, and a typo'd self-declared nick must never shadow the proven
one. The privacy JOINs behind both sources are asserted at the SQL layer by
``backend/tests/test_stream_repository.py`` — see that file before touching
either query.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.repository import StreamTargetRepository, TournamentLinkRepository, TournamentPollTarget

__all__ = (
    "POLLED_TOURNAMENT_STATUSES",
    "TWITCH_HOSTS",
    "ParticipantChannel",
    "StreamTargetsService",
    "TournamentPollTarget",
    "platform_from_url",
    "twitch_channel_from_url",
)

#: ``check_in`` and ``draft`` are in on purpose: the official broadcast goes live
#: before the first map, and an organizer whose stream badge only appears at
#: ``live`` would rather not have the feature. ``registration`` is out — it can
#: run for weeks and would burn the shared Helix bucket on an empty hall.
#: ``completed``/``archived`` are never polled.
#:
#: Keyed on ``status``, NOT on ``Tournament.is_finished``: that flag is set by
#: separate code paths and is not kept in sync with the status enum.
POLLED_TOURNAMENT_STATUSES: Final[tuple[enums.TournamentStatus, ...]] = (
    enums.TournamentStatus.CHECK_IN,
    enums.TournamentStatus.DRAFT,
    enums.TournamentStatus.LIVE,
    enums.TournamentStatus.PLAYOFFS,
)

#: The kind stamped on ``TournamentLink`` rows this feature polls.
STREAM_LINK_KIND: Final[str] = "stream"

TWITCH_HOSTS: Final[frozenset[str]] = frozenset({"twitch.tv", "www.twitch.tv", "m.twitch.tv", "player.twitch.tv"})

_YOUTUBE_HOSTS: Final[frozenset[str]] = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtube-nocookie.com"}
)

#: Twitch paths that look like a channel but are not one. ``/videos/123`` is a
#: VOD, ``/directory/...`` a category page: pollable channel names, all of them
#: wrong.
_NON_CHANNEL_TWITCH_SEGMENTS: Final[frozenset[str]] = frozenset(
    {"videos", "directory", "collections", "team", "downloads", "p", "settings"}
)


@dataclass(frozen=True, slots=True)
class ParticipantChannel:
    """One player's Twitch channel, with the consent path that produced it."""

    player_id: int
    login: str
    provider_user_id: str | None
    source: str  # "self_declared" | "verified"


def platform_from_url(url: str) -> str:
    """``twitch`` / ``youtube`` / ``other`` from the URL host.

    Shared with the RPC read so an official link and a polled channel never
    disagree about what platform they are on.
    """
    host = (urlparse(url).hostname or "").casefold()
    if host in TWITCH_HOSTS:
        return "twitch"
    if host in _YOUTUBE_HOSTS:
        return "youtube"
    return "other"


def twitch_channel_from_url(url: str) -> str | None:
    """The channel login in a Twitch URL, or ``None`` when there is nothing to poll.

    ``None`` for a non-Twitch host, a bare ``twitch.tv/``, and for VOD/category
    paths — a caller must render those with ``live=None`` ("no detection"), never
    ``live=False`` ("checked, offline").
    """
    parsed = urlparse(url)
    if (parsed.hostname or "").casefold() not in TWITCH_HOSTS:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) != 1:
        return None
    login = segments[0].casefold()
    if login in _NON_CHANNEL_TWITCH_SEGMENTS:
        return None
    return login


class StreamTargetsService:
    """Resolves poll targets through the shared read-only repositories.

    Everything here delegates straight to ``shared.repository`` — this class
    owns the merge/dedup rule (a login seen by both consent sources keeps the
    verified one) and the batching shape (one pair of channel queries and one
    link query for every active tournament, not one pair per tournament).
    """

    def __init__(
        self,
        *,
        links: TournamentLinkRepository = TournamentLinkRepository(),
        targets: StreamTargetRepository = StreamTargetRepository(),
    ) -> None:
        self.links = links
        self.targets = targets

    async def active_tournaments(self, session: AsyncSession) -> list[TournamentPollTarget]:
        """Tournaments in a phase where somebody could be broadcasting."""
        return list(await self.targets.list_active_tournaments(session, POLLED_TOURNAMENT_STATUSES))

    async def official_stream_links(self, session: AsyncSession, tournament_id: int) -> list[models.TournamentLink]:
        """Active ``kind='stream'`` links for one tournament, in organizer order.

        ORM rows, not URLs: the RPC read renders ``label`` beside the link, and a
        second query there to fetch it would be the same JOIN twice.
        """
        return list(await self.links.list_active_by_kind(session, tournament_id, STREAM_LINK_KIND))

    async def official_stream_links_bulk(
        self, session: AsyncSession, tournament_ids: list[int]
    ) -> dict[int, list[models.TournamentLink]]:
        """``official_stream_links`` for every id in ``tournament_ids``, batched
        into one query — what the poll tick uses instead of one query per
        active tournament."""
        return await self.links.list_active_by_kind_bulk(session, tournament_ids, STREAM_LINK_KIND)

    async def participant_channels_bulk(
        self, session: AsyncSession, tournament_ids: list[int]
    ) -> dict[int, list[ParticipantChannel]]:
        """Every participant channel each of ``tournament_ids`` may broadcast,
        deduped by login, keyed by tournament.

        Two queries total regardless of how many tournaments are active — not two
        per tournament — because the underlying rows already carry
        ``tournament_id``. Two queries rather than a UNION: they select different
        columns, and keeping them apart is what lets the verified row win a
        collision by construction instead of by a CASE expression nobody would
        read again.
        """
        by_tournament: dict[int, dict[str, ParticipantChannel]] = {tid: {} for tid in tournament_ids}

        for self_declared in await self.targets.list_self_declared_channels(session, tournament_ids):
            login = str(self_declared.twitch_login or "").strip().casefold()
            if not login:
                continue
            by_tournament.setdefault(self_declared.tournament_id, {})[login] = ParticipantChannel(
                player_id=self_declared.player_id,
                login=login,
                provider_user_id=None,
                source="self_declared",
            )

        for verified in await self.targets.list_verified_channels(session, tournament_ids):
            login = str(verified.username_normalized or verified.username or "").strip().casefold()
            if not login:
                continue
            # Overwrites a self-declared entry for the same login: same channel,
            # better identifier (provider_user_id survives a rename, a login
            # does not).
            by_tournament.setdefault(verified.tournament_id, {})[login] = ParticipantChannel(
                player_id=verified.user_id,
                login=login,
                provider_user_id=verified.provider_user_id,
                source="verified",
            )

        return {
            tournament_id: [channels[login] for login in sorted(channels)]
            for tournament_id, channels in by_tournament.items()
        }
