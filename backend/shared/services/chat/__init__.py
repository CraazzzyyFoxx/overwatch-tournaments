"""Room chat, shared by every live room.

Design: docs/plans/2026-09-21-shared-room-chat.md
"""

from shared.services.chat.access import SPECTATOR_ROLE, ChatAccess, ChatMembership
from shared.services.chat.room import CHAT_DOMAIN, ChatRoom, ChatRoomKind
from shared.services.chat.schemas import (
    HISTORY_DEFAULT,
    HISTORY_MAX,
    MAX_BODY_LENGTH,
    ChatEnvelope,
    ChatMessageRead,
    ChatMuteInput,
    ChatMuteRead,
    ChatPostInput,
    ChatSettings,
    ChatSettingsInput,
    ChatViewer,
)
from shared.services.chat.service import (
    EVENT_DELETED,
    EVENT_MESSAGE,
    EVENT_MUTED,
    EVENT_UNMUTED,
    EVENT_VISIBILITY,
    ChatService,
)

__all__ = (
    "CHAT_DOMAIN",
    "EVENT_DELETED",
    "EVENT_MESSAGE",
    "EVENT_MUTED",
    "EVENT_UNMUTED",
    "EVENT_VISIBILITY",
    "HISTORY_DEFAULT",
    "HISTORY_MAX",
    "MAX_BODY_LENGTH",
    "SPECTATOR_ROLE",
    "ChatAccess",
    "ChatEnvelope",
    "ChatMembership",
    "ChatMessageRead",
    "ChatMuteInput",
    "ChatMuteRead",
    "ChatPostInput",
    "ChatRoom",
    "ChatRoomKind",
    "ChatService",
    "ChatSettings",
    "ChatSettingsInput",
    "ChatViewer",
)
