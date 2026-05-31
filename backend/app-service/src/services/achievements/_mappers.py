"""ORM → narrow DTO conversion helpers for achievements/ flows."""

from __future__ import annotations

from src import models, schemas
from src.schemas.base import Score


def to_tournament_link(
    tournament: models.Tournament,
) -> schemas.AchievementTournamentLink:
    return schemas.AchievementTournamentLink(
        id=tournament.id,
        number=tournament.number,
        name=tournament.name,
        is_league=tournament.is_league,
    )


def _team_ref(team: models.Team | None) -> schemas.AchievementMatchTeamRef | None:
    if team is None:
        return None
    return schemas.AchievementMatchTeamRef(id=team.id, name=team.name)


def to_match_link(match: models.Match) -> schemas.AchievementMatchLink:
    return schemas.AchievementMatchLink(
        id=match.id,
        encounter_id=match.encounter_id,
        map_id=match.map_id,
        score=Score(home=match.home_score, away=match.away_score),
        log_name=match.log_name,
        time=match.time,
        home_team=_team_ref(getattr(match, "home_team", None)),
        away_team=_team_ref(getattr(match, "away_team", None)),
    )
