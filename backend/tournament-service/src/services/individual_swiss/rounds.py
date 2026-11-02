"""Rounds of an ``individual_swiss`` stage: start (freeze the pool, round 1) and the next round once one is closed.

Every round reshuffles the stage's players into new teams. A round team has no ``tournament.team``: its seat is
written with ``team_id = NULL`` and the roster, role and captain live in the ``encounter.team_member`` snapshot.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name
from shared.domain.roster import PlayerRoster
from shared.repository import BracketEncounterRepository, CatalogRoleRepository, EncounterRepository, StageRepository
from shared.repository.player_standing import PlayerStandingRepository
from shared.services.encounter.participants import MemberSnapshot, place_team
from shared.services.roster import roster_engine
from shared.services.team_format import tournament_slot_shape
from src.domain.admin.best_of import best_of_config, resolve_best_of
from src.domain.individual_swiss import (
    PoolError,
    PoolPlayer,
    StandingLine,
    check_playoff_team_count,
    pair_randomly,
    round_captain,
    score_lobbies,
    split_pool,
    split_two,
    teams_per_round,
)
from src.services.individual_swiss.standings import (
    DEFAULT_PLAYOFF_TEAMS,
    order_by_role,
    recalculate_individual_stage,
    stage_pins,
    stage_players,
)
from src.services.notifications.lifecycle import lifecycle_notifier

__all__ = ("IndividualSwissRoundsService", "individual_swiss_rounds_service")

_encounters = EncounterRepository()
_positions = BracketEncounterRepository()
_players = PlayerStandingRepository()
_roles = CatalogRoleRepository()
_stages = StageRepository()

Team = list[PoolPlayer]


def _refuse(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message})


def _roster_name(roster: PlayerRoster) -> str:
    return (roster.display_name or roster.handle or roster.player_name or f"#{roster.registration_id}")[:255]


class IndividualSwissRoundsService:
    async def start(self, session: AsyncSession, stage: models.Stage) -> list[models.Encounter]:
        """Freeze the pool as the stage's personal table and generate round 1.

        Refuses (409 ``{code, message}``) before writing anything when a registration does not name exactly one
        ranked role or the pool does not split into equal, evenly paired teams.
        """
        tournament = await session.get_one(models.Tournament, stage.tournament_id)
        shape = (await tournament_slot_shape(session, tournament.id)).slots
        rosters = await roster_engine.for_tournament(session, tournament.id, pool_only=True)

        pool: list[PoolPlayer] = []
        for roster in rosters.values():
            name = _roster_name(roster)
            if roster.workspace_member_id is None:
                raise _refuse("member_required", f"{name}: у регистрации нет участника воркспейса")
            playable = roster.playable
            if len(playable) != 1:
                raise _refuse(
                    "one_role_required",
                    f"{name}: нужна ровно одна роль с рангом, сейчас {len(playable)}",
                )
            role = playable[0].role
            pool.append(PoolPlayer(roster.workspace_member_id, roster.registration_id, name, role, playable[0].rank))
        if len({player.member_id for player in pool}) != len(pool):
            raise _refuse("duplicate_member", "Один участник воркспейса зарегистрирован дважды")
        try:
            check_playoff_team_count(
                stage.playoff_team_count or DEFAULT_PLAYOFF_TEAMS, teams_per_round(pool, shape), shape
            )
        except PoolError as exc:
            raise _refuse(exc.code, str(exc)) from exc

        await _players.delete_for_stage(session, stage.id)
        await _players.create_many(
            session,
            [
                models.PlayerStanding(
                    tournament_id=tournament.id,
                    stage_id=stage.id,
                    registration_id=player.registration_id,
                    workspace_member_id=player.member_id,
                    display_name=player.display_name,
                    role=player.role,
                    rank=player.rank,
                )
                for player in pool
            ],
        )
        # Positions, cut line and captains from the first minute, before any result exists.
        await recalculate_individual_stage(session, stage, tournament)
        return await self._generate_round(session, stage, tournament, 1)

    async def generate_ready_rounds(
        self,
        session: AsyncSession,
        tournament_id: int,
        *,
        stages: Sequence[models.Stage] | None = None,
    ) -> list[models.Encounter]:
        """Generate round ``r + 1`` of every active, unfinished individual Swiss stage whose round ``r`` is closed.

        Idempotent: the latest round is read under the stage lock, so a second call finds the new round open.
        """
        if stages is None:
            stages = (
                await session.scalars(
                    _stages.select()
                    .where(
                        models.Stage.tournament_id == tournament_id,
                        models.Stage.stage_type == enums.StageType.INDIVIDUAL_SWISS,
                        models.Stage.is_active.is_(True),
                    )
                    .options(selectinload(models.Stage.items))
                    .execution_options(populate_existing=True)
                )
            ).all()
        candidates = [
            stage
            for stage in stages
            if stage.stage_type == enums.StageType.INDIVIDUAL_SWISS and stage.is_active and not stage.is_completed
        ]
        generated: list[models.Encounter] = []
        for stage in candidates:
            await session.execute(sa.select(models.Stage.id).where(models.Stage.id == stage.id).with_for_update())
            latest = await self._latest_round(session, stage.id)
            if latest is None:
                continue
            number, statuses = latest
            if number >= stage.max_rounds or any(s != enums.EncounterStatus.COMPLETED for s in statuses):
                continue
            tournament = await session.get_one(models.Tournament, stage.tournament_id)
            generated.extend(await self._generate_round(session, stage, tournament, number + 1))
        return generated

    @staticmethod
    async def _latest_round(session: AsyncSession, stage_id: int) -> tuple[int, list[enums.EncounterStatus]] | None:
        latest = await session.scalar(
            sa.select(sa.func.max(models.BracketEncounter.round)).where(models.BracketEncounter.stage_id == stage_id)
        )
        if latest is None:
            return None
        statuses = await session.scalars(
            sa.select(models.Encounter.status)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_id == stage_id, models.BracketEncounter.round == latest)
        )
        return latest, list(statuses.all())

    async def _generate_round(
        self, session: AsyncSession, stage: models.Stage, tournament: models.Tournament, round_number: int
    ) -> list[models.Encounter]:
        rows = await stage_players(session, stage.id)
        shape = (await tournament_slot_shape(session, tournament.id)).slots
        pool = [
            PoolPlayer(row.workspace_member_id, row.registration_id, row.display_name, row.role, row.rank)
            for row in rows
        ]
        rng = random.Random(f"{stage.id}:{round_number}")
        try:
            if stage.pairing_mode == enums.StagePairingMode.BALANCE:
                pairs = pair_randomly(split_pool(pool, shape, teams_per_round(pool, shape), rng), rng)
            else:
                by_member = {player.member_id: player for player in pool}
                lines = [
                    StandingLine(
                        row.workspace_member_id,
                        row.role,
                        row.rank,
                        row.points,
                        row.maps_won - row.maps_lost,
                        row.buchholz,
                    )
                    for row in rows
                ]
                order = order_by_role(lines, await stage_pins(session, stage.id), shape)
                lobbies = score_lobbies({role: [by_member[m] for m in ids] for role, ids in order.items()}, shape)
                pairs = [split_two(lobby, shape, rng) for lobby in lobbies]
        except PoolError as exc:
            raise _refuse(exc.code, str(exc)) from exc

        sorted_items = sorted(stage.items or [], key=lambda item: (item.order, item.id))
        stage_item_id = sorted_items[0].id if sorted_items else None
        dimension = (
            await _roles.ontology(session, discipline=tournament.discipline, workspace_id=tournament.workspace_id)
        ).rated.code
        captains = [(round_captain(first), round_captain(second)) for first, second in pairs]
        names = [(f"Команда {a.display_name}"[:255], f"Команда {b.display_name}"[:255]) for a, b in captains]
        best_of = resolve_best_of(best_of_config(stage), round_number, is_final=False)

        created = [
            models.Encounter(
                workspace_id=tournament.workspace_id,
                discipline=tournament.discipline,
                tournament_id=tournament.id,
                scoring_rule_id=stage.scoring_rule_id,
                name=build_encounter_name(seat_names),
                slot_count=2,
                best_of=best_of,
                status=enums.EncounterStatus.OPEN,
            )
            for seat_names in names
        ]
        await _encounters.create_many(session, created)
        await _positions.create_many(
            session,
            [
                models.BracketEncounter(
                    encounter_id=encounter.id,
                    tournament_id=tournament.id,
                    stage_id=stage.id,
                    stage_item_id=stage_item_id,
                    round=round_number,
                )
                for encounter in created
            ],
        )
        for encounter, pair, pair_captains, pair_names in zip(created, pairs, captains, names, strict=True):
            for slot, (team, captain, name) in enumerate(zip(pair, pair_captains, pair_names, strict=True), 1):
                await place_team(
                    session,
                    encounter,
                    slot=slot,
                    team_id=None,
                    name=name,
                    seed=None,
                    members=[
                        MemberSnapshot(
                            workspace_member_id=player.member_id,
                            display_name=player.display_name,
                            rank=player.rank,
                            is_substitute=False,
                            roles=((dimension, player.role),),
                            is_captain=player is captain,
                        )
                        for player in team
                    ],
                )
        await session.flush()
        # DMs only, like a team Swiss round: a channel post per pairing is spam.
        await lifecycle_notifier.on_encounters_changed(session, created, channel=False)
        logger.info(
            "Individual Swiss: generated {} encounters for round {}",
            len(created),
            round_number,
            stage_id=stage.id,
            tournament_id=tournament.id,
        )
        return created


individual_swiss_rounds_service = IndividualSwissRoundsService()
