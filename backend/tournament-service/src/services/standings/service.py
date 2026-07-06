import typing
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.core import enums
from shared.core.enums import StageType
from shared.services.bracket.swiss_settings import swiss_bye_counts, swiss_scope_stopped
from shared.services.tournament_utils import (
    completed_encounters as _shared_completed_encounters,
)
from shared.services.tournament_utils import (
    completed_encounters_in_finished_rounds as _shared_completed_encounters_in_finished_rounds,
)
from shared.services.tournament_utils import sort_bracket_matches
from src import models, schemas
from src.core import utils
from src.services.encounter import service as encounter_service
from src.services.team import service as team_service

GROUP_STAGE_TYPES = {StageType.ROUND_ROBIN, StageType.SWISS}
ELIMINATION_STAGE_TYPES = {
    StageType.SINGLE_ELIMINATION,
    StageType.DOUBLE_ELIMINATION,
}
DEFAULT_STAGE_MAX_ROUNDS = 5

RULE_PRESET_DEFAULTS: dict[str, list[str]] = {
    "challonge_round_robin": [
        "points",
        "head_to_head",
        "median_buchholz",
        "match_wins",
        "score_differential",
    ],
    "challonge_swiss": [
        "points",
        "median_buchholz",
        "buchholz",
        "match_wins",
        "score_differential",
    ],
    "bracket_default": [
        "points",
        "head_to_head",
        "median_buchholz",
        "score_differential",
        "match_wins",
    ],
}


@dataclass
class RankedStageTeam:
    team_id: int
    matches: int = 0
    wins: int = 0
    draws: int = 0
    loses: int = 0
    points: float = 0.0
    opponents: list[int] = field(default_factory=list)
    buchholz: float = 0.0
    median_buchholz: float = 0.0
    head_to_head: int = 0
    score_differential: int = 0


def _entity_requested(in_entities: list[str], entity: str) -> bool:
    return entity in in_entities or any(item.startswith(f"{entity}.") for item in in_entities)


def standing_entities(in_entities: list[str]) -> list[_AbstractLoad]:
    entities: list[_AbstractLoad] = []
    stage_entity = sa.orm.selectinload(models.Standing.stage)
    stage_item_entity = sa.orm.selectinload(models.Standing.stage_item)
    entities.append(stage_entity)
    entities.append(stage_item_entity)

    if "tournament" in in_entities:
        entities.append(sa.orm.selectinload(models.Standing.tournament))
    if "group" in in_entities:
        entities.append(sa.orm.selectinload(models.Standing.group))
    if _entity_requested(in_entities, "team"):
        team_entity = sa.orm.selectinload(models.Standing.team)
        entities.append(team_entity)
        entities.extend(team_service.team_entities(utils.prepare_entities(in_entities, "team"), team_entity))
    return entities


async def get_by_tournament(
    session: AsyncSession, tournament: models.Tournament, entities: list[str]
) -> typing.Sequence[models.Standing]:
    query = (
        sa.select(models.Standing)
        .options(*standing_entities(entities))
        .where(sa.and_(models.Standing.tournament_id == tournament.id))
        .order_by(
            models.Standing.overall_position.desc(),
            models.Standing.stage_id.asc().nullslast(),
            models.Standing.stage_item_id.asc().nullslast(),
            models.Standing.position.asc(),
        )
    )
    result = await session.execute(query)
    standings = result.scalars().all()
    logger.debug(f"Retrieved {len(standings)} standings for tournament {tournament.id}")
    return standings


async def get_completed_match_history_by_tournament(
    session: AsyncSession,
    tournament_id: int,
) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .where(
            models.Encounter.tournament_id == tournament_id,
            models.Encounter.home_team_id.isnot(None),
            models.Encounter.away_team_id.isnot(None),
            sa.or_(
                models.Encounter.status == enums.EncounterStatus.COMPLETED,
                models.Encounter.result_status == enums.EncounterResultStatus.CONFIRMED,
            ),
        )
        .order_by(
            models.Encounter.stage_id.asc().nullslast(),
            models.Encounter.stage_item_id.asc().nullslast(),
            sa.func.abs(models.Encounter.round).asc(),
            models.Encounter.round.desc(),
            models.Encounter.id.asc(),
        )
    )
    result = await session.execute(query)
    return result.scalars().all()


async def delete_by_tournament(session: AsyncSession, tournament_id: int, *, commit: bool = True) -> None:
    """Delete all Standing rows for a tournament.

    When called as part of :func:`recalculate_for_tournament` we pass
    ``commit=False`` so that the DELETE and the subsequent INSERT land in the
    same transaction — avoiding the brief window where the table is empty
    (Phase D: transactional recalculation).
    """
    query = sa.delete(models.Standing).where(sa.and_(models.Standing.tournament_id == tournament_id))
    await session.execute(query)
    if commit:
        await session.commit()
    logger.info(f"Deleted standings for tournament {tournament_id}")


async def get_tournament_for_standings(
    session: AsyncSession,
    tournament_id: int,
) -> models.Tournament | None:
    result = await session.execute(
        sa.select(models.Tournament)
        .where(models.Tournament.id == tournament_id)
        .options(
            selectinload(models.Tournament.groups),
            selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs),
        )
    )
    return result.unique().scalars().first()


async def recalculate_for_tournament(
    session: AsyncSession,
    tournament_id: int,
    *,
    commit: bool = True,
) -> typing.Sequence[models.Standing]:
    """Delete + rebuild standings for a tournament atomically.

    Everything happens in a single transaction: readers never observe an
    empty standings table mid-recalculation.
    """
    await delete_by_tournament(session, tournament_id, commit=False)
    tournament = await get_tournament_for_standings(session, tournament_id)
    if tournament is None:
        if commit:
            await session.commit()
        else:
            await session.flush()
        return []
    return await calculate_for_tournament(session, tournament, commit=commit)


def _completed_encounters(
    encounters: typing.Sequence[models.Encounter],
) -> list[models.Encounter]:
    """Phase E: delegate to shared predicate to avoid drift between services."""
    return _shared_completed_encounters(encounters)


def _completed_encounters_in_finished_rounds(
    encounters: typing.Sequence[models.Encounter],
) -> list[models.Encounter]:
    """Ignore partially completed playable rounds for standings purposes."""
    return _shared_completed_encounters_in_finished_rounds(encounters)


def _stage_settings(stage: models.Stage | None) -> dict:
    raw = stage.settings_json if stage and stage.settings_json else {}
    return raw if isinstance(raw, dict) else {}


def _stage_max_rounds(stage: models.Stage) -> int:
    raw_value = getattr(stage, "max_rounds", DEFAULT_STAGE_MAX_ROUNDS)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_STAGE_MAX_ROUNDS
    return max(1, value)


def _swiss_scope_completed(total: int, completed: int, max_round: int, max_rounds: int) -> bool:
    return total > 0 and completed == total and max_round >= max_rounds


def _rule_profile(stage: models.Stage) -> str:
    settings = _stage_settings(stage)
    if isinstance(settings.get("ranking_preset"), str):
        return settings["ranking_preset"]
    if stage.stage_type == StageType.SWISS:
        return "challonge_swiss"
    if stage.stage_type == StageType.ROUND_ROBIN:
        return "challonge_round_robin"
    return "bracket_default"


def _tiebreak_order(stage: models.Stage) -> list[str]:
    settings = _stage_settings(stage)
    explicit = settings.get("tiebreak_order")
    if isinstance(explicit, list):
        filtered = [str(metric) for metric in explicit if isinstance(metric, str)]
        if filtered:
            return filtered
    return RULE_PRESET_DEFAULTS.get(_rule_profile(stage), RULE_PRESET_DEFAULTS["bracket_default"])


def _manual_positions(stage: models.Stage) -> dict[int, int]:
    settings = _stage_settings(stage)
    raw = settings.get("manual_positions")
    if not isinstance(raw, dict):
        return {}
    output: dict[int, int] = {}
    for team_id, position in raw.items():
        try:
            output[int(team_id)] = int(position)
        except (TypeError, ValueError):
            continue
    return output


def _scoring(stage: models.Stage, tournament: models.Tournament) -> tuple[float, float, float]:
    settings = _stage_settings(stage)
    scoring = settings.get("scoring")
    if isinstance(scoring, dict):
        return (
            float(scoring.get("win", tournament.win_points)),
            float(scoring.get("draw", tournament.draw_points)),
            float(scoring.get("loss", tournament.loss_points)),
        )
    return tournament.win_points, tournament.draw_points, tournament.loss_points


def _metric_value(
    team: RankedStageTeam,
    metric: str,
    *,
    manual_positions: dict[int, int],
) -> float | int:
    if metric == "points":
        return team.points
    if metric == "match_wins":
        return team.wins
    if metric == "head_to_head":
        return team.head_to_head
    if metric == "buchholz":
        return team.buchholz
    if metric == "median_buchholz":
        return team.median_buchholz
    if metric in {"score_differential", "map_differential"}:
        return team.score_differential
    if metric == "wins_as_higher_stage_specific_metric":
        return team.wins
    if metric == "manual_override":
        return -manual_positions.get(team.team_id, 10**9)
    return 0


def _sort_ranked_teams(
    teams: list[RankedStageTeam],
    *,
    tiebreak_order: list[str],
    manual_positions: dict[int, int],
) -> list[RankedStageTeam]:
    ordered = list(teams)
    for metric in reversed(tiebreak_order):
        reverse = metric != "manual_override"
        ordered.sort(
            key=lambda team: _metric_value(team, metric, manual_positions=manual_positions),
            reverse=reverse,
        )
    return ordered


def _calculate_buchholz(
    teams_by_id: dict[int, RankedStageTeam],
) -> None:
    for team in teams_by_id.values():
        opponent_scores = [
            teams_by_id[opponent_id].points for opponent_id in team.opponents if opponent_id in teams_by_id
        ]
        team.buchholz = float(sum(opponent_scores))
        if len(opponent_scores) > 2:
            trimmed = sorted(opponent_scores)[1:-1]
            team.median_buchholz = float(sum(trimmed))
        else:
            team.median_buchholz = float(sum(opponent_scores))


def _calculate_head_to_head(
    teams_by_id: dict[int, RankedStageTeam],
    encounters: typing.Sequence[models.Encounter],
) -> None:
    points_buckets: dict[float, set[int]] = defaultdict(set)
    for team in teams_by_id.values():
        points_buckets[team.points].add(team.team_id)

    for team_ids in points_buckets.values():
        if len(team_ids) < 2:
            continue
        for encounter in encounters:
            if encounter.home_team_id not in team_ids or encounter.away_team_id not in team_ids:
                continue
            if encounter.home_score > encounter.away_score:
                teams_by_id[encounter.home_team_id].head_to_head += 1
            elif encounter.away_score > encounter.home_score:
                teams_by_id[encounter.away_team_id].head_to_head += 1


def prepare_teams_for_groups(
    encounters: typing.Sequence[models.Encounter],
    *,
    seed_team_ids: typing.Sequence[int] | None = None,
    bye_counts: dict[int, int] | None = None,
    bye_points: float = 1.0,
    win_points: float = 1.0,
    draw_points: float = 0.5,
    loss_points: float = 0.0,
    tiebreak_order: list[str] | None = None,
    manual_positions: dict[int, int] | None = None,
) -> list[RankedStageTeam]:
    completed_encounters = _completed_encounters_in_finished_rounds(encounters)
    team_cache: dict[int, RankedStageTeam] = {}

    for team_id in seed_team_ids or []:
        team_cache.setdefault(team_id, RankedStageTeam(team_id=team_id))

    for encounter in completed_encounters:
        for team_id in (encounter.home_team_id, encounter.away_team_id):
            if team_id not in team_cache:
                team_cache[team_id] = RankedStageTeam(team_id=team_id)

        home_team = team_cache[typing.cast(int, encounter.home_team_id)]
        away_team = team_cache[typing.cast(int, encounter.away_team_id)]

        home_team.matches += 1
        away_team.matches += 1
        home_team.opponents.append(away_team.team_id)
        away_team.opponents.append(home_team.team_id)
        home_team.score_differential += encounter.home_score - encounter.away_score
        away_team.score_differential += encounter.away_score - encounter.home_score

        if encounter.home_score > encounter.away_score:
            home_team.wins += 1
            home_team.points += win_points
            away_team.loses += 1
            away_team.points += loss_points
        elif encounter.home_score < encounter.away_score:
            away_team.wins += 1
            away_team.points += win_points
            home_team.loses += 1
            home_team.points += loss_points
        else:
            home_team.draws += 1
            home_team.points += draw_points
            away_team.draws += 1
            away_team.points += draw_points

    for team_id, bye_count in (bye_counts or {}).items():
        team_cache.setdefault(team_id, RankedStageTeam(team_id=team_id))
        team_cache[team_id].points += max(0, bye_count) * bye_points

    _calculate_buchholz(team_cache)
    _calculate_head_to_head(team_cache, completed_encounters)
    return _sort_ranked_teams(
        list(team_cache.values()),
        tiebreak_order=tiebreak_order or RULE_PRESET_DEFAULTS["bracket_default"],
        manual_positions=manual_positions or {},
    )


def prepare_teams_for_playoffs_double_elimination(
    encounters: typing.Sequence[models.Encounter],
) -> list[schemas.StandingTeamDataWithRanking]:
    logger.info("Preparing teams for double elimination playoffs")
    completed_encounters = _completed_encounters_in_finished_rounds(encounters)
    participants = list(
        {match.home_team_id for match in completed_encounters} | {match.away_team_id for match in completed_encounters}
    )
    data: dict[int, dict[str, float | int]] = {
        typing.cast(int, participant): {"win": 0, "lose": 0, "placement": 0} for participant in participants
    }

    upper_bracket = sorted(
        [encounter for encounter in completed_encounters if encounter.round > 0],
        key=lambda encounter: encounter.round,
        reverse=True,
    )
    if upper_bracket:
        last_game = upper_bracket[0]
        if last_game.home_score > last_game.away_score:
            data[typing.cast(int, last_game.home_team_id)]["placement"] = 1
            data[typing.cast(int, last_game.away_team_id)]["placement"] = 2
        else:
            data[typing.cast(int, last_game.away_team_id)]["placement"] = 1
            data[typing.cast(int, last_game.home_team_id)]["placement"] = 2

    for encounter in completed_encounters:
        if encounter.home_score > encounter.away_score:
            data[typing.cast(int, encounter.home_team_id)]["win"] += 1
            data[typing.cast(int, encounter.away_team_id)]["lose"] += 1
        else:
            data[typing.cast(int, encounter.away_team_id)]["win"] += 1
            data[typing.cast(int, encounter.home_team_id)]["lose"] += 1

    lower_bracket_games: dict[int, list[models.Encounter]] = {}
    global_placement = len(participants)

    for encounter in [encounter for encounter in completed_encounters if encounter.round < 0]:
        lower_bracket_games.setdefault(encounter.round, []).append(encounter)

    for matches in lower_bracket_games.values():
        losers: list[int] = []
        for match in matches:
            if match.home_score > match.away_score:
                losers.append(typing.cast(int, match.away_team_id))
            else:
                losers.append(typing.cast(int, match.home_team_id))

        global_placement -= len(losers) - 1
        for loser in losers:
            data[loser]["placement"] = global_placement
        global_placement -= 1

    output: list[schemas.StandingTeamDataWithRanking] = []
    for team_id, team_data in data.items():
        output.append(
            schemas.StandingTeamDataWithRanking(
                id=team_id,
                wins=int(team_data["win"]),
                loses=int(team_data["lose"]),
                draws=0,
                points=0,
                ranking=team_data["placement"],
                opponents=[],
                matches=int(team_data["win"]) + int(team_data["lose"]),
            )
        )
    return output


def prepare_teams_for_playoffs_single_elimination(
    encounters: typing.Sequence[models.Encounter],
) -> list[schemas.StandingTeamDataWithRanking]:
    logger.info("Preparing teams for single elimination playoffs")
    completed_encounters = _completed_encounters_in_finished_rounds(encounters)
    participants = list(
        {match.home_team_id for match in completed_encounters} | {match.away_team_id for match in completed_encounters}
    )

    data: dict[int, dict[str, float | int]] = {
        typing.cast(int, participant): {"win": 0, "lose": 0, "placement": 0} for participant in participants
    }
    round_of_loss: dict[int, int | None] = {typing.cast(int, team): None for team in participants}

    for encounter in completed_encounters:
        if encounter.home_score > encounter.away_score:
            winner_id = typing.cast(int, encounter.home_team_id)
            loser_id = typing.cast(int, encounter.away_team_id)
        else:
            winner_id = typing.cast(int, encounter.away_team_id)
            loser_id = typing.cast(int, encounter.home_team_id)

        data[winner_id]["win"] += 1
        data[loser_id]["lose"] += 1

        if round_of_loss[loser_id] is None:
            round_of_loss[loser_id] = encounter.round

    valid_rounds = [encounter.round for encounter in completed_encounters if encounter.round > 0]
    if not valid_rounds:
        return [
            schemas.StandingTeamDataWithRanking(
                id=team_id,
                wins=int(data[team_id]["win"]),
                loses=int(data[team_id]["lose"]),
                draws=0,
                points=0,
                ranking=0,
                opponents=[],
                matches=int(data[team_id]["win"]) + int(data[team_id]["lose"]),
            )
            for team_id in data
        ]

    final_round = max(valid_rounds)
    final_matches = [encounter for encounter in completed_encounters if encounter.round == final_round]
    for final_match in final_matches:
        if final_match.home_score > final_match.away_score:
            data[typing.cast(int, final_match.home_team_id)]["placement"] = 1
            data[typing.cast(int, final_match.away_team_id)]["placement"] = 2
        else:
            data[typing.cast(int, final_match.away_team_id)]["placement"] = 1
            data[typing.cast(int, final_match.home_team_id)]["placement"] = 2

    round_losers: dict[int, list[int]] = defaultdict(list)
    for team_id, match_round in round_of_loss.items():
        if match_round is not None and data[team_id]["placement"] not in (1, 2):
            round_losers[match_round].append(team_id)

    current_place = 3
    for match_round in sorted(round_losers.keys(), reverse=True):
        losers_in_round = round_losers[match_round]
        for team_id in losers_in_round:
            data[team_id]["placement"] = current_place
        current_place += len(losers_in_round)

    output: list[schemas.StandingTeamDataWithRanking] = []
    for team_id, stats in data.items():
        output.append(
            schemas.StandingTeamDataWithRanking(
                id=team_id,
                wins=int(stats["win"]),
                loses=int(stats["lose"]),
                draws=0,
                points=0,
                ranking=stats["placement"],
                opponents=[],
                matches=int(stats["win"]) + int(stats["lose"]),
            )
        )
    return output


PLAYOFF_CALCULATORS: dict[
    StageType,
    Callable[
        [typing.Sequence[models.Encounter]],
        list[schemas.StandingTeamDataWithRanking],
    ],
] = {
    StageType.SINGLE_ELIMINATION: prepare_teams_for_playoffs_single_elimination,
    StageType.DOUBLE_ELIMINATION: prepare_teams_for_playoffs_double_elimination,
}


def _infer_stage_type_from_encounters(
    encounters: typing.Sequence[models.Encounter],
) -> StageType:
    has_negative = any(encounter.round < 0 for encounter in encounters)
    return StageType.DOUBLE_ELIMINATION if has_negative else StageType.SINGLE_ELIMINATION


def _resolve_compat_group_id(
    tournament: models.Tournament,
    stage: models.Stage,
    stage_item: models.StageItem | None,
) -> int | None:
    """Resolve the legacy ``TournamentGroup`` id for a given stage/stage_item.

    Returns ``None`` if no compat-group exists — this is valid now that
    ``Standing.group_id`` is nullable (Phase A). Callers must tolerate ``None``.
    """
    groups = list(getattr(tournament, "groups", []) or [])
    stage_candidates = [group for group in groups if group.stage_id == stage.id]

    if stage_item is not None:
        item_name = stage_item.name.strip().lower()
        exact_match = [group for group in stage_candidates if group.name.strip().lower() == item_name]
        if exact_match:
            return exact_match[0].id

    if len(stage_candidates) == 1:
        return stage_candidates[0].id

    if stage_item is None:
        stage_name_match = [group for group in groups if group.name.strip().lower() == stage.name.strip().lower()]
        if stage_name_match:
            return stage_name_match[0].id

    fallback_candidates = [group for group in groups if group.is_groups == (stage.stage_type in GROUP_STAGE_TYPES)]
    if stage_item is not None:
        item_name = stage_item.name.strip().lower()
        fallback_exact = [group for group in fallback_candidates if group.name.strip().lower() == item_name]
        if fallback_exact:
            return fallback_exact[0].id

    if stage_candidates:
        return stage_candidates[0].id
    if fallback_candidates:
        return fallback_candidates[0].id

    # Phase A: Standing.group_id is nullable, so missing compat-group is no
    # longer a hard error — log and proceed without one.
    logger.debug(
        "No compat TournamentGroup for tournament=%s stage=%s; Standing.group_id will be NULL",
        tournament.id,
        stage.id,
    )
    return None


def _stage_item_team_ids(stage_item: models.StageItem | None) -> list[int]:
    if stage_item is None:
        return []

    team_ids: list[int] = []
    seen: set[int] = set()
    for stage_input in sorted(stage_item.inputs, key=lambda item: item.slot):
        if stage_input.team_id is None or stage_input.team_id in seen:
            continue
        team_ids.append(stage_input.team_id)
        seen.add(stage_input.team_id)
    return team_ids


def _build_group_stage_standings(
    tournament: models.Tournament,
    stage: models.Stage,
    stage_item: models.StageItem | None,
    encounters: typing.Sequence[models.Encounter],
) -> list[models.Standing]:
    seed_team_ids = _stage_item_team_ids(stage_item)
    if not encounters and not seed_team_ids:
        return []

    tiebreak_order = _tiebreak_order(stage)
    manual_positions = _manual_positions(stage)
    win_points, draw_points, loss_points = _scoring(stage, tournament)
    settings = _stage_settings(stage)
    bye_points = float(settings.get("swiss_bye_points", win_points))
    bye_counts = (
        swiss_bye_counts(stage, stage_item.id if stage_item is not None else None)
        if stage.stage_type == StageType.SWISS
        else {}
    )
    compat_group_id = _resolve_compat_group_id(tournament, stage, stage_item)

    teams = prepare_teams_for_groups(
        encounters,
        seed_team_ids=seed_team_ids,
        bye_counts=bye_counts,
        bye_points=bye_points,
        win_points=win_points,
        draw_points=draw_points,
        loss_points=loss_points,
        tiebreak_order=tiebreak_order,
        manual_positions=manual_positions,
    )

    standings: list[models.Standing] = []
    for position, team in enumerate(teams, 1):
        standings.append(
            models.Standing(
                tournament_id=tournament.id,
                group_id=compat_group_id,
                team_id=team.team_id,
                stage_id=stage.id,
                stage_item_id=stage_item.id if stage_item is not None else None,
                position=position,
                overall_position=0,
                matches=team.matches,
                win=team.wins,
                draw=team.draws,
                lose=team.loses,
                points=team.points,
                buchholz=team.median_buchholz,
                tb=team.head_to_head,
                score_differential=team.score_differential,
                stage=stage,
                stage_item=stage_item,
            )
        )
    return standings


def _build_elimination_stage_standings(
    tournament: models.Tournament,
    stage: models.Stage,
    encounters: typing.Sequence[models.Encounter],
) -> list[models.Standing]:
    # Collect all team ids participating in this stage from inputs.
    seed_team_ids: list[int] = []
    seen: set[int] = set()
    for item in sorted(stage.items, key=lambda it: (it.order, it.id)):
        for inp in sorted(item.inputs, key=lambda i: i.slot):
            if inp.team_id is not None and inp.team_id not in seen:
                seed_team_ids.append(inp.team_id)
                seen.add(inp.team_id)

    if not encounters and not seed_team_ids:
        return []

    compat_group_id = _resolve_compat_group_id(tournament, stage, None)

    if not encounters:
        # No matches played yet — create placeholder standings with position 0.
        standings: list[models.Standing] = []
        for team_id in seed_team_ids:
            standings.append(
                models.Standing(
                    tournament_id=tournament.id,
                    group_id=compat_group_id,
                    team_id=team_id,
                    stage_id=stage.id,
                    stage_item_id=None,
                    position=0,
                    overall_position=0,
                    matches=0,
                    win=0,
                    draw=0,
                    lose=0,
                    points=0,
                    buchholz=None,
                    tb=None,
                    stage=stage,
                )
            )
        return standings

    stage_type = stage.stage_type or _infer_stage_type_from_encounters(encounters)
    calculator = PLAYOFF_CALCULATORS.get(stage_type, prepare_teams_for_playoffs_single_elimination)
    teams = calculator(encounters)
    teams_with_standings = {team.id for team in teams}

    standings = []
    for team in teams:
        standings.append(
            models.Standing(
                tournament_id=tournament.id,
                group_id=compat_group_id,
                team_id=team.id,
                stage_id=stage.id,
                stage_item_id=None,
                position=int(team.ranking),
                overall_position=int(team.ranking),
                matches=team.matches,
                win=team.wins,
                draw=team.draws,
                lose=team.loses,
                points=team.points,
                buchholz=None,
                tb=None,
                stage=stage,
            )
        )
    # Teams that have not played any completed match yet get a placeholder row.
    for team_id in seed_team_ids:
        if team_id not in teams_with_standings:
            standings.append(
                models.Standing(
                    tournament_id=tournament.id,
                    group_id=compat_group_id,
                    team_id=team_id,
                    stage_id=stage.id,
                    stage_item_id=None,
                    position=0,
                    overall_position=0,
                    matches=0,
                    win=0,
                    draw=0,
                    lose=0,
                    points=0,
                    buchholz=None,
                    tb=None,
                    stage=stage,
                )
            )
    return standings


def _sort_for_overall(standings: list[models.Standing], stage_order: dict[int, int]) -> list[models.Standing]:
    return sorted(
        standings,
        key=lambda standing: (
            stage_order.get(standing.stage_id or 0, 0),
            standing.points,
            standing.tb or 0,
            standing.buchholz or 0,
            -standing.position,
        ),
        reverse=True,
    )


def calculate_overall_positions(
    standings: list[models.Standing],
    stages: list[models.Stage],
) -> list[models.Standing]:
    stage_order = {stage.id: stage.order for stage in stages}
    playoff_standings = [
        standing
        for standing in standings
        if standing.stage is not None and standing.stage.stage_type in ELIMINATION_STAGE_TYPES
    ]
    progressed_team_ids = {standing.team_id for standing in playoff_standings}

    if playoff_standings:
        for standing in playoff_standings:
            standing.overall_position = standing.position

        # Number of distinct teams that reached playoffs
        playoff_team_count = len(progressed_team_ids)

        remaining = _sort_for_overall(
            [standing for standing in standings if standing.team_id not in progressed_team_ids],
            stage_order,
        )
        # Best group-only team gets position playoff_team_count + 1
        next_position = playoff_team_count + 1
        for standing in remaining:
            standing.overall_position = next_position
            next_position += 1
        return standings

    remaining = _sort_for_overall(standings, stage_order)
    # Best team (first after sort) gets position 1
    for position, standing in enumerate(remaining, start=1):
        standing.overall_position = position
    return remaining


def sort_matches(
    matches: typing.Sequence[models.Encounter],
) -> typing.Sequence[models.Encounter]:
    """Phase E: delegate to shared utility."""
    return sort_bracket_matches(matches)


async def _update_stage_completion_flags(session: AsyncSession, tournament: models.Tournament) -> None:
    """After recalc, flip ``Stage.is_completed`` to match reality.

    A stage is considered completed when every encounter that belongs to it
    has ``status == COMPLETED``. Stages without any encounters are treated
    as not-completed (nothing to finish).

    This powers the admin UI's "Group A — 10/10 done" badge and the
    activate-and-generate warning for downstream playoff stages.
    """
    stages = getattr(tournament, "stages", []) or []
    if not stages:
        return

    stage_ids = [s.id for s in stages]
    counts_result = await session.execute(
        sa.select(
            models.Encounter.stage_id,
            models.Encounter.stage_item_id,
            sa.func.count(models.Encounter.id).label("total"),
            sa.func.sum(
                sa.case(
                    (
                        models.Encounter.status == enums.EncounterStatus.COMPLETED,
                        1,
                    ),
                    else_=0,
                )
            ).label("completed"),
            sa.func.coalesce(sa.func.max(models.Encounter.round), 0).label("max_round"),
        )
        .where(models.Encounter.stage_id.in_(stage_ids))
        .group_by(models.Encounter.stage_id, models.Encounter.stage_item_id)
    )
    rows_by_stage: dict[int, list[tuple[int | None, int, int, int]]] = defaultdict(list)
    for row in counts_result:
        rows_by_stage[row.stage_id].append(
            (
                getattr(row, "stage_item_id", None),
                int(row.total or 0),
                int(row.completed or 0),
                int(row.max_round or 0),
            )
        )

    for stage in stages:
        stage_rows = rows_by_stage.get(stage.id, [])
        if stage.stage_type == StageType.SWISS:
            rows_by_item = {
                stage_item_id: (total, completed, max_round)
                for stage_item_id, total, completed, max_round in stage_rows
            }
            item_scopes = [
                (item.id, *rows_by_item.get(item.id, (0, 0, 0))) for item in (getattr(stage, "items", []) or [])
            ]
            extra_scopes = [
                (None, total, completed, max_round)
                for stage_item_id, total, completed, max_round in stage_rows
                if stage_item_id is None
            ]
            scopes = item_scopes or extra_scopes
            should_be_completed = bool(scopes) and all(
                swiss_scope_stopped(stage, stage_item_id)
                or _swiss_scope_completed(total, completed, max_round, _stage_max_rounds(stage))
                for stage_item_id, total, completed, max_round in scopes
            )
            if stage.is_completed != should_be_completed:
                stage.is_completed = should_be_completed
            continue

        total = sum(row_total for _, row_total, _, _ in stage_rows)
        completed = sum(row_completed for _, _, row_completed, _ in stage_rows)
        should_be_completed = total > 0 and completed == total
        if stage.is_completed != should_be_completed:
            stage.is_completed = should_be_completed


async def calculate_for_tournament(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    commit: bool = True,
) -> typing.Sequence[models.Standing]:
    stages = sorted(getattr(tournament, "stages", []) or [], key=lambda stage: stage.order)
    all_standings: list[models.Standing] = []

    for stage in stages:
        stage_encounters = sort_matches(await encounter_service.get_by_stage_id(session, tournament.id, stage.id, []))
        if stage.stage_type in GROUP_STAGE_TYPES:
            stage_items = sorted(stage.items, key=lambda item: item.order) if stage.items else []
            if stage_items:
                for stage_item in stage_items:
                    item_encounters = [
                        encounter for encounter in stage_encounters if encounter.stage_item_id == stage_item.id
                    ]
                    all_standings.extend(_build_group_stage_standings(tournament, stage, stage_item, item_encounters))
            else:
                all_standings.extend(_build_group_stage_standings(tournament, stage, None, stage_encounters))
        elif stage.stage_type in ELIMINATION_STAGE_TYPES:
            all_standings.extend(_build_elimination_stage_standings(tournament, stage, stage_encounters))

    final_standings = calculate_overall_positions(all_standings, stages)
    session.add_all(final_standings)
    # Phase P0.4: auto-flip Stage.is_completed to reflect encounter progress
    # in the same transaction as the standings write.
    await _update_stage_completion_flags(session, tournament)
    if commit:
        await session.commit()
    else:
        await session.flush()
    logger.info(f"Stage-first standings calculated for tournament {tournament.id}")
    return await get_by_tournament(session, tournament, ["team", "stage", "stage_item"])
