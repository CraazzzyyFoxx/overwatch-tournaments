"""Typed request contracts for pickup mixes."""

from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from shared.core.enums import MixParticipation
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES

__all__ = (
    "CustomGameBalancerConfigPatch",
    "CustomGameCoHostPatch",
    "CustomGameCreate",
    "CustomGameDiscordChannelPatch",
    "CustomGameHostTransfer",
    "CustomGameNextMapPatch",
    "CustomGameOutcome",
    "CustomGamePlayerPatch",
    "CustomGamePlayerParticipationPatch",
    "CustomGamePlayersParticipationPatch",
    "CustomGamePointsPerWinPatch",
    "CustomGamePostDiscord",
    "CustomGameRecordOutcome",
    "CustomGameRoleMaskPatch",
    "CustomGameRosterUpdate",
    "CustomGameSeatSwap",
    "CustomGameTeamNamesPatch",
)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomGameCreate(_Request):
    name: str = Field(min_length=1, max_length=255)
    member_ids: list[int] = Field(default_factory=list, max_length=100)
    balancer_config: dict[str, Any] | None = None
    #: Start from a previous mix of this workspace: its pool, role setup, role
    #: shape, points knob, team names, solver overrides and co-hosts, but none
    #: of its played state.
    clone_from_game_id: int | None = None

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name is required")
        return trimmed


class CustomGameRosterUpdate(_Request):
    member_ids: list[int] = Field(max_length=100)


class CustomGamePlayerPatch(_Request):
    participation: MixParticipation | None = None
    roles: list[str] | None = None
    is_flex: StrictBool | None = None

    @field_validator("roles")
    @classmethod
    def _roles(cls, roles: list[str] | None) -> list[str] | None:
        if roles is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in roles:
            role = raw.strip().lower()
            if role not in REGISTRATION_ROLE_CODES:
                raise ValueError(f"unknown role {role}")
            if role not in seen:
                seen.add(role)
                normalized.append(role)
        return normalized


class CustomGamePlayerParticipationPatch(_Request):
    workspace_member_id: int
    participation: MixParticipation


class CustomGamePlayersParticipationPatch(_Request):
    players: list[CustomGamePlayerParticipationPatch] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _unique_members(self) -> CustomGamePlayersParticipationPatch:
        member_ids = [player.workspace_member_id for player in self.players]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("workspace_member_id values must be unique")
        return self


class CustomGameTeamNamesPatch(_Request):
    team_names: dict[str, str]


class CustomGameRoleMaskPatch(_Request):
    role_mask: dict[str, int] | None


class CustomGamePointsPerWinPatch(_Request):
    points_per_win: int | None


class CustomGameNextMapPatch(_Request):
    """``null`` clears the pick; the next match then records with no map."""

    map_id: int | None


class CustomGameDiscordChannelPatch(_Request):
    """The channel the mix posts its matchup to; ``null`` clears it.

    A string, not an integer: a Discord snowflake is a 64-bit id that a
    JavaScript client cannot hold losslessly as a number. Digits only, so the
    server can turn it back into the ``BIGINT`` column without guessing.
    """

    channel_id: str | None

    @field_validator("channel_id")
    @classmethod
    def _snowflake(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed.isdigit() or not (1 <= len(trimmed) <= 20):
            raise ValueError("channel_id must be a Discord id (1-20 digits)")
        return trimmed


#: Ceiling on the encoded lineup screenshot. ~6 MiB decoded: far above the
#: ~200 KB a matchup card rasterises to, far below both Discord's 10 MiB
#: attachment limit and the gateway's 12 MiB body cap (``edge/dispatch.go``).
_MAX_IMAGE_B64_LENGTH = 8 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class CustomGamePostDiscord(_Request):
    """Which balance option's lineup to post, and the PNG of it to attach.

    The image is the matchup card the host is looking at, rasterised in their
    browser (see ``frontend/src/hooks/useNodeCapture.ts``) -- the bot has no
    renderer, and a screenshot of the real card is the one thing guaranteed to
    match what the mix page shows. Omitted when the capture fails, and the
    text embed is then posted instead.
    """

    variant_index: int = Field(ge=0)
    image_b64: str | None = Field(default=None, max_length=_MAX_IMAGE_B64_LENGTH)

    @field_validator("image_b64")
    @classmethod
    def _png(cls, value: str | None) -> str | None:
        """Reject anything that is not decodable base64 of a real PNG.

        Trust boundary: this blob is forwarded to Discord unread by anything
        else, so the check that it is an image happens here or nowhere.
        """
        if value is None:
            return None
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image_b64 must be base64") from exc
        if not raw.startswith(_PNG_MAGIC):
            raise ValueError("image_b64 must be a PNG")
        return value


class CustomGameBalancerConfigPatch(_Request):
    balancer_config: dict[str, Any] | None


class CustomGameHostTransfer(_Request):
    new_host_user_id: int


class CustomGameCoHostPatch(_Request):
    co_host_user_id: int


class CustomGameSeatSwap(_Request):
    variant_index: int = Field(ge=0)
    first_uuid: str = Field(min_length=1)
    second_uuid: str = Field(min_length=1)


class CustomGameOutcome(_Request):
    winner: Literal[1, 2] | None


class CustomGameRecordOutcome(_Request):
    outcome: CustomGameOutcome
    variant_index: int = Field(ge=0)
    map_id: int | None = None
