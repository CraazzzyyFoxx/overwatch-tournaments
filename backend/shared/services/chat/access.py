"""Who somebody is inside a chat room — the one thing that varies per room kind.

The resolver answers a DOMAIN question ("is this account a captain of this
encounter / this draft session, an organizer of its workspace, or just
watching?") and nothing else. Room POLICY -- whether a spectator may read at
all, whether this account is muted -- belongs to ``ChatService``, which owns the
settings and mute tables, so every policy rule is written exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from shared.services.chat.room import ChatRoom

__all__ = ("SPECTATOR_ROLE", "ChatAccess", "ChatMembership")

#: The one role that cannot author a message, hence the one the message table
#: never stores. Kept as a constant because both the service and every resolver
#: compare against it.
SPECTATOR_ROLE = "spectator"


@dataclass(frozen=True, slots=True)
class ChatMembership:
    """What the caller is in this room.

    ``role`` is one of ``home`` / ``away`` / ``captain`` / ``player`` / ``staff`` /
    ``spectator``. All but the last are writers (``player``: a mix match's seated
    non-captain) and are snapshotted onto every message they send; ``spectator`` never is.

    ``display_name`` is resolved by the owning service because only it knows
    where a name lives for that room (a linked player for an encounter captain,
    the draft team's captain account for a draft). It is snapshotted too, so a
    later rename leaves history readable as it was.
    """

    role: str
    display_name: str
    can_write: bool
    can_moderate: bool

    @property
    def is_spectator(self) -> bool:
        return self.role == SPECTATOR_ROLE


class ChatAccess(Protocol):
    """Implemented once per room kind, in the service that owns the domain.

    MUST raise 403 when the caller may not even SEE the room (a hidden
    tournament, a missing referent). Returning a spectator membership means
    "allowed to watch this room" — whether watching includes reading the chat
    is the room's setting, decided by ``ChatService``.

    ``for_update`` is the service saying which side of the room it is on: True
    for a write (a post, a delete, moderation), where a resolver that owns a row
    lock for its referent takes it so one account's writes queue (the post rate
    limit counts, then inserts); False for the history read, which every
    spectator polls and which must never queue behind a writer.
    """

    async def resolve(
        self, session: Any, auth_user: Any | None, room: ChatRoom, *, for_update: bool
    ) -> ChatMembership: ...
