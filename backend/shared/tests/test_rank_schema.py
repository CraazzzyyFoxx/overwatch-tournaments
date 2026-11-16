"""One rank schema for every game: tables, the ``discipline`` every row carries, and the claims that read only their own game."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from shared.models.ranks.rank import (
    RANK_SCHEMA,
    CareerSnapshot,
    CharacterRate,
    GameAccountProfile,
    RankAccountState,
    RankFetchLog,
    UserRankSnapshot,
)
from shared.repository.ranks import RankAccountStateRepository, workspace_account_ids

TABLES = (
    UserRankSnapshot.__table__,
    RankAccountState.__table__,
    RankFetchLog.__table__,
    GameAccountProfile.__table__,
    CareerSnapshot.__table__,
    CharacterRate.__table__,
)


def _compiled(statement):
    return statement.compile(dialect=postgresql.dialect())


def test_the_rank_tables_live_in_one_rank_schema() -> None:
    assert RANK_SCHEMA == "rank"
    assert {table.fullname for table in TABLES} == {
        "rank.rank_snapshot",
        "rank.account_state",
        "rank.fetch_log",
        "rank.account_profile",
        "rank.career_snapshot",
        "rank.character_rate",
    }


def test_every_rank_row_names_its_game_and_no_default_hides_a_missing_one() -> None:
    for table in TABLES:
        column = table.c.discipline
        assert (column.nullable, column.server_default, column.default) == (False, None, None), table.name
        assert column.type.length == 32


def test_a_lol_row_fits_the_snapshot_and_the_state() -> None:
    snapshot, state = UserRankSnapshot.__table__.c, RankAccountState.__table__.c
    assert all(snapshot[name].nullable for name in ("platform", "role", "queue", "lp", "wins", "losses"))
    assert "battle_tag" not in snapshot and snapshot.handle.nullable is False
    assert state.external_id.nullable and state.region.nullable and state.social_account_id.unique
    assert "player_id_slug" not in state and "battle_tag" not in RankFetchLog.__table__.c


def test_the_series_and_claim_indexes_carry_the_queue_and_the_game() -> None:
    snapshot = {index.name: index for index in UserRankSnapshot.__table__.indexes}
    assert [c.name for c in snapshot["ix_rank_snapshot_series_captured"].columns] == [
        "social_account_id",
        "role",
        "platform",
        "queue",
        "captured_at",
    ]
    assert "queue" in str(snapshot["ix_rank_snapshot_latest_ranked"].expressions)
    state = {index.name: [c.name for c in index.columns] for index in RankAccountState.__table__.indexes}
    assert state["ix_account_state_due"][0] == "discipline"


class _Session:
    def __init__(self) -> None:
        self.statements: list = []

    async def scalars(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: [])


def test_a_claim_only_ever_picks_its_own_games_accounts() -> None:
    session = _Session()
    asyncio.run(
        RankAccountStateRepository().claim_due(
            session, discipline="lol", limit=5, scope="all", interval_seconds=60, now=datetime.now(UTC)
        )
    )
    compiled = _compiled(session.statements[0])
    assert "rank.account_state.discipline = %(discipline_1)s" in str(compiled)
    assert compiled.params["discipline_1"] == "lol"


def test_the_workspace_hop_follows_the_given_provider() -> None:
    compiled = _compiled(workspace_account_ids(7, provider="riot"))
    assert compiled.params["provider_1"] == "riot" and compiled.params["workspace_id_1"] == 7
