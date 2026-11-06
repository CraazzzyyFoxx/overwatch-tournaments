"""``flowP4_01_source_result`` on a populated database: seats are backfilled, tentative inputs go, the DE split moves
into the filter config, and an unmatched wired seat stops the upgrade.

A disposable database is taken to ``flowP3_06``, seeded with rows in the old shape, and the real Alembic process applies
the revision (``stats_parity`` scratch databases; the shared ``anak_test`` is never touched).
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from shared.testing.stats_parity import legacy_database, upgrade_database

REVISION = "flowP4_01_source_result"


def _seed(conn: sa.Connection, *, matching_result: bool) -> dict[str, int]:
    def one(sql: str, **params: object) -> int:
        return conn.execute(sa.text(sql + " RETURNING id"), params).scalar_one()

    ws = one("INSERT INTO public.workspace (slug, name) VALUES ('p4up', 'p4up')")
    tournament = one(
        "INSERT INTO tournament.tournament (workspace_id, name, status, slug) VALUES (:w, 'T', 'live', 'p4up')", w=ws
    )
    rule = one(
        "INSERT INTO encounter.scoring_rule (workspace_id, preset, game_formula, end_formula) "
        "VALUES (:w, 'wins', 'win', 'games >= best_of')",
        w=ws,
    )

    def stage(name: str, kind: str, order: int, upper: int | None = None) -> int:
        return one(
            'INSERT INTO tournament.stage (tournament_id, name, stage_type, "order", scoring_rule_id, advance_upper_count) '
            "VALUES (:t, :n, :k, :o, :r, :u)",
            t=tournament,
            n=name,
            k=kind,
            o=order,
            r=rule,
            u=upper,
        )

    groups, playoff = stage("Groups", "round_robin", 1, upper=2), stage("Playoff", "single_elimination", 2)

    def item(stage_id: int, name: str, kind: str, order: int, upper: int | None = None) -> int:
        return one(
            'INSERT INTO tournament.stage_item (stage_id, name, type, "order", advance_upper_count) '
            "VALUES (:s, :n, :k, :o, :u)",
            s=stage_id,
            n=name,
            k=kind,
            o=order,
            u=upper,
        )

    group_a, bracket = item(groups, "A", "group", 0, upper=1), item(playoff, "Bracket", "single_bracket", 0)
    teams = [
        one(
            "INSERT INTO tournament.team (tournament_id, name, balancer_name) VALUES (:t, :n, :n)",
            t=tournament,
            n=f"p4up-{i}",
        )
        for i in range(3)
    ]

    def node(kind: str, name: str, status: str, stage_id: int | None = None, config: dict | None = None) -> int:
        return one(
            "INSERT INTO tournament.flow_node (tournament_id, kind, name, status, stage_id, config) "
            "VALUES (:t, :k, :n, :s, :st, CAST(:c AS jsonb))",
            t=tournament,
            k=kind,
            n=name,
            s=status,
            st=stage_id,
            c=json.dumps(config or {}),
        )

    group_node = node("stage", "Groups", "completed", groups)
    filter_node = node("filter", "Top", "final", config={"mode": "per_item_top", "n": 2})
    playoff_node = node("stage", "Playoff", "draft", playoff)
    for source, port, target, target_port in (
        (group_node, "ranking", filter_node, "ranking"),
        (filter_node, "passed", playoff_node, "participants"),
    ):
        one(
            "INSERT INTO tournament.flow_edge (tournament_id, source_node_id, source_port, target_node_id, target_port) "
            "VALUES (:t, :s, :sp, :d, :dp)",
            t=tournament,
            s=source,
            sp=port,
            d=target,
            dp=target_port,
        )
    results = {
        team: one(
            "INSERT INTO tournament.flow_node_result (node_id, port, rank, team_id, state) "
            "VALUES (:n, 'passed', :r, :t, 'final')",
            n=filter_node,
            r=rank,
            t=team,
        )
        for rank, team in enumerate(teams[:2] if matching_result else teams[1:2], 1)
    }

    def seat(slot: int, kind: str, team: int | None, source_position: int | None) -> int:
        return one(
            "INSERT INTO tournament.stage_item_input "
            "(stage_item_id, slot, input_type, team_id, source_stage_item_id, source_position) "
            "VALUES (:i, :s, CAST(:k AS tournament.stageiteminputtype), :t, :src, :p)",
            i=bracket,
            s=slot,
            k=kind,
            t=team,
            src=group_a if source_position else None,
            p=source_position,
        )

    wired = seat(1, "final", teams[0], 1)
    tentative = seat(2, "tentative", None, 2)
    by_hand = seat(3, "final", teams[2], None)
    return {
        "group_a": group_a,
        "filter_node": filter_node,
        "wired": wired,
        "tentative": tentative,
        "by_hand": by_hand,
        "wired_result": results.get(teams[0], 0),
    }


def test_upgrade_backfills_seats_converts_tentative_and_copies_the_split() -> None:
    with legacy_database() as url:
        assert upgrade_database(url, "flowP3_06").returncode == 0
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = _seed(conn, matching_result=True)
            done = upgrade_database(url, REVISION)
            assert done.returncode == 0, done.stdout + done.stderr
            with engine.connect() as conn:
                seats = {
                    row.id: row
                    for row in conn.execute(
                        sa.text(
                            "SELECT id, input_type::text AS kind, team_id, source_result_id "
                            "FROM tournament.stage_item_input"
                        )
                    )
                }
                config = conn.execute(
                    sa.text("SELECT config FROM tournament.flow_node WHERE id = :id"), {"id": ids["filter_node"]}
                ).scalar_one()
                columns = {
                    row[0]
                    for row in conn.execute(
                        sa.text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'tournament' AND table_name = 'stage_item_input'"
                        )
                    )
                }
        finally:
            engine.dispose()
    assert seats[ids["wired"]].source_result_id == ids["wired_result"]
    assert seats[ids["by_hand"]].source_result_id is None
    assert (seats[ids["tentative"]].kind, seats[ids["tentative"]].team_id) == ("empty", None)
    assert config["upper"] == 2
    assert config["per_item_upper"] == {str(ids["group_a"]): 1}
    assert {"source_stage_item_id", "source_position"}.isdisjoint(columns)


def test_upgrade_stops_on_a_wired_seat_without_a_result_row() -> None:
    with legacy_database() as url:
        assert upgrade_database(url, "flowP3_06").returncode == 0
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = _seed(conn, matching_result=False)
            done = upgrade_database(url, REVISION)
        finally:
            engine.dispose()
    assert done.returncode != 0
    assert str([ids["wired"]]) in done.stdout + done.stderr
