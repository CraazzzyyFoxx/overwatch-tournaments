"""The voice plan of one tournament: the whole desired state of its Discord voice channels.

Served on ``rpc.tournament.voice_plan`` and applied by discord-service; the rules are in
``docs/tournament-voice-channels.md`` ("The plan").
"""

from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.tournament_state import FINISHED_STATUSES
from shared.repository import WorkspaceMemberRepository
from shared.schemas.voice import VoicePlan, VoicePlanChannel, VoicePlanWarning
from shared.services.flow_queries import stage_node_status
from src.domain.voice import Encounter, assign_round_slots

__all__ = ("build_voice_plan",)

_members = WorkspaceMemberRepository()

#: ``Tournament.status`` after which nothing may exist.
_FINISHED = FINISHED_STATUSES
_LIVE = enums.FlowNodeStatus.LIVE
_COMPLETED = enums.FlowNodeStatus.COMPLETED
_NO_DISCORD = "player_without_discord"
#: Discord's channel name limit.
_NAME_LIMIT = 100


def _is_complete(stages: list[sa.Row]) -> bool:
    """The last stage (highest ``order``; parallel divisions share one) is completed and no stage is still live."""
    if not stages or any(stage.status == _LIVE for stage in stages):
        return False
    last = max(stage.order for stage in stages)
    return all(stage.status == _COMPLETED for stage in stages if stage.order == last)


async def _team_rosters(session: AsyncSession, tournament_id: int, stages: list[sa.Row], early_teams: bool):
    """``(team id, name)`` and each team's ``Player`` rows, for the teams that get a voice now."""
    playing = [
        stage.id for stage in stages if stage.status == _LIVE and stage.stage_type != enums.StageType.INDIVIDUAL_SWISS
    ]
    if playing:
        # ``seat_inputs`` turns every tentative input into a FINAL team: the seats of a live stage.
        seated = (
            sa.select(models.StageItemInput.team_id)
            .join(models.StageItem, models.StageItem.id == models.StageItemInput.stage_item_id)
            .where(
                models.StageItem.stage_id.in_(playing),
                models.StageItemInput.input_type == enums.StageItemInputType.FINAL,
                models.StageItemInput.team_id.is_not(None),
            )
        )
        teams_filter = models.Team.id.in_(seated)
    elif early_teams and not any(stage.is_published for stage in stages):
        teams_filter = models.Team.tournament_id == tournament_id
    else:
        return [], {}
    teams = (
        await session.execute(
            sa.select(models.Team.id, models.Team.name)
            .where(models.Team.tournament_id == tournament_id, teams_filter)
            .order_by(models.Team.id)
        )
    ).all()
    players = (
        await session.execute(
            sa.select(models.Player.team_id, models.Player.workspace_member_id, models.Player.name)
            .where(models.Player.team_id.in_([team.id for team in teams]))
            .order_by(models.Player.team_id, models.Player.workspace_member_id, models.Player.id)
        )
    ).all()
    roster: dict[int, dict[int, str]] = defaultdict(dict)
    for team_id, member_id, name in players:
        roster[team_id].setdefault(member_id, name)
    return teams, roster


async def _round_encounters(session: AsyncSession, stage_id: int):
    """Every round of an individual Swiss stage as ``Encounter`` sides, plus the member names of the latest round."""
    rows = (
        await session.execute(
            sa.select(
                models.BracketEncounter.round,
                models.BracketEncounter.encounter_id,
                models.EncounterTeam.slot,
                models.EncounterTeamMember.workspace_member_id,
                models.EncounterTeamMember.display_name_snapshot,
            )
            .select_from(models.BracketEncounter)
            .join(
                models.EncounterTeam,
                sa.and_(
                    models.EncounterTeam.encounter_id == models.BracketEncounter.encounter_id,
                    models.EncounterTeam.active.is_(True),
                ),
            )
            .join(models.EncounterTeamMember, models.EncounterTeamMember.encounter_team_id == models.EncounterTeam.id)
            .where(models.BracketEncounter.stage_id == stage_id)
            .order_by(
                models.BracketEncounter.round,
                models.BracketEncounter.encounter_id,
                models.EncounterTeam.slot,
                models.EncounterTeamMember.workspace_member_id,
            )
        )
    ).all()
    # round -> encounter -> slot -> members; an encounter with no roster yet still holds its lobby.
    tree: dict[int, dict[int, dict[int, list[int]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    names: dict[int, str] = {}
    for round_, encounter_id, slot, member_id, name in rows:
        tree[round_][encounter_id][slot].append(member_id)
        names[member_id] = name
    rounds: list[list[Encounter]] = [
        [(sides.get(1, []), sides.get(2, [])) for _id, sides in sorted(encounters.items())]
        for _round, encounters in sorted(tree.items())
    ]
    return rounds, names


async def build_voice_plan(session: AsyncSession, tournament_id: int) -> VoicePlan:
    tournament = (
        await session.execute(
            sa.select(models.Tournament.name, models.Tournament.status, models.Workspace.discord_guild_id)
            .join(models.Workspace, models.Workspace.id == models.Tournament.workspace_id)
            .where(models.Tournament.id == tournament_id)
        )
    ).first()
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    settings = await session.scalar(
        sa.select(models.TournamentVoiceSettings).where(models.TournamentVoiceSettings.tournament_id == tournament_id)
    )
    plan = VoicePlan(
        tournament_id=tournament_id,
        tournament_name=tournament.name,
        guild_id=tournament.discord_guild_id,
        enabled=bool(settings and settings.enabled),
        private=bool(settings and settings.private),
        category_id=str(settings.category_id) if settings and settings.category_id is not None else None,
        staff_role_ids=[str(role_id) for role_id in (settings.staff_role_ids if settings else [])],
    )
    if not plan.enabled or plan.guild_id is None or tournament.status in _FINISHED:
        return plan
    stages = (
        await session.execute(
            sa.select(
                models.Stage.id,
                models.Stage.stage_type,
                models.Stage.order,
                models.Stage.is_published,
                stage_node_status(models.Stage.id).label("status"),
            )
            .where(models.Stage.tournament_id == tournament_id)
            .order_by(models.Stage.order, models.Stage.id)
        )
    ).all()
    if _is_complete(stages):
        return plan

    teams, team_roster = await _team_rosters(session, tournament_id, stages, settings.early_teams)

    # Latest round of each live individual Swiss stage: its seats fill the stage's slots.
    slots: list[tuple[int, dict[int, int], int]] = []  # (stage id, member -> slot index, slot count)
    seat_names: dict[int, str] = {}
    for stage in stages:
        if stage.stage_type != enums.StageType.INDIVIDUAL_SWISS or stage.status != _LIVE:
            continue
        rounds, names = await _round_encounters(session, stage.id)
        if not rounds:
            continue
        seats = assign_round_slots(rounds)[-1]
        slots.append((stage.id, seats, 2 * len(rounds[-1])))
        seat_names.update({member_id: names[member_id] for member_id in seats})
    return await _compose(session, plan, teams, team_roster, slots, seat_names)


async def _compose(
    session: AsyncSession,
    plan: VoicePlan,
    teams: list[sa.Row],
    team_roster: dict[int, dict[int, str]],
    slots: list[tuple[int, dict[int, int], int]],
    seat_names: dict[int, str],
) -> VoicePlan:
    wanted = {member_id for roster in team_roster.values() for member_id in roster} | set(seat_names)
    # One id per member, the smallest if an account somehow carries several.
    discord: dict[int, str] = {}
    if wanted:
        for member_id, discord_id in sorted(await _members.discord_ids(session, sorted(wanted)), key=_by_id):
            discord.setdefault(member_id, str(discord_id))

    channels: list[VoicePlanChannel] = []
    routes: dict[str, str] = {}
    warnings: list[VoicePlanWarning] = []
    warned: set[int] = set()

    def warn(member_id: int, name: str, team_id: int | None) -> None:
        if member_id not in discord and member_id not in warned:
            warned.add(member_id)
            warnings.append(
                VoicePlanWarning(code=_NO_DISCORD, workspace_member_id=member_id, name=name, team_id=team_id)
            )

    for team in teams:
        roster = team_roster.get(team.id, {})
        key = f"team:{team.id}"
        channels.append(
            VoicePlanChannel(
                slot_key=key,
                kind="team",
                name=team.name[:_NAME_LIMIT],
                position=0,
                team_id=team.id,
                member_discord_ids=sorted({discord[m] for m in roster if m in discord}),
            )
        )
        for member_id, name in roster.items():
            warn(member_id, name, team.id)
            if member_id in discord:
                routes.setdefault(discord[member_id], key)

    slot_routes: dict[str, str] = {}
    for stage_id, seats, count in slots:
        by_slot: dict[int, list[int]] = defaultdict(list)
        for member_id, index in seats.items():
            by_slot[index].append(member_id)
        for index in range(count):
            key = f"slot:{stage_id}:{index}"
            members = sorted(by_slot[index])
            channels.append(
                VoicePlanChannel(
                    slot_key=key,
                    kind="swiss_slot",
                    name=f"Лобби {index // 2 + 1} · {'AB'[index % 2]}",
                    position=0,
                    stage_id=stage_id,
                    member_discord_ids=sorted({discord[m] for m in members if m in discord}),
                )
            )
            for member_id in members:
                warn(member_id, seat_names[member_id], None)
                if member_id in discord:
                    slot_routes.setdefault(discord[member_id], key)
    routes.update(slot_routes)  # a current round slot wins over the team voice

    if channels:
        hub = VoicePlanChannel(
            slot_key="hub", kind="hub", name=f"Общий · {plan.tournament_name}"[:_NAME_LIMIT], position=0
        )
        channels = [hub, *channels]
        for position, channel in enumerate(channels):
            channel.position = position
    return plan.model_copy(update={"channels": channels, "routes": routes, "warnings": warnings})


def _by_id(row: sa.Row) -> tuple[int, str]:
    return int(row[0]), str(row[1])
