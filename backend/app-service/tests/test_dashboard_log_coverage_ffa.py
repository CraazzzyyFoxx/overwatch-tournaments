"""An FFA lobby is not a series that is missing its logs (real-DB integration).

A lobby never produces a match log — its results live in ``encounter_game_result``,
not in ``matches.match`` — so counting it as "missing logs" would permanently drag
the dashboard's log coverage down for a tournament that is actually complete::

    uv run pytest app-service/tests/test_dashboard_log_coverage_ffa.py -v

Uses the shared ``db_session`` fixture (``shared.testing``, wired in conftest);
seeds its own workspace and drops it again. Skips only when Postgres is
unreachable.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import sqlalchemy as sa

from shared.core import enums
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import Team, Tournament
from src.services.dashboard.service import dashboard


async def _seed(session: Any) -> tuple[int, int]:
    """A live tournament with one log-less duel and one lobby."""

    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"ffadash-{suffix}", name=f"FFA dashboard {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"FFA dashboard {suffix}",
        slug=f"ffadash-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
        is_finished=False,
    )
    session.add(tournament)
    await session.flush()
    teams = [
        Team(tournament_id=tournament.id, name=f"Team {index} {suffix}", balancer_name=f"team-{index}-{suffix}")
        for index in range(2)
    ]
    session.add_all(teams)
    await session.flush()

    await session.execute(
        sa.text(
            "insert into tournament.encounter (name, home_team_id, away_team_id, home_score, away_score, "
            "round, best_of, tournament_id, status, result_status) "
            "values ('A vs B', :h, :a, 0, 0, 1, 3, :t, 'OPEN', 'none')"
        ),
        {"h": teams[0].id, "a": teams[1].id, "t": tournament.id},
    )
    await session.execute(
        sa.text(
            "insert into tournament.encounter (name, format, home_score, away_score, round, best_of, "
            "tournament_id, status, result_status) values ('Lobby', 'ffa', 0, 0, 1, 3, :t, 'OPEN', 'none')"
        ),
        {"t": tournament.id},
    )
    await session.commit()
    return workspace.id, tournament.id


async def _drop(session: Any, workspace_id: int) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_a_lobby_is_not_an_encounter_missing_logs(db_session) -> None:
    async def _run() -> tuple[dict | None, int]:
        workspace_id, tournament_id = await _seed(db_session)
        try:
            stats = await dashboard.get_active_tournament_stats(db_session, workspace_id)
            issues = await dashboard.get_issues(db_session, workspace_id)
            assert stats is not None and stats["tournament_id"] == tournament_id
            return stats, issues["encounters_missing_logs"]
        finally:
            await _drop(db_session, workspace_id)

    stats, missing_logs_issue = asyncio.run(_run())
    assert stats["encounters_total"] == 1
    assert stats["encounters_missing_logs"] == 1
    assert missing_logs_issue == 1
