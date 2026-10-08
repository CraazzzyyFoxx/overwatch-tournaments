"""Which voice channels a mix may use, and who goes where.

Pure: the service hands in the workspace's voice settings, the lobbies' seats
and the members' Discord links; discord-service does the moving.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ("LobbyVoice", "MixVoiceConfig", "VoicePlan", "plan_move", "report", "snowflake", "voice_config_from")


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


@dataclass(frozen=True, slots=True)
class LobbyVoice:
    lobby_index: int
    #: Member ids per team of the lobby's selected option, team 1 first.
    teams: tuple[tuple[int, ...], ...]
    team_voice_ids: tuple[str | None, str | None]


@dataclass(slots=True)
class VoicePlan:
    #: What discord-service is asked to do.
    moves: list[dict[str, str]]
    #: People settled here, before Discord is asked: no target, a general voice as target, no link.
    rows: list[dict[str, Any]]
    #: Discord id -> member, to name discord-service's answers.
    member_by_discord: dict[str, int]


def _target_problem(config: MixVoiceConfig, channel_id: str | None) -> str | None:
    if channel_id is None:
        return "not_configured"
    # A general voice is not a team voice; whether a team voice is still in the
    # category is discord-service's call -- only it sees the guild.
    if channel_id in config.general_ids:
        return "channel_outside_category"
    return None


def plan_move(config: MixVoiceConfig, lobbies: Sequence[LobbyVoice], links: Mapping[int, str]) -> VoicePlan:
    """Every seated player to their team's voice, or the reason they are not asked for."""
    plan = VoicePlan(moves=[], rows=[], member_by_discord={})
    for lobby in lobbies:
        for team, channel_id in zip(lobby.teams, lobby.team_voice_ids, strict=False):
            problem = _target_problem(config, channel_id)
            for member_id in team:
                discord_id = links.get(member_id)
                # A bad target outranks a missing link: the host fixes the voice first.
                status = problem or (None if discord_id is not None else "no_discord_link")
                if status is not None:
                    plan.rows.append({"workspace_member_id": member_id, "status": status, "channel_id": channel_id})
                    continue
                plan.moves.append({"discord_user_id": discord_id, "channel_id": channel_id})
                plan.member_by_discord[discord_id] = member_id
    return plan


def report(plan: VoicePlan, results: Sequence[Mapping[str, Any]], names: Mapping[int, str]) -> dict[str, Any]:
    """The answer a host reads: one row per person, named the way the board names them."""
    rows: list[dict[str, Any]] = [
        {
            "workspace_member_id": row["workspace_member_id"],
            "name": names.get(row["workspace_member_id"]) or f"#{row['workspace_member_id']}",
            "status": row["status"],
            "channel_id": row["channel_id"],
        }
        for row in plan.rows
    ]
    for result in results:
        discord_id = str(result.get("discord_user_id"))
        member_id = plan.member_by_discord.get(discord_id)
        name = (names.get(member_id) if member_id is not None else None) or result.get("name") or discord_id
        rows.append(
            {
                "workspace_member_id": member_id,
                "name": name,
                "status": result.get("status") or "failed",
                "channel_id": result.get("channel_id"),
            }
        )
    return {"moved": sum(row["status"] == "moved" for row in rows), "results": rows}
