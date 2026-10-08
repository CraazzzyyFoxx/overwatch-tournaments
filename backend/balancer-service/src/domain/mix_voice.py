"""Which voice channels a mix may use, and who goes where.

Pure: the service hands in the workspace's voice settings, the lobbies' seats
and the members' Discord links; discord-service does the moving.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ("MixVoiceConfig", "snowflake", "voice_config_from")


@dataclass(frozen=True, slots=True)
class MixVoiceConfig:
    guild_id: str | None
    category_id: str | None
    general_ids: frozenset[str]


def snowflake(value: int | None) -> str | None:
    return None if value is None else str(value)


def voice_config_from(config_json: Any, guild_id: str | None) -> MixVoiceConfig:
    """The workspace's voice settings out of its balancer config blob."""
    blob: Mapping[str, Any] = config_json if isinstance(config_json, Mapping) else {}
    category = blob.get("mix_voice_category_id")
    general = blob.get("mix_general_voice_channel_ids")
    return MixVoiceConfig(
        guild_id=guild_id or None,
        category_id=str(category) if category else None,
        general_ids=frozenset(str(value) for value in general) if isinstance(general, list) else frozenset(),
    )
