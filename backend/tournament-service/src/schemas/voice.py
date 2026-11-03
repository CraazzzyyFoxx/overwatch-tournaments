"""Admin wire shapes of a tournament's voice channels (``docs/tournament-voice-channels.md``, "Admin API").

Discord snowflakes travel as strings: JSON numbers do not survive a float64 round-trip.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

__all__ = ("VoiceChannelStatus", "VoiceSettings", "VoiceStatus", "VoiceSyncIssue", "VoiceWarning")


def _fits_bigint(value: str) -> str:
    if int(value) > 2**63 - 1:
        raise ValueError("snowflake out of range")
    return value


#: Digits only, and within a signed 64-bit column (Discord ids are 17-19 digits).
Snowflake = Annotated[str, StringConstraints(pattern=r"^[1-9]\d{0,18}$"), AfterValidator(_fits_bigint)]


class VoiceSettings(BaseModel):
    enabled: bool = False
    private: bool = False
    early_teams: bool = False
    category_id: Snowflake | None = None
    staff_role_ids: list[Snowflake] = Field(default_factory=list, max_length=25)


class VoiceChannelStatus(BaseModel):
    slot_key: str
    kind: Literal["category", "hub", "team", "swiss_slot"]
    name: str | None = None
    discord_channel_id: str | None = None
    status: Literal["planned", "pending", "active", "deleting"]


class VoiceWarning(BaseModel):
    code: str
    workspace_member_id: int | None = None
    name: str | None = None
    team_id: int | None = None


class VoiceSyncIssue(BaseModel):
    code: str
    detail: str | None = None


class VoiceStatus(BaseModel):
    settings: VoiceSettings
    guild_linked: bool
    channels: list[VoiceChannelStatus]
    warnings: list[VoiceWarning]
    sync_issues: list[VoiceSyncIssue]
    last_synced_at: datetime | None = None
