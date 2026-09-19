"""encounter_result / encounter_comeback — series-grain conditions.

Both nodes emit ``(user_id, tournament_id, encounter_id)``: the fact they
measure belongs to the series itself, not to any single map of it.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import AchievementGrain
from src import models

from ..context import EvalContext
from . import ResultSet, register
from .encounter import join_final_encounters

#: Which side of a *decided* encounter the outcome refers to. Unknown outcome → ``KeyError``.
_OUTCOME_TEAM = {
    "win": lambda: sa.case(
        (models.Encounter.home_score > models.Encounter.away_score, models.Encounter.home_team_id),
        else_=models.Encounter.away_team_id,
    ),
    "loss": lambda: sa.case(
        (models.Encounter.home_score < models.Encounter.away_score, models.Encounter.home_team_id),
        else_=models.Encounter.away_team_id,
    ),
}


def _series_roster_query() -> sa.Select:
    """Encounter joined to stage context — no roster join, no columns yet."""
    return (
        sa.select(models.Encounter.id)
        .select_from(models.Encounter)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .outerjoin(models.Stage, models.Stage.id == models.Encounter.stage_id)
        .outerjoin(models.StageItem, models.StageItem.id == models.Encounter.stage_item_id)
    )


@register(
    "encounter_result",
    grain=AchievementGrain.user_encounter,
    description="A completed series ended in this outcome and scoreline shape",
    required=("outcome",),
    optional=("margin", "opponent_score", "round_type"),
    depends_on=("tournament.encounter", "tournament.player"),
)
async def execute_encounter_result(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Roster of the winning or losing side of a decided series. Grain: user_encounter.

    params:
        outcome: "win" | "loss" — which side's roster qualifies.
        margin: abs(home_score - away_score) must equal this.
        opponent_score: the LOSING side's map count must equal this (0 = a sweep).
        round_type: "any" (default) | "final".
    """
    target_team_id = _OUTCOME_TEAM[params["outcome"]]()
    margin_expr = sa.func.abs(models.Encounter.home_score - models.Encounter.away_score)

    where = [
        models.Tournament.workspace_id == context.workspace_id,
        models.Encounter.status == "COMPLETED",
        # A draw has no winner and no loser, so it qualifies neither side.
        models.Encounter.home_score != models.Encounter.away_score,
        models.Player.is_substitution.is_(False),
    ]
    if context.tournament:
        where.append(models.Encounter.tournament_id == context.tournament.id)
    if (margin := params.get("margin")) is not None:
        where.append(margin_expr == margin)
    if (opponent_score := params.get("opponent_score")) is not None:
        loser_score = sa.case(
            (models.Encounter.home_score < models.Encounter.away_score, models.Encounter.home_score),
            else_=models.Encounter.away_score,
        )
        where.append(loser_score == opponent_score)

    query = _series_roster_query().with_only_columns(
        models.WorkspaceMember.player_id.label("user_id"),
        models.Encounter.tournament_id.label("tournament_id"),
        models.Encounter.id.label("encounter_id"),
        models.Encounter.home_score.label("home_score"),
        models.Encounter.away_score.label("away_score"),
    )

    if params.get("round_type", "any") == "final":
        query = join_final_encounters(query, context.workspace_id)

    query = (
        query.join(
            models.Player,
            sa.and_(
                models.Player.team_id == target_team_id,
                models.Player.tournament_id == models.Encounter.tournament_id,
            ),
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(*where)
    )

    result = await session.execute(query)
    keys: ResultSet = set()
    for row in result:
        key = (row.user_id, row.tournament_id, row.encounter_id)
        keys.add(key)
        context.record_evidence(
            key,
            home_score=int(row.home_score),
            away_score=int(row.away_score),
            margin=abs(int(row.home_score) - int(row.away_score)),
            outcome=params["outcome"],
        )
    return keys


@register(
    "encounter_comeback",
    grain=AchievementGrain.user_encounter,
    description="Won a series after trailing by this many maps",
    optional=("min_deficit",),
    depends_on=("tournament.encounter", "tournament.player", "matches.match"),
)
async def execute_encounter_comeback(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Series winner that was once behind by ``min_deficit`` maps. Grain: user_encounter.

    params:
        min_deficit: maps the eventual winner had to be down by (default 2).

    The walk happens in Python: one query pulls every candidate series' maps,
    because the running score is sequential and SQL window functions buy
    nothing over a few thousand rows.
    """
    min_deficit = params.get("min_deficit", 2)

    maps_query = (
        sa.select(
            models.Encounter.id.label("encounter_id"),
            models.Encounter.tournament_id.label("tournament_id"),
            models.Encounter.home_team_id.label("enc_home_team_id"),
            models.Encounter.away_team_id.label("enc_away_team_id"),
            models.Encounter.home_score.label("enc_home_score"),
            models.Encounter.away_score.label("enc_away_score"),
            models.Match.id.label("match_id"),
            models.Match.map_index.label("map_index"),
            models.Match.home_team_id.label("map_home_team_id"),
            models.Match.away_team_id.label("map_away_team_id"),
            models.Match.home_score.label("map_home_score"),
            models.Match.away_score.label("map_away_score"),
        )
        .select_from(models.Match)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Encounter.status == "COMPLETED",
            models.Encounter.home_score != models.Encounter.away_score,
        )
    )
    if context.tournament:
        maps_query = maps_query.where(models.Encounter.tournament_id == context.tournament.id)

    series: dict[int, list] = {}
    for row in await session.execute(maps_query):
        series.setdefault(row.encounter_id, []).append(row)

    # encounter_id -> (tournament_id, winning_team_id, max_deficit, home_score, away_score)
    qualifying: dict[int, tuple[int, int, int, int, int]] = {}
    for encounter_id, rows in series.items():
        first = rows[0]
        winner_team_id = (
            first.enc_home_team_id if first.enc_home_score > first.enc_away_score else first.enc_away_team_id
        )
        loser_team_id = (
            first.enc_away_team_id if first.enc_home_score > first.enc_away_score else first.enc_home_team_id
        )

        won = lost = 0
        max_deficit = 0
        # NULL ``map_index`` sorts last: an unpositioned map is of unknown order,
        # so it cannot be assumed to have come first.
        for row in sorted(rows, key=lambda r: (r.map_index is None, r.map_index or 0, r.match_id)):
            if row.map_home_score > row.map_away_score:
                map_winner = row.map_home_team_id
            elif row.map_away_score > row.map_home_score:
                map_winner = row.map_away_team_id
            else:  # a drawn map moves neither side
                continue
            # Map orientation is independent of the encounter's, so resolve the
            # map's winner onto the encounter's two teams rather than its sides.
            if map_winner == winner_team_id:
                won += 1
            elif map_winner == loser_team_id:
                lost += 1
            else:  # a map of some other pairing, defensively ignored
                continue
            max_deficit = max(max_deficit, lost - won)

        if max_deficit >= min_deficit:
            qualifying[encounter_id] = (
                first.tournament_id,
                winner_team_id,
                max_deficit,
                first.enc_home_score,
                first.enc_away_score,
            )

    if not qualifying:
        return set()

    winning_team_ids = {entry[1] for entry in qualifying.values()}
    roster_query = (
        sa.select(
            models.Player.team_id.label("team_id"),
            models.WorkspaceMember.player_id.label("user_id"),
        )
        .select_from(models.Player)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.team_id.in_(winning_team_ids),
            models.Player.is_substitution.is_(False),
        )
    )
    roster: dict[int, list[int]] = {}
    for row in await session.execute(roster_query):
        roster.setdefault(row.team_id, []).append(row.user_id)

    keys: ResultSet = set()
    for encounter_id, (tournament_id, team_id, max_deficit, home_score, away_score) in qualifying.items():
        for user_id in roster.get(team_id, ()):
            key = (user_id, tournament_id, encounter_id)
            keys.add(key)
            context.record_evidence(
                key,
                max_deficit=int(max_deficit),
                home_score=int(home_score),
                away_score=int(away_score),
            )
    return keys
