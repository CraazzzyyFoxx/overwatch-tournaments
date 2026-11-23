"""Maps a participation won and lost, as SQL.

Source: the confirmed games (``encounter.game_team``). A series with no game rows (an ``import``/``admin``/
``series_claim`` result) falls back to the seat ``score`` -- but only under the ``wins`` preset, where the
score IS the maps won; a points-preset score is never maps, so such an encounter contributes none.
"""

from __future__ import annotations

import typing

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums

__all__ = ("seat_maps",)


def seat_maps(seat: typing.Any) -> tuple[sa.ColumnElement[int], sa.ColumnElement[int]]:
    """``(maps_won, maps_lost)`` of the aliased ``EncounterTeam`` ``seat``; the query must select from its ``Encounter``."""
    confirmed = enums.EncounterGameState.CONFIRMED

    def games(condition: typing.Callable[[typing.Any], sa.ColumnElement[bool]]) -> sa.ColumnElement[int]:
        game_team = aliased(models.EncounterGameTeam)
        game = aliased(models.EncounterGame)
        return (
            sa.select(sa.func.count())
            .select_from(game_team)
            .join(game, game.id == game_team.game_id)
            .where(game_team.encounter_team_id == seat.id, game.state == confirmed, condition(game_team))
            .correlate(seat)
            .scalar_subquery()
        )

    # A place is stored only when the organizer entered one; otherwise a higher raw score places higher
    # (``shared.domain.encounter_scoring.resolve_placements``). shortcut: a game with neither (a formula-only
    # lobby) reads as a draw for all; derive its formula here if such games ever need map records.
    def won(game_team: typing.Any) -> sa.ColumnElement[bool]:
        rival = aliased(models.EncounterGameTeam)
        return sa.and_(
            sa.or_(game_team.placement == 1, game_team.placement.is_(None)),
            ~sa.exists(
                sa.select(1).where(
                    rival.game_id == game_team.game_id,
                    rival.encounter_team_id != game_team.encounter_team_id,
                    sa.or_(
                        sa.and_(game_team.placement.is_not(None), rival.placement == 1),
                        sa.and_(
                            game_team.placement.is_(None),
                            sa.func.coalesce(rival.score, 0) >= sa.func.coalesce(game_team.score, 0),
                        ),
                    ),
                )
            ),
        )

    def lost(game_team: typing.Any) -> sa.ColumnElement[bool]:
        rival = aliased(models.EncounterGameTeam)
        outscored = sa.exists(
            sa.select(1).where(
                rival.game_id == game_team.game_id,
                rival.encounter_team_id != game_team.encounter_team_id,
                sa.func.coalesce(rival.score, 0) > sa.func.coalesce(game_team.score, 0),
            )
        )
        return sa.or_(game_team.placement > 1, sa.and_(game_team.placement.is_(None), outscored))

    game = aliased(models.EncounterGame)
    has_games = sa.exists(sa.select(1).where(game.encounter_id == seat.encounter_id, game.state == confirmed))
    wins_series = sa.exists(
        sa.select(1).where(
            models.ScoringRule.id == models.Encounter.scoring_rule_id, models.ScoringRule.preset == "wins"
        )
    )
    others = aliased(models.EncounterTeam)
    series_lost = sa.cast(
        sa.select(sa.func.coalesce(sa.func.sum(others.score), 0))
        .where(others.encounter_id == seat.encounter_id, others.active.is_(True), others.id != seat.id)
        .correlate(seat)
        .scalar_subquery(),
        sa.Integer,
    )
    maps_won = sa.case((has_games, games(won)), (wins_series, sa.cast(seat.score, sa.Integer)), else_=0)
    maps_lost = sa.case((has_games, games(lost)), (wins_series, series_lost), else_=0)
    return maps_won, maps_lost
