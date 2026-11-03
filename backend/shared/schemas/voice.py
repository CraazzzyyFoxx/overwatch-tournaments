"""The tournament voice plan: what tournament-service wants to exist in Discord.

Served by tournament-service on ``rpc.tournament.voice_plan`` (internal, no identity) and applied by
discord-service, which diffs it against ``tournament.voice_channel``. Categories are not in the plan:
laying channels out into categories (the organizer's one, or the bot's, split at 50) is the bot's job.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = (
    "VOICE_PLAN_SUBJECT",
    "VoicePlan",
    "VoicePlanChannel",
    "VoicePlanWarning",
)

VOICE_PLAN_SUBJECT = "rpc.tournament.voice_plan"


class VoicePlanChannel(BaseModel):
    #: Stable identity across syncs: ``hub``, ``team:<team_id>``, ``slot:<stage_id>:<index>``.
    slot_key: str
    kind: Literal["hub", "team", "swiss_slot"]
    #: At most 100 characters (Discord's limit).
    name: str = Field(max_length=100)
    #: Order inside the tournament's channels; the hub is 0.
    position: int
    stage_id: int | None = None
    team_id: int | None = None
    #: Discord user ids granted access when the plan is private; empty for the hub.
    member_discord_ids: list[str] = Field(default_factory=list)


class VoicePlanWarning(BaseModel):
    #: ``player_without_discord``: a roster member with no linked Discord account.
    code: str
    workspace_member_id: int | None = None
    name: str | None = None
    team_id: int | None = None


class VoicePlan(BaseModel):
    tournament_id: int
    tournament_name: str
    #: ``Workspace.discord_guild_id``; None -> the bot cannot do anything.
    guild_id: str | None
    enabled: bool
    private: bool
    #: The organizer's existing category, or None for the bot's own.
    category_id: str | None = None
    staff_role_ids: list[str] = Field(default_factory=list)
    #: Empty when disabled or when nothing should exist (before start, after the final): the bot deletes its channels.
    channels: list[VoicePlanChannel] = Field(default_factory=list)
    #: Discord user id -> ``slot_key`` the hub sends them to (their team voice or their current Swiss round slot).
    routes: dict[str, str] = Field(default_factory=dict)
    warnings: list[VoicePlanWarning] = Field(default_factory=list)
