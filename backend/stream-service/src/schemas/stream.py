"""Response models for the ``rpc.stream.*`` contract.

These are the wire shape of the public tournament-streams block. The hand-written
frontend mirror is ``frontend/src/types/stream.types.ts`` (no OpenAPI codegen in
this project) — the two are kept in sync by eye, so field names and nullability
here are the contract, not an implementation detail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.schemas.base import BaseRead

__all__ = (
    "StreamEntryRead",
    "StreamPlatform",
    "StreamPlayerRead",
    "StreamPollHealthRead",
    "StreamPollStatus",
    "StreamRepollRead",
    "StreamTeamRead",
    "TournamentStreamsRead",
)

#: Detected from the link's host. ``other`` is not an error state — a link the
#: organizer typed is still worth rendering, it just has no player embed.
StreamPlatform = Literal["twitch", "youtube", "other"]


class StreamTeamRead(BaseRead):
    """The team a streaming participant plays for in THIS tournament."""

    name: str


class StreamPlayerRead(BaseRead):
    """The player behind a participant stream. Absent for an official broadcast."""

    name: str
    avatar_url: str | None = None
    team: StreamTeamRead | None = None
    """``None`` whenever the player has no roster row in this tournament.

    Rosters are drafted after registration opens, so a participant can be on air
    days before any team exists — absence is the normal early state, not a failure
    to resolve. The frontend renders the team caption only when it is set; an empty
    string would claim a nameless team.
    """


class StreamEntryRead(BaseModel):
    """One channel in the tournament's stream block."""

    platform: StreamPlatform
    #: Twitch login (lowercase), or a human-readable channel identifier — the
    #: organizer's link label, falling back to the host — on other platforms.
    channel: str
    url: str
    live: bool | None
    """Tri-state, and the ``None`` case is load-bearing.

    ``True``/``False`` — the poller HAS live detection for this channel (a
    ``twitch.tv/{login}`` page) and reports the current state; absence from the
    Redis live set means offline. ``None`` — there IS NO live detection for this
    channel: YouTube and other hosts are never polled (design A4), and neither is
    a Twitch URL that is not a channel page (``twitch.tv/videos/123``).

    ``None`` is NOT ``False``. "We do not know" must render as NO badge at all,
    not as a grey "offline" badge — see ``STREAM_STATUS_META`` in
    ``frontend/src/lib/social/stream-platform.ts``. Claiming a caster is offline when
    nobody ever checked is the one wrong answer here.
    """
    title: str | None = None
    game_name: str | None = None
    viewer_count: int | None = None
    #: Already sized (440x248) by the Helix client — never carries Twitch's
    #: ``{width}x{height}`` placeholders.
    thumbnail_url: str | None = None
    started_at: datetime | None = None
    player: StreamPlayerRead | None = None


class TournamentStreamsRead(BaseModel):
    """The whole stream block for one tournament."""

    #: Official broadcast links from ``tournament.tournament_link``, live or not —
    #: the link itself is always worth showing, so offline entries stay in.
    official: list[StreamEntryRead]
    #: Participant streams, and only the ones currently live: this list answers
    #: "who is on air right now", so an offline participant has nothing to say.
    participants: list[StreamEntryRead]


class StreamRepollRead(BaseModel):
    """202 body for ``rpc.stream.repoll``.

    Deliberately just the id: the handler does not run a poll tick, it clears the
    poll cursor so the next scheduler heartbeat is due immediately. "Accepted, not
    done" is what the 202 already says, so a constant ``queued: true`` field would
    add a word and no information.
    """

    tournament_id: int


#: Outcome of the last poll tick. Mirrors the ``status`` label on
#: ``STREAM_POLL_TICKS_TOTAL`` so the panel and Grafana never disagree.
StreamPollStatus = Literal[
    "ok",
    "empty",
    "truncated",
    "not_configured",
    "rate_limited",
    "unauthorized",
    "unavailable",
    "error",
]


class StreamPollHealthRead(BaseModel):
    """Poller health for the admin panel.

    Exists because the tick swallows its own failures by design — a Twitch outage
    must not kill the scheduler — so "polling works" and "Twitch rejected the
    credentials" both look like a page with no live badges. Without this read the
    only way to tell them apart is `docker compose logs`.

    Platform-wide, not per-workspace: there is one poller and one Redis key, so
    the numbers carry no workspace dimension and the read requires a GLOBAL
    ``stream.read`` rather than a workspace-scoped grant.
    """

    #: The live config, echoed so the panel can show interval/batch next to the
    #: outcome they produced instead of reading the settings table separately.
    enabled: bool
    interval_seconds: int
    batch_size: int

    #: ``None`` = no tick has been recorded yet. That is NOT the same as a
    #: recorded failure, and the panel says so: never-ran means the scheduler has
    #: not reached a due tick, a failure names what went wrong.
    status: StreamPollStatus | None = None
    last_run_at: datetime | None = None
    tournaments_active: int | None = None
    tournaments_updated: int | None = None
    channels_polled: int | None = None
    live_channels: int | None = None
    #: Twitch's ``Ratelimit-Remaining`` at the last call, out of an 800/min bucket
    #: shared with identity-service's OAuth logins.
    ratelimit_remaining: int | None = None
    #: Whether Twitch app credentials are present in this worker's environment.
    #: Distinguishes "operator never set them" from "Twitch refused them".
    credentials_configured: bool = False
