"""``discipline`` narrows the public tournament list, its facets and the picker lookup to one installed game.

Three properties: a bogus code is a validation error (never an empty list and never another game's rows), the
filter reaches both the page and the count statement, and over a real database a game's tournaments are
counted/listed/looked up without the other game's.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.models.encounter import ScoringRule  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.models.tournament.flow import FlowNode  # noqa: E402
from shared.models.tournament.stage import Stage  # noqa: E402
from shared.rpc.query import build_query_model  # noqa: E402
from shared.testing import real_db_sessionmaker as _db_sessions  # noqa: E402
from src import schemas  # noqa: E402
from src.rpc import _helpers as rpc_helpers  # noqa: E402
from src.rpc import reads  # noqa: E402
from src.services.tournament import flows as tournament_flows  # noqa: E402
from src.services.tournament.service import tournament_service  # noqa: E402
from tests._rpc_fakes import CapturingBroker  # noqa: E402

MODELS = (schemas.TournamentPaginationSortSearchQueryParams, schemas.TournamentFacetsQueryParams)


@pytest.mark.parametrize("model", MODELS)
def test_installed_code_narrows_and_absent_means_every_game(model: type) -> None:
    assert build_query_model(model, {"discipline": ["lol"]}).discipline == "lol"
    assert build_query_model(model, {}).discipline is None


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("bogus", ["starcraft", "", "all", "LOL"])
def test_an_uninstalled_code_is_rejected_not_defaulted(model: type, bogus: str) -> None:
    with pytest.raises(ValidationError):
        build_query_model(model, {"discipline": [bogus]})


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[sa.Select] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self

    async def scalar(self, statement):
        self.statements.append(statement)
        return 0

    def unique(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one(self):
        return 0


def test_sql_puts_the_discipline_filter_in_the_page_and_the_count() -> None:
    from sqlalchemy.dialects import postgresql

    async def _run() -> list[str]:
        session = _RecordingSession()
        qp = schemas.TournamentPaginationSortSearchQueryParams(discipline="lol")
        await tournament_service.get_all(session, schemas.TournamentPaginationSortSearchParams.from_query_params(qp))
        return [str(statement.compile(dialect=postgresql.dialect())) for statement in session.statements]

    page_sql, count_sql = asyncio.run(_run())
    assert "tournament.discipline = " in page_sql
    assert "tournament.discipline = " in count_sql


async def _make_tournament(session, *, workspace_id: int, discipline: str) -> Tournament:
    now = datetime.now(UTC)
    suffix = uuid.uuid4().hex[:12]
    tournament = Tournament(
        workspace_id=workspace_id,
        name=f"disc-{suffix}",
        slug=f"disc-{suffix}",
        discipline=discipline,
        status=enums.TournamentStatus.LIVE,
        is_hidden=False,
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    session.add(tournament)
    await session.flush()
    # "Live" in the facets means a stage node is live (TOURNAMENT_IN_PLAY), not just the stored status.
    rule = ScoringRule(workspace_id=workspace_id, preset="wins", game_formula="win", end_formula="games >= best_of")
    session.add(rule)
    await session.flush()
    stage = Stage(
        tournament_id=tournament.id, scoring_rule_id=rule.id, name="S", stage_type=enums.StageType.ROUND_ROBIN
    )
    session.add(stage)
    await session.flush()
    session.add(
        FlowNode(
            tournament_id=tournament.id,
            kind=enums.FlowNodeKind.STAGE,
            name="S",
            status=enums.FlowNodeStatus.LIVE,
            stage_id=stage.id,
        )
    )
    await session.flush()
    return tournament


def test_list_and_facets_over_two_games_of_one_workspace() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                suffix = uuid.uuid4().hex[:12]
                workspace = Workspace(slug=f"disc-{suffix}", name=f"Disc {suffix}")
                session.add(workspace)
                await session.flush()
                for discipline in ("overwatch", "overwatch", "lol"):
                    await _make_tournament(session, workspace_id=workspace.id, discipline=discipline)
                await session.commit()
                workspace_id = workspace.id

            try:
                async with session_maker() as session:
                    flows = tournament_flows.flows_service

                    async def listing(**filters):
                        qp = schemas.TournamentPaginationSortSearchQueryParams(workspace_id=workspace_id, **filters)
                        params = schemas.TournamentPaginationSortSearchParams.from_query_params(qp)
                        page = await flows.get_all(session, params)
                        return page.total, {row.discipline for row in page.results}

                    return (
                        await listing(),
                        await listing(discipline="lol"),
                        await listing(discipline="overwatch"),
                        await flows.get_facets(session, workspace_id=workspace_id, discipline="lol"),
                        await flows.get_facets(session, workspace_id=workspace_id),
                    )
            finally:
                async with session_maker() as session:
                    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
                    await session.commit()

    every, lol, overwatch, lol_facets, all_facets = asyncio.run(_run())

    assert every == (3, {"overwatch", "lol"})
    assert lol == (1, {"lol"})
    assert overwatch == (2, {"overwatch"})
    assert (lol_facets.total, lol_facets.live) == (1, 1)
    assert (all_facets.total, all_facets.live) == (3, 3)


def test_lookup_rpc_lists_only_the_requested_games_tournaments() -> None:
    broker = CapturingBroker()
    reads.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
    lookup = broker.handlers["rpc.tournament.lookup_tournaments"]

    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                suffix = uuid.uuid4().hex[:12]
                workspace = Workspace(slug=f"look-{suffix}", name=f"Look {suffix}")
                session.add(workspace)
                await session.flush()
                ids: dict[str, set[int]] = {"overwatch": set(), "lol": set()}
                for discipline in ("overwatch", "overwatch", "lol"):
                    tournament = await _make_tournament(session, workspace_id=workspace.id, discipline=discipline)
                    ids[discipline].add(tournament.id)
                await session.commit()
                workspace_id = workspace.id

            async def ask(**query: str) -> dict:
                data = {"query": {"workspace_id": [str(workspace_id)], **{k: [v] for k, v in query.items()}}}
                return await lookup(data, None)

            try:
                with patch.object(rpc_helpers.db, "async_session_maker", session_maker):
                    return ids, await ask(), await ask(discipline="lol"), await ask(discipline="starcraft")
            finally:
                async with session_maker() as session:
                    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
                    await session.commit()

    ids, every, lol, bogus = asyncio.run(_run())

    assert {row["id"] for row in every["data"]} == ids["overwatch"] | ids["lol"]
    assert {row["id"] for row in lol["data"]} == ids["lol"]
    # An uninstalled code is the filter's 422, never an empty list or every game's tournaments.
    assert bogus["ok"] is False
    assert bogus["error"]["code"] == "unprocessable"
