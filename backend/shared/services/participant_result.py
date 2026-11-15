"""``tournament.participant_result``: one row per member of a finished tournament (spec §4.7).

Rule 1: when the tournament has a ``leaderboard`` sink (no outgoing edge; the highest id when several), its ``final``
rows: a player row is the member, a team row expands to the team's non-substitute members, all at the row's rank (a
tie group at its head place); ``field_size`` is the leaderboard's row count and ``source_node_id`` the leaderboard.
A by-role leaderboard ranks each role on its own: a member keeps their best place over their roles, with that role's
row count as ``field_size``. A player row's ``final_team_id`` is rule 2's team.

Rule 2: per member, the last-formed team the member played for (substitutes never count; the team of the formation
node completed last, a tournament-wide team after them, then the latest row), the placement being that team's positive
``Standing.overall_position`` in its last stage by ``Stage.order`` (NULL when it never had one), and ``field_size`` the
team count of that team's formation output: the node's teams plus the tournament-wide ones (plan Decision 8), or every
team of the tournament for a tournament-wide team. The formation is the TEAM's, never the player's column. The
migration ``flowP1_participant_result`` ran before any node existed, so its backfill SQL is a frozen, simpler copy. The
storage and the member's tournament-row helpers live in ``shared.repository.participant_result``.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core.enums import FlowNodeKind, FlowResultState
from shared.repository.participant_result import ParticipantResultRepository

__all__ = ("write_participant_results",)


def _team_rule_rows(tournament_id: int) -> sa.Select:
    """One select in ``ParticipantResultRepository`` column order (``COLUMNS``)."""
    player, standing, stage, team, peer = (
        models.Player,
        models.Standing,
        models.Stage,
        aliased(models.Team),
        aliased(models.Team),
    )
    placement = (
        sa.select(standing.overall_position)
        .outerjoin(stage, stage.id == standing.stage_id)
        .where(standing.team_id == player.team_id, standing.overall_position > 0)
        .order_by(stage.order.desc().nulls_last(), standing.stage_id.desc().nulls_last(), standing.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    field_size = (
        sa.select(sa.func.count(peer.id))
        .where(
            peer.tournament_id == tournament_id,
            sa.or_(
                team.formation_node_id.is_(None),
                peer.formation_node_id.is_(None),
                peer.formation_node_id == team.formation_node_id,
            ),
        )
        .scalar_subquery()
    )
    return (
        sa.select(
            player.tournament_id,
            player.workspace_member_id,
            player.team_id,
            placement,
            field_size,
            sa.cast(sa.null(), sa.BigInteger),
        )
        .join(models.Tournament, models.Tournament.id == player.tournament_id)
        .join(team, team.id == player.team_id)
        .outerjoin(models.FlowNode, models.FlowNode.id == team.formation_node_id)
        .where(
            player.tournament_id == tournament_id,
            models.Tournament.is_finished.is_(True),
            player.is_substitution.is_(False),
        )
        .ext(distinct_on(player.workspace_member_id))
        .order_by(player.workspace_member_id, models.FlowNode.completed_at.desc().nulls_last(), player.id.desc())
    )


def _leaderboard_sink(tournament_id: int) -> sa.ScalarSelect:
    node, edge = models.FlowNode, models.FlowEdge
    return (
        sa.select(node.id)
        .where(
            node.tournament_id == tournament_id,
            node.kind == FlowNodeKind.LEADERBOARD.value,
            ~sa.exists().where(edge.source_node_id == node.id),
        )
        .order_by(node.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _leaderboard_rows(tournament_id: int) -> sa.Select:
    """Rule 1 in ``COLUMNS`` order: the sink's final rows, player and team units alike."""
    sink, result, every, player = (
        _leaderboard_sink(tournament_id),
        models.FlowNodeResult,
        aliased(models.FlowNodeResult),
        models.Player,
    )
    rule2 = _team_rule_rows(tournament_id).subquery("rule2")
    # Rank and tie group count inside the row's role (all NULL outside a by-role ranking).
    place = sa.case(
        (result.tie_group.is_(None), result.rank),
        else_=sa.func.min(result.rank).over(partition_by=(result.role, result.tie_group)),
    )
    field_size = (
        sa.select(sa.func.count(every.id))
        .where(every.node_id == sink, every.role.is_not_distinct_from(result.role))
        .scalar_subquery()
    )
    final = (
        models.Tournament.id == tournament_id,
        models.Tournament.is_finished.is_(True),
        result.node_id == sink,
        result.state == FlowResultState.FINAL.value,
    )
    players = (
        sa.select(
            result.workspace_member_id.label("member"),
            rule2.c.team_id.label("team"),
            place.label("place"),
            field_size.label("field_size"),
        )
        .select_from(result)
        .join(models.Tournament, sa.true())
        .outerjoin(rule2, rule2.c.workspace_member_id == result.workspace_member_id)
        .where(*final, result.workspace_member_id.is_not(None))
    )
    teams = (
        sa.select(player.workspace_member_id, result.team_id, place, field_size)
        .select_from(result)
        .join(models.Tournament, sa.true())
        .join(player, sa.and_(player.team_id == result.team_id, player.is_substitution.is_(False)))
        .where(*final)
    )
    rows = sa.union_all(players, teams).subquery("rows")
    return (
        sa.select(
            sa.literal(tournament_id, models.ParticipantResult.tournament_id.type),
            rows.c.member,
            rows.c.team,
            rows.c.place,
            rows.c.field_size,
            sink,
        )
        .ext(distinct_on(rows.c.member))
        # A member's best place; between equal places, the larger field.
        .order_by(rows.c.member, rows.c.place, rows.c.field_size.desc())
    )


async def write_participant_results(session: AsyncSession, tournament_id: int) -> int:
    """Replace the tournament's rows with the rule-1 rows when it has a leaderboard sink, else the rule-2 rows; none
    unless the tournament is finished. Never commits."""
    await session.flush()
    has_sink = await session.scalar(sa.select(_leaderboard_sink(tournament_id))) is not None
    rows = _leaderboard_rows(tournament_id) if has_sink else _team_rule_rows(tournament_id)
    return await ParticipantResultRepository().replace(session, tournament_id, rows)
