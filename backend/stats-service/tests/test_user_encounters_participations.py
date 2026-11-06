"""The user encounter reads over participations, executed against a real Postgres.

"The team played the encounter" is an active participation carrying its ``team_id``;
a win, loss or draw is read off ``placement`` (a shared first place is a draw) and
the maps off the seats' ``score``. A lobby counts for the record but not for the
maps. One disposable workspace, dropped again at the end::

    uv run pytest stats-service/tests/test_user_encounters_participations.py -v
"""

from __future__ import annotations

import asyncio
import re
import uuid
from inspect import unwrap
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from shared.core import enums, pagination
from shared.disciplines import DISCIPLINES
from shared.models.catalog.role import CatalogRole, RoleDimension
from shared.models.encounter import Encounter, EncounterTeamMember, EncounterTeamMemberRole
from shared.models.identity.user import User
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.models.tournament import Player, Stage, Team, Tournament
from shared.models.tournament.bracket_encounter import BracketEncounter
from shared.models.tournament.player_role import assignment_of
from shared.repository import CatalogRoleRepository
from shared.schemas.role import RoleRef
from shared.services.ontology import rated_leaf
from src.services.user import _mappers
from src.services.user.queries.encounters import UserEncounterQueries
from src.services.user.queries.overview import UserOverviewQueries
from src.services.user.service import UserService
from tests.encounter_seed import seed_confirmed_games, seed_encounter, seed_scoring_rule

encounter_queries = UserEncounterQueries.of("overwatch")
overview_queries = UserOverviewQueries.of("overwatch")


class _Seed:
    def __init__(self) -> None:
        self.workspace_id = 0
        self.users: dict[str, int] = {}
        self.teams: dict[str, int] = {}
        self.encounters: dict[str, int] = {}
        self.stage_name = ""


async def _seed(session: Any) -> _Seed:
    suffix = uuid.uuid4().hex[:10]
    seed = _Seed()
    workspace = Workspace(slug=f"seats-{suffix}", name=f"Seats {suffix}")
    session.add(workspace)
    await session.flush()
    seed.workspace_id = workspace.id

    members: dict[str, int] = {}
    for key in ("alice", "bob", "carol"):
        user = User(name=f"zz{suffix}-{key}")
        session.add(user)
        await session.flush()
        seed.users[key] = user.id
        member = WorkspaceMember(workspace_id=workspace.id, player_id=user.id)
        session.add(member)
        await session.flush()
        members[key] = member.id

    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Seats {suffix}",
        slug=f"seats-{suffix}",
        status=enums.TournamentStatus.COMPLETED,
        is_finished=True,
    )
    session.add(tournament)
    await session.flush()
    rule_id = await seed_scoring_rule(session, workspace.id)
    stage = Stage(
        tournament_id=tournament.id,
        name="Playoffs",
        stage_type=enums.StageType.SINGLE_ELIMINATION,
        order=1,
        scoring_rule_id=rule_id,
    )
    session.add(stage)
    await session.flush()
    seed.stage_name = stage.name

    teams: dict[str, Team] = {}
    for key in ("X", "Y", "Z"):
        team = Team(tournament_id=tournament.id, name=f"Team {key} {suffix}", balancer_name=f"team-{key}-{suffix}")
        session.add(team)
        teams[key] = team
    await session.flush()
    seed.teams = {key: team.id for key, team in teams.items()}
    for key, user_key in (("X", "alice"), ("Y", "bob"), ("Z", "carol")):
        session.add(
            Player(
                name=f"zz{suffix}-{user_key}",
                rank=2000,
                assignments=[
                    assignment_of(
                        await rated_leaf(
                            session,
                            discipline="overwatch",
                            workspace_id=tournament.workspace_id,
                            role="tank",
                            sub_role=None,
                        )
                    )
                ],
                is_substitution=False,
                tournament_id=tournament.id,
                team_id=teams[key].id,
                workspace_member_id=members[user_key],
            )
        )
    await session.flush()

    # alice plays for X: she wins E1 and the lobby, draws E2 and loses E4.
    plan = {
        "E1": [(teams["X"], 2), (teams["Y"], 1)],
        "E2": [(teams["X"], 2), (teams["Z"], 2)],
        "LOBBY": [(teams["X"], 30), (teams["Y"], 20), (teams["Z"], 10)],
        "E4": [(teams["Y"], 2), (teams["X"], 0)],
    }
    for name, seats in plan.items():
        encounter = await seed_encounter(session, tournament, rule_id, seats, name=name, round_=None)
        seed.encounters[name] = encounter.id
    # Only E1 sits in the bracket, on the stage.
    session.add(
        BracketEncounter(encounter_id=seed.encounters["E1"], tournament_id=tournament.id, stage_id=stage.id, round=3)
    )
    await session.flush()

    # The roster snapshot of E1's first seat: alice, as a tank.
    first_seat = (
        await session.execute(
            sa.text("select id from encounter.team where encounter_id = :e and slot = 1"),
            {"e": seed.encounters["E1"]},
        )
    ).scalar_one()
    member = EncounterTeamMember(
        encounter_id=seed.encounters["E1"],
        encounter_team_id=first_seat,
        active=True,
        workspace_member_id=members["alice"],
        display_name_snapshot="Alice",
    )
    session.add(member)
    await session.flush()
    leaf = await CatalogRoleRepository().resolve(
        session, discipline="overwatch", workspace_id=workspace.id, dimension=None, code="tank"
    )
    session.add(EncounterTeamMemberRole(team_member_id=member.id, dimension_id=leaf.dimension_id, role_id=leaf.id))
    await session.commit()
    return seed


async def _drop(session: Any, seed: _Seed) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id == seed.workspace_id))
    await session.execute(sa.delete(User).where(User.id.in_(list(seed.users.values()))))
    await session.commit()


def _params(**overrides: Any) -> pagination.PaginationSortParams:
    return pagination.PaginationSortParams(**{"page": 1, "per_page": 50, "sort": "id", "order": "asc", **overrides})


def _run(db_session, body):
    async def _go():
        seed = await _seed(db_session)
        try:
            return seed, await body(seed)
        finally:
            await _drop(db_session, seed)

    return asyncio.run(_go())


def test_the_encounter_list_filters_by_the_outcome_of_the_viewers_seat(db_session) -> None:
    async def body(seed: _Seed) -> dict[str, list[int]]:
        found: dict[str, list[int]] = {}
        for result in (None, "win", "loss", "draw"):
            rows, total = await encounter_queries.get_user_encounters_paginated(
                db_session, seed.users["alice"], _params(), seed.workspace_id, result=result
            )
            assert total == len({row[0].id for row in rows})
            found[str(result)] = sorted({row[0].id for row in rows})
        return found

    seed, found = _run(db_session, body)
    ids = seed.encounters
    assert found["None"] == sorted(ids.values())
    # A win is a sole first place, so the lobby counts; a shared first place is a draw.
    assert found["win"] == sorted([ids["E1"], ids["LOBBY"]])
    assert found["loss"] == [ids["E4"]]
    assert found["draw"] == [ids["E2"]]


def test_the_opponent_filter_and_the_sort_by_round_read_the_other_seats(db_session) -> None:
    async def body(seed: _Seed) -> tuple[list[int], list[int]]:
        rows, _ = await encounter_queries.get_user_encounters_paginated(
            db_session, seed.users["alice"], _params(), seed.workspace_id, opponent="Team Z"
        )
        by_opponent = sorted({row[0].id for row in rows})
        rows, _ = await encounter_queries.get_user_encounters_paginated(
            db_session, seed.users["alice"], _params(sort="round"), seed.workspace_id, stage="playoffs"
        )
        return by_opponent, sorted({row[0].id for row in rows})

    seed, (by_opponent, in_playoffs) = _run(db_session, body)
    assert by_opponent == sorted([seed.encounters["E2"], seed.encounters["LOBBY"]])
    assert in_playoffs == [seed.encounters["E1"]]


def test_the_encounter_list_sorts_by_closeness_and_by_round(db_session) -> None:
    async def body(seed: _Seed) -> dict[str, list[int]]:
        found: dict[str, list[int]] = {}
        for sort in ("closeness", "round"):
            rows, _ = await encounter_queries.get_user_encounters_paginated(
                db_session, seed.users["alice"], _params(sort=sort, order="desc"), seed.workspace_id
            )
            found[sort] = [row[0].id for row in rows]
        return found

    seed, found = _run(db_session, body)
    # A sort key moves rows around; it never drops one, and E1, the only bracketed encounter, has a round.
    assert sorted(found["closeness"]) == sorted(seed.encounters.values())
    assert found["round"][0] == seed.encounters["E1"]
    assert sorted(found["round"]) == sorted(seed.encounters.values())


def test_opponents_and_stage_records_are_read_off_placements(db_session) -> None:
    async def body(seed: _Seed):
        opponents = await encounter_queries.get_user_opponents(db_session, seed.users["alice"], seed.workspace_id)
        stages = await encounter_queries.get_user_stage_breakdown(db_session, seed.users["alice"], seed.workspace_id)
        return opponents, stages

    seed, (opponents, stages) = _run(db_session, body)
    by_name = {row.name.split()[1]: (row.wins, row.losses, row.draws) for row in opponents}
    # Y: won E1 and the lobby, lost E4. Z: drew E2, trailed alice in the lobby.
    assert by_name == {"Y": (2, 1, 0), "Z": (1, 0, 1)}
    # Only E1 sits in a stage, and "Playoffs" classifies; the rest have no bracket row.
    assert {row.kind: (row.w, row.l) for row in stages if row.kind} == {"playoffs": (1, 0)}


def test_the_dossier_context_carries_the_live_seats_roster_and_bracket_position(db_session) -> None:
    async def body(seed: _Seed) -> None:
        contexts = await encounter_queries.get_encounter_contexts(db_session, list(seed.encounters.values()))
        orm = (
            await db_session.execute(
                sa.select(Encounter)
                .options(joinedload(Encounter.tournament))
                .where(Encounter.id == seed.encounters["E1"])
            )
        ).scalar_one()
        read = _mappers.to_encounter_with_user_stats(
            orm, contexts[seed.encounters["E1"]], [], viewer_user_id=seed.users["alice"]
        )
        assert [seat.slot for seat in contexts[seed.encounters["LOBBY"]].participations] == [1, 2, 3]
        assert read.slot_count == 2 and read.round == 3
        assert read.stage is not None and read.stage.name == seed.stage_name
        assert [(team.slot, team.score, team.placement) for team in read.teams] == [(1, 2.0, 1), (2, 1.0, 2)]
        assert read.user_team_id == seed.teams["X"]
        assert [(player.user_id, player.name, player.role) for player in read.teams[0].players] == [
            (seed.users["alice"], "Alice", RoleRef(dimension="player_role", role="tank"))
        ]
        assert read.teams[1].players == []
        # An encounter outside any bracket reads round 0 and no stage.
        assert contexts[seed.encounters["E2"]].position is None

        # A leaf, another dimension and another discipline must still yield only the rated leaf.
        catalog = CatalogRoleRepository()
        tank = await catalog.resolve(
            db_session, discipline="overwatch", workspace_id=seed.workspace_id, dimension=None, code="tank"
        )
        leaf = CatalogRole(
            dimension_id=tank.dimension_id,
            workspace_id=seed.workspace_id,
            parent_role_id=tank.id,
            code="tank_main",
            name="Main",
        )
        trait = RoleDimension(discipline="overwatch", code="trait", name="Trait", selection_mode="single")
        db_session.add_all([leaf, trait])
        await db_session.flush()
        trait_role = CatalogRole(dimension_id=trait.id, code="caller", name="Caller")
        db_session.add(trait_role)
        await catalog.project_module(db_session, DISCIPLINES["lol"])
        foreign = await catalog.resolve(db_session, discipline="lol", workspace_id=None, dimension=None, code="support")
        member_id = read.teams[0].players[0].id
        assignment = await db_session.scalar(
            sa.select(EncounterTeamMemberRole).where(EncounterTeamMemberRole.team_member_id == member_id)
        )
        assignment.role_id = leaf.id
        db_session.add_all(
            [
                EncounterTeamMemberRole(team_member_id=member_id, dimension_id=trait.id, role_id=trait_role.id),
                EncounterTeamMemberRole(
                    team_member_id=member_id, dimension_id=foreign.dimension_id, role_id=foreign.id
                ),
            ]
        )
        await db_session.flush()
        contexts = await encounter_queries.get_encounter_contexts(db_session, [seed.encounters["E1"]])
        read = _mappers.to_encounter_with_user_stats(orm, contexts[seed.encounters["E1"]], [])
        assert read.teams[0].players[0].role == RoleRef(dimension="player_role", role="tank_main", parent="tank")

    _run(db_session, body)


def test_the_encounter_list_ships_and_reads_only_the_requested_entities(db_session) -> None:
    """``entities`` is opt-in: an entity not named is null/empty on every row and its table is never read."""
    service = UserService.of("overwatch")
    read = unwrap(UserService.get_encounters_by_user)
    engine = db_session.bind.sync_engine
    asks = {
        "nothing": [],
        "streak": ["teams", "teams.players"],
        "everything": ["tournament", "stage", "stage_item", "teams", "teams.players", "matches.map"],
    }

    async def body(seed: _Seed) -> dict[str, tuple[dict[int, Any], str]]:
        found = {}
        for label, entities in asks.items():
            statements: list[str] = []

            def record(_conn, _cursor, statement, *_args, sink=statements) -> None:
                sink.append(statement)

            sa.event.listen(engine, "before_cursor_execute", record)
            try:
                page = await read(
                    service, db_session, seed.users["alice"], _params(entities=entities), seed.workspace_id
                )
            finally:
                sa.event.remove(engine, "before_cursor_execute", record)
            found[label] = ({row.id: row for row in page.results}, "\n".join(statements))
        return found

    seed, found = _run(db_session, body)
    e1 = seed.encounters["E1"]
    rows, sql = found["nothing"]
    assert set(rows) == set(seed.encounters.values())
    for row in rows.values():
        assert (row.tournament, row.stage, row.stage_item, row.teams, row.matches, row.user_team_id) == (
            None,
            None,
            None,
            [],
            [],
            None,
        )
    # The bracket row is always read: it is the encounter's round, not an expansion.
    assert rows[e1].round == 3
    for table in (r"encounter\.team_member\b", r"tournament\.stage\b", r"tournament\.stage_item\b", r"stats\.fact\b"):
        assert not re.search(table, sql), table

    rows, sql = found["streak"]
    assert rows[e1].user_team_id == seed.teams["X"]
    assert [player.user_id for player in rows[e1].teams[0].players] == [seed.users["alice"]]
    assert (rows[e1].tournament, rows[e1].stage, rows[e1].matches) == (None, None, [])
    assert re.search(r"encounter\.team_member\b", sql) and not re.search(r"tournament\.stage\b", sql)

    rows, _sql = found["everything"]
    assert rows[e1].tournament is not None and rows[e1].stage is not None and rows[e1].stage.name == seed.stage_name
    assert rows[e1].teams == found["streak"][0][e1].teams


def test_map_records_count_duels_only(db_session) -> None:
    async def body(seed: _Seed):
        return await overview_queries.get_overview_map_records(db_session, [seed.users["alice"]], seed.workspace_id)

    seed, records = _run(db_session, body)
    # E1 2-1, E2 2-2, E4 0-2: the lobby's 30 points are not maps, and every duel has a result.
    assert records[seed.users["alice"]] == (4, 5, 3)


def test_maps_come_from_the_games_and_fall_back_to_a_wins_series_score_only(db_session) -> None:
    """``game_team`` is the source; a seat score is maps only for a ``wins`` series with no games."""

    async def body(seed: _Seed):
        async def _tournament_teams():
            row = (
                await db_session.execute(
                    sa.text("select tournament_id from tournament.team where id = :t"), {"t": seed.teams["X"]}
                )
            ).scalar_one()
            return row

        tournament_id = await _tournament_teams()
        tournament = await db_session.get(Tournament, tournament_id)
        teams = {key: await db_session.get(Team, team_id) for key, team_id in seed.teams.items()}
        points_rule = await seed_scoring_rule(db_session, seed.workspace_id, "points")
        wins_rule = await seed_scoring_rule(db_session, seed.workspace_id, "wins")
        # A points-preset duel: its 40-5 is points, so no map is won or lost -- with or without games.
        await seed_encounter(db_session, tournament, points_rule, [(teams["X"], 40), (teams["Y"], 5)], name="PTS")
        # A wins-preset duel whose seat score (9-0) disagrees with its two confirmed games (1-1): games win.
        with_games = await seed_encounter(
            db_session, tournament, wins_rule, [(teams["X"], 9), (teams["Y"], 0)], name="GAMES"
        )
        await seed_confirmed_games(db_session, with_games, [[1, 2], [2, 1]])
        # A wins-preset duel without games: its seat score is the maps (3-2).
        await seed_encounter(db_session, tournament, wins_rule, [(teams["X"], 3), (teams["Y"], 2)], name="SERIES")
        await db_session.commit()
        # The base seed's E1/E2/E4/lobby add 4 won / 5 lost maps (see the duel-only test above).
        return await overview_queries.get_overview_map_records(db_session, [seed.users["alice"]], seed.workspace_id)

    seed, records = _run(db_session, body)
    # 4+0 (base) + 1 (GAMES) + 3 (SERIES) won; 5+0 + 1 + 2 lost; PTS adds nothing and is not "played".
    assert records[seed.users["alice"]] == (8, 8, 5)
