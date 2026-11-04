"""The two optional hooks that help a pickup mix's match reach stats: a bot-created lobby and a player's ingest status.

``DisciplineSpec.lobby_bot`` lets a module have a bot create the in-game lobby and report the match id it was played
as (a mix then files that id directly instead of searching by players); ``DisciplineSpec.ingest_status`` tells whether
a player's own client uploads their matches (what the by-players search depends on). Pure declarations: a module
implements both lazily, and core never imports the module (``shared.disciplines`` is the only door).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

__all__ = (
    "BotLobbyCreate",
    "BotLobbyFailed",
    "BotLobbyMatchId",
    "BotLobbyParty",
    "BotLobbyRateLimited",
    "BotLobbyRequest",
    "IngestClient",
    "IngestStatus",
    "IngestStatusSource",
    "LobbyBotSpec",
)


@dataclass(frozen=True, slots=True)
class BotLobbyRequest:
    """What a mix tells the bot to open: the region it plays in, its seats, and where to report the match id."""

    region: str
    #: Seats of the larger team; a module maps it to a game mode.
    team_size: int
    #: Every seated player: the lobby is not startable with fewer.
    roster_size: int
    #: Absolute URL the game source POSTs the match id to; ``None`` when the site has no public address (poll only).
    callback_url: str | None


@dataclass(frozen=True, slots=True)
class BotLobbyParty:
    party_id: str
    #: The code players enter in the game.
    party_code: str
    #: Sent back by the source on its callback, when it has one.
    callback_secret: str | None


class BotLobbyRateLimited(Exception):
    """The source refused to open another lobby for now; ``retry_after`` is its own hint in seconds, if any."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("bot lobby rate limited")
        self.retry_after = retry_after


class BotLobbyFailed(Exception):
    """The source is down or refused the request."""


#: ``create(request) -> party``; raises :class:`BotLobbyRateLimited` or :class:`BotLobbyFailed`.
BotLobbyCreate = Callable[[BotLobbyRequest], Awaitable[BotLobbyParty]]
#: ``match_id(party_id) -> match id`` once the lobby's match started, else ``None`` (also for a source that is down).
BotLobbyMatchId = Callable[[str], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class LobbyBotSpec:
    #: Server regions a host may pick; the module maps them to its source's own.
    regions: tuple[str, ...]
    default_region: str
    create: BotLobbyCreate
    match_id: BotLobbyMatchId


@dataclass(frozen=True, slots=True)
class IngestStatus:
    #: Whether the account's client uploaded a match within ``window_days``.
    active: bool
    last_upload_at: datetime | None
    window_days: int


#: ``status(account ids) -> {account id: status}``, ``None`` for an account the source could not answer for (unknown is
#: never "inactive"). The ids are the discipline's ``identity_provider`` account ids.
IngestStatusSource = Callable[[Sequence[str]], Awaitable[dict[str, IngestStatus | None]]]


@dataclass(frozen=True, slots=True)
class IngestClient:
    """Where a player gets the client that uploads their matches: its instructions first, then its installer."""

    instructions_url: str
    installer_url: str
