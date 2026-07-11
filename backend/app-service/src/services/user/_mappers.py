"""ORM → narrow DTO conversion helpers for user/ flows.

These replace the wide `to_pydantic_*` family that lived in `_internal/` —
each function produces a DTO defined in `src.schemas.user` that contains
only the fields the frontend actually renders on user-scoped pages.
"""

from __future__ import annotations

from shared.core.impact import BADGE_THRESHOLD
from shared.division_grid import DivisionGrid
from shared.services.division_grid_resolution import resolve_tournament_division
from src import models, schemas
from src.schemas.base import Score
from src.schemas.division_grid import DivisionGridVersionRead


def resolve_team_placement(team: models.Team) -> int | None:
    """Pick the best (lowest, positive) overall_position across standings.

    Replaces `_internal.team.flows.resolve_team_placement` — same logic.
    """
    standings = getattr(team, "standings", None) or []
    positive_positions = [
        standing.overall_position for standing in standings if getattr(standing, "overall_position", 0) > 0
    ]
    if positive_positions:
        return min(positive_positions)
    return None


def _division_grid_version(tournament: models.Tournament) -> DivisionGridVersionRead | None:
    if getattr(tournament, "division_grid_version", None) is None:
        return None
    return DivisionGridVersionRead.model_validate(tournament.division_grid_version, from_attributes=True)


def to_user_tournament_summary(
    tournament: models.Tournament,
) -> schemas.UserTournamentSummary:
    """Narrow tournament card for UserProfile.tournaments + filter lists."""
    return schemas.UserTournamentSummary(
        id=tournament.id,
        number=tournament.number,
        name=tournament.name,
        is_league=tournament.is_league,
        is_finished=tournament.is_finished,
        status=tournament.status,
        division_grid_version=_division_grid_version(tournament),
    )


def to_user_tournament_player(
    player: models.Player,
    *,
    grid: DivisionGrid,
    avg_mvp: float | None = None,
    heroes: list[dict] | None = None,
) -> schemas.UserTournamentPlayer:
    """Player card inside UserTournament.players.

    ``avg_mvp`` and ``heroes`` are supplied by the caller from bulk lookups
    keyed by (tournament_id, user_id) — see ``_repositories`` — so this stays a
    pure ORM→DTO conversion with no per-player queries.
    """
    return schemas.UserTournamentPlayer(
        id=player.id,
        name=player.name,
        role=player.role,
        sub_role=player.sub_role,
        rank=player.rank,
        division=resolve_tournament_division(player.rank, tournament_grid=grid),
        # workspace_member_id is NOT NULL (contract step, iwrefac07): the
        # identity anchor is always workspace_member.player_id.
        user_id=player.workspace_member.player_id,
        is_substitution=player.is_substitution,
        is_newcomer=player.is_newcomer,
        is_newcomer_role=player.is_newcomer_role,
        related_player_id=player.related_player_id,
        relative_player=getattr(player, "relative_player", None),
        avg_mvp=avg_mvp,
        heroes=[schemas.HeroRead.model_validate(h) for h in (heroes or [])],
    )


def to_match_with_user_stats(
    match: models.Match,
    *,
    performance: int | None,
    heroes: list[dict] | None,
    impact_rank: int | float | None = None,
    impact_points: float | None = None,
    overperformance_score: float | None = None,
    overperf_pos: int | None = None,
) -> schemas.MatchReadWithUserStats:
    """One match in a user-scoped encounter — includes the viewer's stats.

    ``overperf_pos`` is the viewer's rank (1 = best) among all match
    participants by OverperformanceScore (match-wide window, not scoped to the
    viewer) — used only to compute ``overperformance_badge`` and not exposed
    on the schema itself.
    """
    map_read = schemas.MapRead.model_validate(match.map, from_attributes=True) if match.map is not None else None
    hero_objs = [schemas.HeroRead.model_validate(h) for h in (heroes or [])]
    return schemas.MatchReadWithUserStats(
        id=match.id,
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        score=Score(home=match.home_score, away=match.away_score),
        time=match.time,
        log_name=match.log_name,
        encounter_id=match.encounter_id,
        map_id=match.map_id,
        code=getattr(match, "code", None),
        map=map_read,
        performance=performance,
        impact_rank=int(impact_rank) if impact_rank is not None else None,
        impact_points=impact_points,
        overperformance_score=overperformance_score,
        overperformance_badge=(
            overperf_pos == 1 and overperformance_score is not None and overperformance_score >= BADGE_THRESHOLD
        ),
        heroes=hero_objs,
    )


def to_encounter_tournament_summary(
    tournament: models.Tournament | None,
) -> schemas.UserEncounterTournament | None:
    if tournament is None:
        return None
    return schemas.UserEncounterTournament(
        id=tournament.id,
        name=tournament.name,
        number=tournament.number,
        is_league=tournament.is_league,
        is_finished=tournament.is_finished,
        status=tournament.status,
    )


def to_encounter_stage_summary(
    stage: models.Stage | None,
) -> schemas.UserEncounterStageSummary | None:
    if stage is None:
        return None
    return schemas.UserEncounterStageSummary(id=stage.id, name=stage.name)


def to_encounter_stage_item_summary(
    stage_item: models.StageItem | None,
) -> schemas.UserEncounterStageItemSummary | None:
    if stage_item is None:
        return None
    return schemas.UserEncounterStageItemSummary(id=stage_item.id, name=stage_item.name)


def _to_encounter_team_player_ref(
    player: models.Player,
) -> schemas.UserEncounterTeamPlayerRef:
    # workspace_member_id is NOT NULL (contract step, iwrefac07): the identity
    # anchor is always workspace_member.player_id.
    return schemas.UserEncounterTeamPlayerRef(
        id=player.id,
        user_id=player.workspace_member.player_id,
        role=player.role,
        name=player.name,
    )


def to_encounter_team_summary(
    team: models.Team | None,
) -> schemas.UserEncounterTeamSummary | None:
    if team is None:
        return None
    return schemas.UserEncounterTeamSummary(
        id=team.id,
        name=team.name,
        players=[_to_encounter_team_player_ref(p) for p in getattr(team, "players", []) or []],
    )


def _resolve_user_team_id(encounter: models.Encounter, user_id: int) -> int | None:
    """Pick which side (home/away) the viewer played on, based on rosters."""
    home = getattr(encounter, "home_team", None)
    if home is not None:
        for player in getattr(home, "players", []) or []:
            member = player.workspace_member
            if member is not None and member.player_id == user_id:
                return home.id
    away = getattr(encounter, "away_team", None)
    if away is not None:
        for player in getattr(away, "players", []) or []:
            member = player.workspace_member
            if member is not None and member.player_id == user_id:
                return away.id
    return None


def to_encounter_with_user_stats(
    encounter: models.Encounter,
    matches: list[schemas.MatchReadWithUserStats],
    *,
    viewer_user_id: int | None = None,
) -> schemas.EncounterReadWithUserStats:
    """User-scoped encounter view.

    Populates tournament/team/stage summaries always — the repository loads
    them via joinedload/selectinload. `viewer_user_id` is used to fill the
    convenience `user_team_id` shortcut so the frontend doesn't have to scan
    rosters itself.
    """
    home_team_summary = to_encounter_team_summary(encounter.home_team)
    away_team_summary = to_encounter_team_summary(encounter.away_team)
    user_team_id = _resolve_user_team_id(encounter, viewer_user_id) if viewer_user_id is not None else None
    return schemas.EncounterReadWithUserStats(
        id=encounter.id,
        name=encounter.name,
        home_team_id=encounter.home_team_id,
        away_team_id=encounter.away_team_id,
        score=Score(home=encounter.home_score, away=encounter.away_score),
        round=encounter.round,
        best_of=encounter.best_of,
        tournament_id=encounter.tournament_id,
        status=encounter.status,
        closeness=encounter.closeness,
        has_logs=encounter.has_logs,
        result_status=getattr(encounter, "result_status", "none"),
        user_team_id=user_team_id,
        tournament=to_encounter_tournament_summary(getattr(encounter, "tournament", None)),
        stage=to_encounter_stage_summary(getattr(encounter, "stage", None)),
        stage_item=to_encounter_stage_item_summary(getattr(encounter, "stage_item", None)),
        home_team=home_team_summary,
        away_team=away_team_summary,
        matches=matches,
    )
