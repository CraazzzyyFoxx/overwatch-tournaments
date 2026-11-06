"""The /users overview numbers, executed against a real Postgres.

The compile-shape suites (``test_users_overview_filters_and_sorts``) prove the
SQL *says* the right thing; this one proves it *returns* the right thing. It
seeds one disposable workspace (plus a second one, to catch scope leaks), then
asserts the values and the orderings the grid shows; a second scenario pins two
workspaces to grids on unrelated rank scales and checks the all-workspaces
divisions meet on the native ladder::

    uv run pytest stats-service/tests/test_users_overview_db_values.py -v

Uses the shared ``db_session`` fixture (``shared.testing``, wired in conftest);
everything it writes hangs off two workspaces and one system division grid,
all dropped again at the end. Skips when Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import Any

import sqlalchemy as sa

from shared.core import enums
from shared.division_grid import DEFAULT_GRID, ladder_grid, stamp_canonical_numbers
from shared.models.division_grid import DivisionGrid as DivisionGridModel
from shared.models.division_grid import DivisionGridTier, DivisionGridVersion
from shared.models.identity.user import User
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.models.tournament import Player, Standing, Team, Tournament
from shared.models.tournament.player_role import assignment_of
from shared.schemas.role import RoleRef
from shared.services.ontology import rated_leaf
from shared.services.participant_result import write_participant_results
from src import schemas
from src.core import db as app_db
from src.services.user.queries.overview import UserOverviewQueries
from src.services.user.service import UserService
from tests.encounter_seed import add_observed_game, seed_encounter, seed_scoring_rule

overview_queries = UserOverviewQueries.of("overwatch")
user_service = UserService.of("overwatch")

RECENT = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=5)


def _rank_for_division(number: int) -> int:
    """A rank that DEFAULT_GRID resolves to exactly ``number``."""
    tier = next(tier for tier in DEFAULT_GRID.tiers if tier.number == number)
    return tier.rank_min


DIV_RANK = {3: _rank_for_division(3), 5: _rank_for_division(5), 7: _rank_for_division(7)}


class _Seed:
    """Ids of everything one run wrote, so the assertions can name them."""

    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        self.users: dict[str, int] = {}
        self.workspace_id = 0
        self.other_workspace_id = 0
        self.grid_id = 0

    def name(self, key: str) -> str:
        return f"zz{self.suffix}-{key}"


async def _seed(session: Any) -> _Seed:
    suffix = uuid.uuid4().hex[:10]
    seed = _Seed(suffix)

    # A system grid (workspace_id IS NULL) is what these tournaments resolve to
    # (no pin, no workspace default); the all-workspaces read takes each rank's
    # canonical number from its tiers.
    grid = DivisionGridModel(workspace_id=None, slug=f"sysgrid-{suffix}", name=f"System {suffix}")
    session.add(grid)
    await session.flush()
    seed.grid_id = grid.id
    version = DivisionGridVersion(grid_id=grid.id, version=1, label="v1", status="published")
    session.add(version)
    await session.flush()
    tiers = [
        DivisionGridTier(
            version_id=version.id,
            slug=f"tier-{tier.number}",
            number=tier.number,
            name=f"Division {tier.number}",
            sort_order=index,
            rank_min=tier.rank_min,
            rank_max=tier.rank_max,
            icon_url="",
        )
        for index, tier in enumerate(DEFAULT_GRID.tiers)
    ]
    stamp_canonical_numbers(tiers, "overwatch")
    session.add_all(tiers)

    workspace = Workspace(slug=f"ovw-{suffix}", name=f"Overview {suffix}")
    other = Workspace(slug=f"ovw2-{suffix}", name=f"Overview other {suffix}")
    session.add_all([workspace, other])
    await session.flush()
    seed.workspace_id, seed.other_workspace_id = workspace.id, other.id

    avatars = {"alpha": "https://cdn.test/alpha.png"}
    for key in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot"):
        user = User(name=seed.name(key), avatar_url=avatars.get(key))
        session.add(user)
        await session.flush()
        seed.users[key] = user.id

    members: dict[tuple[int, str], int] = {}
    for workspace_id, keys in (
        (seed.workspace_id, ("alpha", "bravo", "charlie", "delta", "echo")),
        (seed.other_workspace_id, ("alpha", "foxtrot")),
    ):
        for key in keys:
            member = WorkspaceMember(workspace_id=workspace_id, player_id=seed.users[key])
            session.add(member)
            await session.flush()
            members[(workspace_id, key)] = member.id

    def _tournament(slug: str, *, workspace_id: int, finished: bool, start, end) -> Tournament:
        return Tournament(
            workspace_id=workspace_id,
            name=f"{slug} {suffix}",
            slug=f"{slug}-{suffix}",
            status=enums.TournamentStatus.COMPLETED if finished else enums.TournamentStatus.LIVE,
            is_finished=finished,
            start_date=start,
            end_date=end,
        )

    jan = datetime.datetime(2026, 1, 10, tzinfo=datetime.UTC)
    mar = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)
    jul = datetime.datetime(2026, 7, 7, tzinfo=datetime.UTC)
    t1 = _tournament("t1", workspace_id=seed.workspace_id, finished=True, start=jan, end=jan)
    t2 = _tournament("t2", workspace_id=seed.workspace_id, finished=True, start=mar, end=mar)
    # Unfinished: counts as activity, contributes no maps and no tournaments_count.
    t4 = _tournament("t4", workspace_id=seed.workspace_id, finished=False, start=RECENT, end=None)
    t5 = _tournament("t5", workspace_id=seed.other_workspace_id, finished=True, start=jul, end=jul)
    session.add_all([t1, t2, t4, t5])
    await session.flush()

    teams: dict[str, Team] = {}
    for label, tournament in (
        ("A", t1),
        ("B", t1),
        ("E", t1),
        ("C", t2),
        ("D", t2),
        ("F", t4),
        ("G", t4),
        ("H", t5),
        ("I", t5),
    ):
        team = Team(
            tournament_id=tournament.id,
            name=f"Team {label} {suffix}",
            balancer_name=f"team-{label.lower()}-{suffix}",
        )
        session.add(team)
        teams[label] = team
    await session.flush()

    roster: list[tuple[str, str, str | None, int | None, Tournament]] = [
        ("A", "alpha", "tank", 3, t1),
        ("A", "bravo", "damage", 5, t1),
        ("B", "charlie", "support", 7, t1),
        ("E", "delta", None, 5, t1),
        ("C", "alpha", "tank", 3, t2),
        ("C", "charlie", "support", 7, t2),
        ("D", "bravo", "damage", 5, t2),
        ("F", "delta", None, 5, t4),
        # bravo's newest event is unranked: the current division stays the ranked t2 one.
        ("G", "bravo", "damage", None, t4),
        ("H", "alpha", "tank", 3, t5),
        ("I", "foxtrot", "damage", 5, t5),
    ]
    for team_label, user_key, role, division, tournament in roster:
        leaf = await rated_leaf(
            session, discipline=tournament.discipline, workspace_id=tournament.workspace_id, role=role, sub_role=None
        )
        session.add(
            Player(
                name=seed.name(user_key),
                rank=DIV_RANK.get(division),
                assignments=[] if leaf is None else [assignment_of(leaf)],
                is_substitution=False,
                tournament_id=tournament.id,
                team_id=teams[team_label].id,
                workspace_member_id=members[(tournament.workspace_id, user_key)],
            )
        )

    standings = [
        (t1, "A", 2, 2),
        (t1, "B", 1, 1),
        # overall_position 0 means "no placement": best_placement must skip it.
        (t1, "E", 1, 0),
        (t2, "C", 2, 5),
        (t2, "D", 1, 3),
    ]
    for tournament, team_label, position, overall in standings:
        session.add(
            Standing(
                tournament_id=tournament.id,
                team_id=teams[team_label].id,
                position=position,
                overall_position=overall,
                matches=1,
                win=1,
                draw=0,
                lose=0,
                points=1.0,
                buchholz=None,
            )
        )
    await session.flush()
    for tournament in (t1, t2, t5):
        await write_participant_results(session, tournament.id)

    encounters = [
        (t1, "A", "B", 2, 1),
        # 0-0: played nothing, so it is not an encounter_played.
        (t1, "A", "B", 0, 0),
        (t1, "E", "A", 3, 0),
        (t2, "C", "D", 3, 1),
        # Unfinished tournament: never counted in maps.
        (t4, "F", "G", 5, 0),
        (t5, "H", "I", 4, 0),
    ]
    rule_ids = {
        workspace_id: await seed_scoring_rule(session, workspace_id)
        for workspace_id in {tournament.workspace_id for tournament, *_ in encounters}
    }
    encounter_ids: list[int] = []
    for index, (tournament, home, away, home_score, away_score) in enumerate(encounters):
        encounter = await seed_encounter(
            session,
            tournament,
            rule_ids[tournament.workspace_id],
            [(teams[home], home_score), (teams[away], away_score)],
            name=f"E{index} {suffix}",
        )
        encounter_ids.append(encounter.id)

    # One parsed-log row, for charlie only: that is what has_logs selects.
    gamemode_id = (
        await session.execute(
            sa.text(
                "insert into catalog.entity (discipline, kind, name, slug, image_path)"
                " values ('overwatch', 'mode', :n, :s, '') returning id",
            ),
            {"n": f"Mode {suffix}", "s": f"mode-{suffix}"},
        )
    ).scalar_one()
    map_id = (
        await session.execute(
            sa.text(
                "insert into catalog.entity (discipline, kind, name, slug, parent_id, image_path)"
                " values ('overwatch', 'map', :n, :s, :g, '') returning id"
            ),
            {"n": f"Map {suffix}", "s": f"map-{suffix}", "g": gamemode_id},
        )
    ).scalar_one()
    await session.run_sync(
        lambda sync_session: add_observed_game(
            sync_session,
            encounter_id=encounter_ids[0],
            map_entity_id=map_id,
            position=1,
            duration_s=600,
            scores=(1, 0),
            observations=[
                (
                    members[(seed.workspace_id, "charlie")],
                    2,
                    None,
                    enums.LogStatsName.HeroTimePlayed,
                    600,
                )
            ],
        )
    )

    await session.commit()
    return seed


async def _drop(session: Any, seed: _Seed) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id.in_([seed.workspace_id, seed.other_workspace_id])))
    await session.execute(sa.delete(User).where(User.id.in_(list(seed.users.values()))))
    await session.execute(sa.delete(DivisionGridModel).where(DivisionGridModel.id == seed.grid_id))
    await session.commit()


def _overview_params(**overrides: Any) -> schemas.UserOverviewParams:
    params = schemas.UserOverviewParams(per_page=50, sort="name", order="asc")
    for key, value in overrides.items():
        setattr(params, key, value)
    return params


async def _order(session: Any, seed: _Seed, **overrides: Any) -> list[str]:
    users, _total = await overview_queries.get_overview_users(
        session,
        _overview_params(**overrides),
        DEFAULT_GRID,
        workspace_id=seed.workspace_id,
    )
    by_id = {user_id: key for key, user_id in seed.users.items()}
    return [by_id[user.id] for user in users]


async def _rows(session: Any, seed: _Seed, *, workspace_id: int | None, **overrides: Any) -> dict[str, Any]:
    response = await user_service.get_overview(
        session,
        _overview_params(**overrides),
        workspace_id=workspace_id,
        grid=DEFAULT_GRID,
    )
    by_id = {user_id: key for key, user_id in seed.users.items()}
    return {by_id[row.id]: row for row in response.results if row.id in by_id}


async def _run_all(session: Any) -> None:
    # The app engine is a pooled process-global. A sibling test that touched it
    # inside its own ``asyncio.run`` leaves connections bound to that (now
    # closed) loop, and the per-page aggregates below would be handed one. Start
    # and end with an empty pool so every connection belongs to this loop.
    await app_db.async_engine.dispose()
    try:
        seed = await _seed(session)
        try:
            await _assertions(session, seed)
        finally:
            await _drop(session, seed)
    finally:
        await app_db.async_engine.dispose()


async def _assertions(session: Any, seed: _Seed) -> None:
    scope = seed.workspace_id

    # ---- per-row values -------------------------------------------------
    rows = await _rows(session, seed, workspace_id=scope)
    assert set(rows) == {"alpha", "bravo", "charlie", "delta", "echo"}

    alpha = rows["alpha"]
    assert alpha.avatar_url == "https://cdn.test/alpha.png"
    assert rows["bravo"].avatar_url is None
    # 2-1 and 0-3 in t1, 3-1 in t2; the 0-0 encounter contributes nothing.
    assert (alpha.maps_won, alpha.maps_lost, alpha.encounters_played) == (5, 5, 3)
    assert (rows["bravo"].maps_won, rows["bravo"].maps_lost, rows["bravo"].encounters_played) == (3, 7, 3)
    assert (rows["charlie"].maps_won, rows["charlie"].maps_lost, rows["charlie"].encounters_played) == (4, 3, 2)
    assert (rows["delta"].maps_won, rows["delta"].maps_lost, rows["delta"].encounters_played) == (3, 0, 1)
    assert (rows["echo"].maps_won, rows["echo"].maps_lost, rows["echo"].encounters_played) == (0, 0, 0)

    assert alpha.best_placement == 2
    assert rows["charlie"].best_placement == 1
    assert rows["bravo"].best_placement == 2
    # Team E only ever placed 0 ("no placement"), so delta has none.
    assert rows["delta"].best_placement is None
    assert rows["echo"].best_placement is None

    assert alpha.last_active_at == "2026-03-01"
    assert rows["charlie"].last_active_at == "2026-03-01"
    # The unfinished tournament is activity, but not maps or tournaments_count.
    assert rows["delta"].last_active_at == RECENT.date().isoformat()
    assert rows["bravo"].last_active_at == RECENT.date().isoformat()
    assert rows["echo"].last_active_at is None
    assert (alpha.tournaments_count, rows["delta"].tournaments_count) == (2, 1)

    assert [role.role for role in alpha.roles] == [RoleRef(dimension="player_role", role="tank")]
    assert [role.division for role in alpha.roles] == [3]
    assert [role.division for role in rows["bravo"].roles] == [5]

    # ---- sorts ----------------------------------------------------------
    # winrates: delta 1.00 (1 encounter), charlie .571, alpha .500, bravo .300,
    # echo none.
    assert await _order(session, seed, sort="winrate", order="desc", min_encounters=0) == [
        "delta",
        "charlie",
        "alpha",
        "bravo",
        "echo",
    ]
    # min_encounters pushes the 1-encounter 100% player behind the real sample.
    assert await _order(session, seed, sort="winrate", order="desc", min_encounters=2) == [
        "charlie",
        "alpha",
        "bravo",
        "delta",
        "echo",
    ]
    assert await _order(session, seed, sort="winrate", order="asc", min_encounters=2) == [
        "bravo",
        "alpha",
        "charlie",
        "delta",
        "echo",
    ]
    # best_placement: 1, 2, 2, then the two users that never placed — last in
    # both directions.
    assert await _order(session, seed, sort="best_placement", order="asc") == [
        "charlie",
        "alpha",
        "bravo",
        "delta",
        "echo",
    ]
    descending = await _order(session, seed, sort="best_placement", order="desc")
    assert set(descending[:2]) == {"alpha", "bravo"}
    assert descending[2] == "charlie"
    assert set(descending[3:]) == {"delta", "echo"}

    # ---- filters --------------------------------------------------------
    assert set(await _order(session, seed, sort="name", divisions=[5])) == {"bravo", "delta"}
    assert set(await _order(session, seed, sort="name", divisions=[3, 7])) == {"alpha", "charlie"}
    assert await _order(session, seed, sort="name", has_logs=True) == ["charlie"]
    assert set(await _order(session, seed, sort="name", divisions=[5], has_logs=True)) == set()

    # ---- stats ----------------------------------------------------------
    stats = await user_service.get_overview_stats(
        session,
        schemas.UserOverviewStatsQueryParams(),
        grid=DEFAULT_GRID,
        workspace_id=scope,
    )
    assert stats.total_players == 5
    assert stats.with_logs_count == 1
    assert stats.role_counts == {"tank": 1, "damage": 1, "support": 1}
    # flex_count counts "plays anything"; flex_declared_count is what the chip
    # selects — here both are delta alone.
    assert stats.flex_count == 1
    assert stats.flex_declared_count == 1
    assert [(entry.division, entry.count) for entry in stats.division_counts] == [(3, 1), (5, 2), (7, 1)]

    filtered = await user_service.get_overview_stats(
        session,
        schemas.UserOverviewStatsQueryParams(divisions=[5]),
        grid=DEFAULT_GRID,
        workspace_id=scope,
    )
    assert filtered.total_players == 2
    # Picking one division must not zero every other chip.
    assert [(entry.division, entry.count) for entry in filtered.division_counts] == [(3, 1), (5, 2), (7, 1)]

    with_logs = await user_service.get_overview_stats(
        session,
        schemas.UserOverviewStatsQueryParams(has_logs=True),
        grid=DEFAULT_GRID,
        workspace_id=scope,
    )
    assert with_logs.total_players == 1
    assert with_logs.with_logs_count == 1
    assert [(entry.division, entry.count) for entry in with_logs.division_counts] == [(7, 1)]

    # ---- catalog --------------------------------------------------------
    catalog = await user_service.get_catalog(
        session,
        schemas.UserCatalogParams(query=f"zz{seed.suffix}"),
        grid=DEFAULT_GRID,
        workspace_id=scope,
    )
    entries = {entry.name: entry for letter in catalog.letters for entry in letter.users}
    assert catalog.total == 5
    catalog_alpha = entries[seed.name("alpha")]
    assert (catalog_alpha.maps_won, catalog_alpha.maps_lost, catalog_alpha.encounters_played) == (5, 5, 3)
    assert catalog_alpha.best_placement == 2
    assert catalog_alpha.last_active_at == "2026-03-01"
    assert catalog_alpha.avatar_url == "https://cdn.test/alpha.png"
    assert catalog_alpha.avg_placement == 3.5

    catalog_filtered = await user_service.get_catalog(
        session,
        schemas.UserCatalogParams(query=f"zz{seed.suffix}", divisions=[5], has_logs=False),
        grid=DEFAULT_GRID,
        workspace_id=scope,
    )
    assert {entry.name for letter in catalog_filtered.letters for entry in letter.users} == {
        seed.name("bravo"),
        seed.name("delta"),
    }

    # ---- all-workspaces scope -------------------------------------------
    all_rows = await _rows(session, seed, workspace_id=None, query=f"zz{seed.suffix}", fields=["name"])
    assert set(all_rows) == {"alpha", "bravo", "charlie", "delta", "echo", "foxtrot"}
    # The other workspace's finished tournament now counts.
    assert (all_rows["alpha"].maps_won, all_rows["alpha"].maps_lost) == (9, 5)
    assert all_rows["alpha"].encounters_played == 4
    assert all_rows["alpha"].last_active_at == "2026-07-07"
    assert all_rows["alpha"].tournaments_count == 3
    assert [role.division for role in all_rows["bravo"].roles] == [5]
    # The divisions chip in all-workspaces mode matches each row's canonical
    # number (its rank on its tournament's effective grid, the seeded ladder here).
    all_division_three = await _rows(
        session,
        seed,
        workspace_id=None,
        query=f"zz{seed.suffix}",
        fields=["name"],
        divisions=[3],
    )
    assert set(all_division_three) == {"alpha"}
    # The chip counts are the same canonical numbers.
    all_stats = await user_service.get_overview_stats(
        session,
        schemas.UserOverviewStatsQueryParams(query=f"zz{seed.suffix}"),
        grid=DEFAULT_GRID,
        workspace_id=None,
    )
    assert [(entry.division, entry.count) for entry in all_stats.division_counts] == [(3, 1), (5, 3), (7, 1)]

    scoped_div_five = await user_service.get_overview_stats(
        session,
        schemas.UserOverviewStatsQueryParams(query=f"zz{seed.suffix}", divisions=[5]),
        grid=DEFAULT_GRID,
        workspace_id=None,
    )
    assert scoped_div_five.total_players == 3  # bravo, delta, foxtrot


def test_overview_values_and_orderings_on_postgres(db_session) -> None:
    # One event loop for the whole scenario: the per-page aggregates open
    # isolated sessions on the app engine, which must not outlive it.
    asyncio.run(_run_all(db_session))


async def _two_rank_scales(session: Any) -> None:
    """Two workspaces whose grids number ranks on unrelated scales meet on the native ladder."""
    suffix = uuid.uuid4().hex[:10]
    ladder = ladder_grid("overwatch")
    assert ladder is not None
    workspace_ids: list[int] = []
    users: dict[str, int] = {}
    canonical: dict[str, int] = {}
    try:
        # Three tiers each; 2500 on the first grid and 25 on the second are both its tier 2.
        for key, scale, players in (("hi", 1000, (("hi", 2500),)), ("lo", 10, (("lo2", 25), ("lo1", 35)))):
            workspace = Workspace(slug=f"cnw-{key}-{suffix}", name=f"Canonical {key} {suffix}")
            session.add(workspace)
            await session.flush()
            workspace_ids.append(workspace.id)
            tiers = [
                DivisionGridTier(
                    slug=f"t{number}",
                    number=number,
                    name=f"T{number}",
                    sort_order=number,
                    rank_min=low,
                    rank_max=high,
                    icon_url="",
                )
                for number, low, high in ((1, 3 * scale, None), (2, 2 * scale, 3 * scale - 1), (3, 0, 2 * scale - 1))
            ]
            stamp_canonical_numbers(tiers, "overwatch")
            version = DivisionGridVersion(
                grid=DivisionGridModel(workspace_id=workspace.id, slug=f"cng-{suffix}", name=f"Grid {key} {suffix}"),
                version=1,
                label="v1",
                status="published",
                tiers=tiers,
            )
            session.add(version)
            await session.flush()
            # Pinned: each tournament's effective grid is its own workspace's.
            tournament = Tournament(
                workspace_id=workspace.id,
                name=f"cn-{key} {suffix}",
                slug=f"cn-{key}-{suffix}",
                status=enums.TournamentStatus.COMPLETED,
                is_finished=True,
                division_grid_version_id=version.id,
            )
            session.add(tournament)
            await session.flush()
            team = Team(tournament_id=tournament.id, name=f"cn-{key} {suffix}", balancer_name=f"cn-{key}-{suffix}")
            session.add(team)
            await session.flush()
            leaf = await rated_leaf(
                session, discipline=tournament.discipline, workspace_id=workspace.id, role="tank", sub_role=None
            )
            for user_key, rank in players:
                user = User(name=f"zz{suffix}-{user_key}")
                session.add(user)
                await session.flush()
                users[user_key] = user.id
                member = WorkspaceMember(workspace_id=workspace.id, player_id=user.id)
                session.add(member)
                await session.flush()
                session.add(
                    Player(
                        name=user.name,
                        rank=rank,
                        assignments=[] if leaf is None else [assignment_of(leaf)],
                        is_substitution=False,
                        tournament_id=tournament.id,
                        team_id=team.id,
                        workspace_member_id=member.id,
                    )
                )
                canonical[user_key] = next(
                    tier.canonical_number
                    for tier in tiers
                    if tier.rank_min <= rank and (tier.rank_max is None or rank <= tier.rank_max)
                )
        await session.commit()

        tier_two = canonical["hi"]
        assert canonical["lo2"] == tier_two != canonical["lo1"]
        # Read raw on the ladder, 25 would be another division: only the canonical lookup lands it here.
        assert ladder.resolve_division_number(25) != tier_two

        by_id = {user_id: key for key, user_id in users.items()}
        response = await user_service.get_overview(
            session,
            _overview_params(query=f"zz{suffix}", fields=["name"], divisions=[tier_two]),
            workspace_id=None,
            grid=ladder,
        )
        # The filter, the role badges and the chip counts all name the same canonical number.
        assert {by_id[row.id] for row in response.results} == {"hi", "lo2"}
        assert response.division_grids == []
        for row in response.results:
            assert [(role.division, role.division_grid_version_id) for role in row.roles] == [(tier_two, None)]
        stats = await user_service.get_overview_stats(
            session,
            schemas.UserOverviewStatsQueryParams(query=f"zz{suffix}"),
            grid=ladder,
            workspace_id=None,
        )
        assert {(entry.division, entry.count) for entry in stats.division_counts} == {
            (tier_two, 2),
            (canonical["lo1"], 1),
        }
    finally:
        await session.rollback()
        await session.execute(sa.delete(Workspace).where(Workspace.id.in_(workspace_ids)))
        await session.execute(sa.delete(User).where(User.id.in_(list(users.values()))))
        await session.commit()


def test_all_workspaces_divisions_meet_on_the_native_ladder_on_postgres(db_session) -> None:
    async def run() -> None:
        await app_db.async_engine.dispose()
        try:
            await _two_rank_scales(db_session)
        finally:
            await app_db.async_engine.dispose()

    asyncio.run(run())
