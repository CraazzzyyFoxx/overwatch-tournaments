"""Typed request contracts for pickup mixes."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from shared.core.enums import MixParticipation, MixSelfSignup
from shared.domain.mix_lobby import MAX_LOBBIES
from shared.schemas.discipline_filter import DisciplineFilterQuery
from shared.schemas.role import RoleRef
from src.domain.mix_self_service import MAX_ROSTER

__all__ = (
    "CustomGameBalanceRequest",
    "CustomGameBanPresetPatch",
    "CustomGameCaptainPatch",
    "CustomGameCoHostPatch",
    "CustomGameCreate",
    "CustomGameDiscordLineup",
    "CustomGameDiscordView",
    "CustomGameDraftCaptainPatch",
    "CustomGameDraftPlayerAdd",
    "CustomGameDraftSeed",
    "CustomGameDraftSettingsPatch",
    "CustomGameHostTransfer",
    "CustomGameListQuery",
    "CustomGameLobbyCodePatch",
    "CustomGameLobbyCountPatch",
    "CustomGameLobbyVoice",
    "CustomGameMatchRun",
    "CustomGameMatchStart",
    "CustomGameNextMapPatch",
    "CustomGameOutcome",
    "CustomGamePlayerPatch",
    "CustomGamePlayerParticipationPatch",
    "CustomGamePlayersParticipationPatch",
    "CustomGamePostDiscord",
    "CustomGamePostSignup",
    "CustomGameRecordOutcome",
    "CustomGameRename",
    "CustomGameRosterUpdate",
    "CustomGameSeatSwap",
    "CustomGameSelfAway",
    "CustomGameSelfServicePatch",
    "CustomGameSelfUpdate",
    "CustomGameTeamNamesPatch",
    "CustomGameVariantIndexPatch",
    "CustomGameVoicePatch",
    "CustomGameVoiceRun",
)


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomGameListQuery(DisciplineFilterQuery):
    """``GET .../custom-games``: one keyset page of the workspace's mixes, newest first."""

    status: Literal["open", "history"] | None = Field(
        None, description="`open` = draft or balanced, `history` = completed or cancelled; absent = every mix."
    )
    q: Annotated[str, StringConstraints(strip_whitespace=True)] | None = Field(
        None, description="Case-insensitive substring of the mix name or its host's display name; blank = no filter."
    )
    limit: int = Field(30, ge=1, le=100, description="Page size, 1..100, default 30.")
    before_id: int | None = Field(
        None, description="Keyset cursor: only mixes with a smaller id (the previous page's `next_before_id`)."
    )


#: Trimmed before the length check, so a blank name is refused rather than stored.
_MixName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


def _dedupe_roles(roles: list[RoleRef]) -> list[RoleRef]:
    return list({(ref.dimension, ref.role): ref for ref in roles}.values())


_RoleOrder = Annotated[list[RoleRef], AfterValidator(_dedupe_roles)]


class CustomGameCreate(_Request):
    name: _MixName
    #: Required: no game is implied. A clone keeps its source's game, so the value is the source's own.
    discipline: str
    team_format_preset: str | None = Field(default=None, max_length=64)
    member_ids: list[int] = Field(default_factory=list, max_length=MAX_ROSTER)
    #: Clone the pool, role setup, frozen team format, team names and co-hosts, not played state.
    clone_from_game_id: int | None = None


class CustomGameRename(_Request):
    name: _MixName


class CustomGameRosterUpdate(_Request):
    member_ids: list[int] = Field(max_length=MAX_ROSTER)


class CustomGamePlayerPatch(_Request):
    participation: MixParticipation | None = None
    roles: _RoleOrder | None = None
    is_flex: StrictBool | None = None
    # Stepped away: in no lobby's seated set until cleared (spec §7.4).
    away: StrictBool | None = None
    # ``None`` is "auto": the balance places them wherever they fit. A patch that
    # does not mention the field leaves the pin exactly as it was.
    lobby_pin: int | None = Field(None, ge=0, le=MAX_LOBBIES - 1)


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


class _LobbyScoped(_Request):
    """Every per-match write names its lobby; ``0`` is the only one a
    single-lobby mix has, which is why it is the default."""

    lobby_index: int = Field(0, ge=0, le=MAX_LOBBIES - 1)


class CustomGameDraftSeed(_LobbyScoped):
    """Which lobby drafts its teams (spec §9.2)."""


class CustomGameDraftCaptainPatch(_LobbyScoped):
    """Replace a draft team's captain: the team and the draft player who takes over (spec §9.3, §9.5)."""

    team_id: int
    player_id: int


class CustomGameDraftPlayerAdd(_LobbyScoped):
    """A waiting player added to a lobby's draft (spec §9.5)."""

    workspace_member_id: int


class CustomGameNextMapPatch(_LobbyScoped):
    """``null`` clears the pick; the next match then records with no map."""

    map_id: int | None


class CustomGameLobbyCodePatch(_LobbyScoped):
    """The in-game lobby's join code, trimmed; ``null`` or a blank string clears it."""

    lobby_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] | None


class CustomGameVariantIndexPatch(_LobbyScoped):
    """Which stored balance option the lobby shows, for every viewer at once."""

    variant_index: int = Field(ge=0)


class CustomGameBalanceRequest(_LobbyScoped):
    """What to balance. An empty body is the first lobby.

    ``scope="all"`` reshuffles every lobby at once and needs ``lobby_count >= 2``.
    """

    scope: Literal["lobby", "all"] = "lobby"


class CustomGamePostDiscord(_LobbyScoped):
    """Which balance option's lineup to post; discord-service renders the card."""

    variant_index: int = Field(ge=0)


class CustomGameDiscordLineup(_Request):
    """One posted lineup card, by its slot: the lobby and the match it announces."""

    lobby_index: int = Field(ge=0, le=MAX_LOBBIES - 1)
    match_number: int = Field(ge=1)


class CustomGameDiscordView(_Request):
    """``rpc.balancer.custom.discord_view``: the mix, and the lineup cards the bot is rendering."""

    custom_game_id: int
    # Plenty for every lineup a mix keeps live; bounds the reads one call makes.
    lineups: list[CustomGameDiscordLineup] = Field(default_factory=list, max_length=64)


class CustomGameHostTransfer(_Request):
    new_host_user_id: int


class CustomGameCoHostPatch(_Request):
    co_host_user_id: int


class CustomGameSeatSwap(_LobbyScoped):
    variant_index: int = Field(ge=0)
    first_uuid: str = Field(min_length=1)
    second_uuid: str = Field(min_length=1)


class CustomGameCaptainPatch(_LobbyScoped):
    """Who captains their team in the lobby's shown option."""

    workspace_member_id: int


class CustomGameOutcome(_Request):
    winner: Literal[1, 2] | None


class CustomGameRecordOutcome(_LobbyScoped):
    """The result of the lobby's live match; its seats and map were fixed when it started."""

    outcome: CustomGameOutcome


class CustomGameMatchRun(_LobbyScoped):
    """Which lobby's match to cancel."""


class CustomGameMatchStart(_LobbyScoped):
    """Which lobby's match to start, and whether the host swaps the computed ban opener (spec §8.3)."""

    flip_opener: StrictBool = False


class CustomGameSelfUpdate(_Request):
    """What a PLAYER may change about their own seat.

    ``roles`` absent means "leave my role order alone"; ``roles: null`` means
    "every role I have a rank for". The two are distinguished by
    ``model_fields_set``, so a flex toggle cannot silently reset a role order.
    """

    roles: _RoleOrder | None = None
    is_flex: StrictBool | None = None


class CustomGameSelfAway(_Request):
    """The player's own away switch: ``true`` steps away, ``false`` comes back."""

    away: StrictBool


class CustomGameSelfServicePatch(_Request):
    """The host's self-service switches: the signup mode and the role-edit flag."""

    self_signup: MixSelfSignup | None = None
    self_role_edit: StrictBool | None = None


class CustomGameBanPresetPatch(_Request):
    """The mix's hero room: its ban preset (``null`` turns bans off) and, when sent, Fearless (spec §11.4) and the
    clocks. The clocks tell "omitted" (unchanged) from ``null`` (the preset's own) by ``model_fields_set``."""

    hero_ban_preset: str | None = Field(max_length=64)
    #: Omitted = unchanged. On: a player cannot pick a hero they were recorded on earlier in this mix.
    hero_fearless: StrictBool | None = None
    #: Seconds per ban (and protect) step / per pick step of the next room; an all-at-once pick is one step.
    hero_ban_seconds: int | None = Field(default=None, ge=10, le=600)
    hero_pick_seconds: int | None = Field(default=None, ge=10, le=600)


class CustomGameDraftSettingsPatch(_Request):
    """How the mix's lobbies form their teams by default, and the draft's pick clock (spec §4.3)."""

    team_formation: Literal["balance", "draft"]
    draft_pick_seconds: int = Field(ge=10, le=600)


class CustomGamePostSignup(_Request):
    """Which signup mode the posted card opens. ``closed`` is not a choice here:
    posting a card that refuses every click is never the intent."""

    self_signup: Literal["pool", "benched"]


class CustomGameLobbyCountPatch(_Request):
    """How many lobbies the mix runs at once."""

    lobby_count: int = Field(ge=1, le=MAX_LOBBIES)


#: A Discord id on the wire: digits in a string, because JSON has one number
#: type and a snowflake does not survive a float64 round-trip.
_Snowflake = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{1,20}$")]


class CustomGameLobbyVoice(_LobbyScoped):
    team1_voice_channel_id: _Snowflake | None = None
    team2_voice_channel_id: _Snowflake | None = None

    @model_validator(mode="after")
    def _two_rooms(self) -> CustomGameLobbyVoice:
        if self.team1_voice_channel_id is not None and self.team1_voice_channel_id == self.team2_voice_channel_id:
            raise ValueError("the two teams need two different voices")
        return self


class CustomGameVoicePatch(_Request):
    """The mix's voices: its general voice and the team voices of every listed lobby.

    ``general_voice_channel_id`` is always replaced; a lobby left out of
    ``lobbies`` keeps its voices. Nothing is checked against Discord here --
    a voice outside the category is refused when people are moved.
    """

    general_voice_channel_id: _Snowflake | None = None
    lobbies: list[CustomGameLobbyVoice] = Field(default_factory=list, max_length=MAX_LOBBIES)

    @model_validator(mode="after")
    def _unique_lobbies(self) -> CustomGameVoicePatch:
        indexes = [lobby.lobby_index for lobby in self.lobbies]
        if len(indexes) != len(set(indexes)):
            raise ValueError("lobby_index values must be unique")
        return self


class CustomGameVoiceRun(_Request):
    """Which lobby to move; ``null`` is every lobby of the mix."""

    lobby_index: int | None = Field(None, ge=0, le=MAX_LOBBIES - 1)
