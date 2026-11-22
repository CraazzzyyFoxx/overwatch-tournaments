"""A team's seat in an encounter, as SQL.

An encounter seats ``slot_count`` participations (``encounter.team``) and has no
sides. "The team played the encounter" is an ACTIVE participation carrying that
``team_id``; whether it won comes from ``placement`` (a shared first place is a
draw, not a win) and the series score it earned from ``score`` -- under the
``wins`` preset the number of maps it won.
"""

from __future__ import annotations

import typing

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums

__all__ = ("Seat", "teamless_seat_ids", "user_live_seat_ids")


def teamless_seat_ids(user_id: typing.Any) -> sa.Select[int]:
    """Ids of the tournament seats with no source team (an individual Swiss lobby) whose roster names ``user_id`` as a
    non-substitute, live or retired: every match such a seat played is one the user played."""
    member, seat = models.EncounterTeamMember, models.EncounterTeam
    return (
        sa.select(member.encounter_team_id)
        .join(seat, seat.id == member.encounter_team_id)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == member.workspace_member_id)
        .where(
            models.WorkspaceMember.player_id == user_id,
            member.is_substitute.is_(False),
            seat.team_id.is_(None),
            seat.tournament_id.is_not(None),
        )
    )


def user_live_seat_ids(user_id: typing.Any, *more: sa.Select[typing.Any]) -> sa.CompoundSelect[int]:
    """Ids of the live seats ``user_id`` played as a non-substitute: their teams' and the team-less ones, with the
    seat ids ``more`` selects."""
    seat = aliased(models.EncounterTeam, name="user_team_seat")
    teams = (
        sa.select(seat.id)
        .join(models.Player, models.Player.team_id == seat.team_id)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(
            seat.active.is_(True),
            models.WorkspaceMember.player_id == user_id,
            models.Player.is_substitution.is_(False),
        )
    )
    loose = Seat("user_teamless_seat")
    return sa.union(teams, loose.teamless_sides(loose.team.id, user_id=user_id, duel=False), *more)


class Seat:
    """One team's live participation, joined to its encounter.

    ``maps_won`` / ``maps_lost`` count maps from the confirmed games (``game_team``), so :meth:`join`
    keeps only two-seat encounters unless asked otherwise.
    """

    def __init__(self, name: str = "seat") -> None:
        self._name = name
        self.team = aliased(models.EncounterTeam, name=name)
        self._others = aliased(models.EncounterTeam, name=f"{name}_others")

    def _join_encounter(self, query: sa.Select, *, duel: bool) -> sa.Select:
        encounter_on = models.Encounter.id == self.team.encounter_id
        if duel:
            encounter_on = sa.and_(encounter_on, models.Encounter.slot_count == 2)
        return query.join(models.Encounter, encounter_on)

    def join(self, query: sa.Select, team_id_column: typing.Any, *, duel: bool = True) -> sa.Select:
        """Join the seat of ``team_id_column`` and then its encounter onto ``query``."""
        query = query.join(self.team, sa.and_(self.team.team_id == team_id_column, self.team.active.is_(True)))
        return self._join_encounter(query, duel=duel)

    def join_id(self, query: sa.Select, seat_id_column: typing.Any, *, duel: bool = True) -> sa.Select:
        """Join the live seat ``seat_id_column`` names and then its encounter onto ``query``."""
        query = query.join(self.team, sa.and_(self.team.id == seat_id_column, self.team.active.is_(True)))
        return self._join_encounter(query, duel=duel)

    def teamless_sides(self, *columns: typing.Any, user_id: typing.Any = None, duel: bool = True) -> sa.Select:
        """``columns`` per non-substitute roster member of a live tournament seat with no source team, joined to its
        encounter.

        Such a seat (an individual Swiss lobby, a deleted team's seat) has no ``tournament.player`` behind it: its
        roster snapshot (``encounter.team_member``) is the only record of who played. Mix seats never count (their
        stats live inside the mix). ``user_id`` keeps that user's rows.
        """
        member = models.EncounterTeamMember
        query = (
            sa.select(*columns)
            .select_from(member)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == member.workspace_member_id)
            .join(
                self.team,
                sa.and_(
                    self.team.id == member.encounter_team_id,
                    self.team.active.is_(True),
                    self.team.team_id.is_(None),
                    self.team.tournament_id.is_not(None),
                ),
            )
            .where(member.is_substitute.is_(False))
        )
        if user_id is not None:
            query = query.where(models.WorkspaceMember.player_id == user_id)
        return self._join_encounter(query, duel=duel)

    def _games(self, *conditions: typing.Callable[[typing.Any], sa.ColumnElement[bool]]) -> sa.ColumnElement[int]:
        """How many confirmed games of this encounter this participation played and ``conditions`` hold for."""
        game_team = aliased(models.EncounterGameTeam)
        game = aliased(models.EncounterGame)
        return (
            sa.select(sa.func.count())
            .select_from(game_team)
            .join(game, game.id == game_team.game_id)
            .where(
                game_team.encounter_team_id == self.team.id,
                game.state == enums.EncounterGameState.CONFIRMED,
                *[condition(game_team) for condition in conditions],
            )
            .correlate(self.team)
            .scalar_subquery()
        )

    @property
    def _has_games(self) -> sa.ColumnElement[bool]:
        game = aliased(models.EncounterGame)
        return sa.exists(
            sa.select(1).where(
                game.encounter_id == self.team.encounter_id, game.state == enums.EncounterGameState.CONFIRMED
            )
        )

    @property
    def _series_only_wins(self) -> sa.ColumnElement[bool]:
        """The result is a ``wins``-preset series score: there, and only there, ``score`` counts maps."""
        return sa.exists(
            sa.select(1).where(
                models.ScoringRule.id == models.Encounter.scoring_rule_id, models.ScoringRule.preset == "wins"
            )
        )

    @property
    def maps_won(self) -> sa.ColumnElement[int]:
        """Maps this participation won: its first places in the confirmed games (``game_team``).

        A series with no game rows (an ``import``/``admin``/``series_claim`` result) falls back to its seat
        ``score`` -- but only under the ``wins`` preset, where the score IS the maps won. A points-preset
        score is never maps, so such an encounter contributes none.
        """

        def won(game_team: typing.Any) -> sa.ColumnElement[bool]:
            rival = aliased(models.EncounterGameTeam)
            return sa.and_(
                game_team.placement == 1,
                ~sa.exists(
                    sa.select(1).where(
                        rival.game_id == game_team.game_id,
                        rival.encounter_team_id != game_team.encounter_team_id,
                        rival.placement == 1,
                    )
                ),
            )

        return sa.case(
            (self._has_games, self._games(won)),
            (self._series_only_wins, sa.cast(self.team.score, sa.Integer)),
            else_=0,
        )

    @property
    def maps_lost(self) -> sa.ColumnElement[int]:
        """Maps this participation lost: its games placed below first, else (see :attr:`maps_won`) the
        other live seats' score under the ``wins`` preset."""
        others = self._others
        # Bare ``active``, not ``IS TRUE``: only the bare column proves the ``WHERE active`` partial index
        # (``uq_team_active_slot``) for this per-row probe; ``IS TRUE`` scans ``uq_team_id_encounter`` whole.
        series_score = sa.cast(
            sa.select(sa.func.coalesce(sa.func.sum(others.score), 0))
            .where(others.encounter_id == self.team.encounter_id, others.active, others.id != self.team.id)
            .correlate(self.team)
            .scalar_subquery(),
            sa.Integer,
        )
        return sa.case(
            (self._has_games, self._games(lambda game_team: game_team.placement > 1)),
            (self._series_only_wins, series_score),
            else_=0,
        )

    @property
    def shared_first(self) -> sa.ColumnElement[bool]:
        """Another live seat holds first place too."""
        others = aliased(models.EncounterTeam, name=f"{self._name}_first")
        return sa.exists(
            sa.select(1)
            .where(
                others.encounter_id == self.team.encounter_id,
                others.active,
                others.id != self.team.id,
                others.placement == 1,
            )
            .correlate(self.team)
        )

    @property
    def won(self) -> sa.ColumnElement[bool]:
        return sa.and_(self.team.placement == 1, ~self.shared_first)

    @property
    def drew(self) -> sa.ColumnElement[bool]:
        return sa.and_(self.team.placement == 1, self.shared_first)

    @property
    def lost(self) -> sa.ColumnElement[bool]:
        return self.team.placement > 1

    def count(self, outcome: sa.ColumnElement[bool]) -> sa.ColumnElement[int]:
        """``1`` when ``outcome`` holds, else ``0`` -- for ``SUM`` over encounters."""
        return sa.case((outcome, 1), else_=0)
