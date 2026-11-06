"""``flowP4_03_seat_source`` on a populated database: hand-seeded seats become ``manual``, completed stage nodes without
``completed_at`` get their latest encounter time.

A disposable database is taken to ``flowP6_02_drop_is_league``, seeded, and the real Alembic process applies the
revision (``stats_parity`` scratch databases; the shared ``anak_test`` is never touched).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from shared.testing.stats_parity import legacy_database, upgrade_database

PARENT = "flowP6_02_drop_is_league"
REVISION = "flowP4_03_seat_source"
ENDED = datetime(2026, 3, 4, 12, tzinfo=UTC)


def _seed(conn: sa.Connection) -> dict[str, int]:
    def one(sql: str, **params: object) -> int:
        return conn.execute(sa.text(sql + " RETURNING id"), params).scalar_one()

    ws = one("INSERT INTO public.workspace (slug, name) VALUES ('p4up3', 'p4up3')")
    tournament = one(
        "INSERT INTO tournament.tournament (workspace_id, name, status, slug) VALUES (:w, 'T', 'live', 'p4up3')", w=ws
    )
    rule = one(
        "INSERT INTO encounter.scoring_rule (workspace_id, preset, game_formula, end_formula) "
        "VALUES (:w, 'wins', 'win', 'games >= best_of')",
        w=ws,
    )
    stages = [
        one(
            'INSERT INTO tournament.stage (tournament_id, name, stage_type, "order", scoring_rule_id) '
            "VALUES (:t, :n, 'round_robin', :o, :r)",
            t=tournament,
            n=name,
            o=order,
            r=rule,
        )
        for order, name in enumerate(("Day 1", "Day 2"), 1)
    ]
    item = one(
        "INSERT INTO tournament.stage_item (stage_id, name, type, \"order\") VALUES (:s, 'A', 'group', 0)",
        s=stages[0],
    )
    teams = [
        one(
            "INSERT INTO tournament.team (tournament_id, name, balancer_name) VALUES (:t, :n, :n)",
            t=tournament,
            n=f"p4up3-{i}",
        )
        for i in range(2)
    ]
    nodes = {
        name: one(
            "INSERT INTO tournament.flow_node (tournament_id, kind, name, status, stage_id, config) "
            "VALUES (:t, 'stage', :n, :s, :st, '{}'::jsonb)",
            t=tournament,
            n=name,
            s=status,
            st=stage,
        )
        for name, status, stage in (("Day 1", "completed", stages[0]), ("Day 2", "completed", stages[1]))
    }
    encounter = one(
        "INSERT INTO encounter.encounter (workspace_id, discipline, tournament_id, scoring_rule_id, name, slot_count, "
        "status, ended_at) SELECT :w, discipline, :t, :r, 'E', 2, 'OPEN', :e FROM tournament.tournament WHERE id = :t",
        w=ws,
        t=tournament,
        r=rule,
        e=ENDED,
    )
    conn.execute(
        sa.text(
            "INSERT INTO tournament.bracket_encounter (encounter_id, tournament_id, stage_id, stage_item_id, round) "
            "VALUES (:e, :t, :s, :i, 1)"
        ),
        {"e": encounter, "t": tournament, "s": stages[0], "i": item},
    )
    result = one(
        "INSERT INTO tournament.flow_node_result (node_id, port, rank, team_id, state) "
        "VALUES (:n, 'ranking', 1, :t, 'final')",
        n=nodes["Day 2"],
        t=teams[0],
    )

    def seat(slot: int, team: int | None, source: int | None) -> int:
        return one(
            "INSERT INTO tournament.stage_item_input (stage_item_id, slot, input_type, team_id, source_result_id) "
            "VALUES (:i, :s, CAST(:k AS tournament.stageiteminputtype), :t, :src)",
            i=item,
            s=slot,
            k="final" if team else "empty",
            t=team,
            src=source,
        )

    return {
        "day1": nodes["Day 1"],
        "day2": nodes["Day 2"],
        "flow_seat": seat(1, teams[0], result),
        "hand_seat": seat(2, teams[1], None),
        "empty_seat": seat(3, None, None),
    }


def test_upgrade_stamps_hand_seats_and_backfills_completed_at() -> None:
    with legacy_database() as url:
        assert upgrade_database(url, PARENT).returncode == 0
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = _seed(conn)
            done = upgrade_database(url, REVISION)
            assert done.returncode == 0, done.stdout + done.stderr
            with engine.connect() as conn:
                sources = dict(conn.execute(sa.text("SELECT id, seat_source FROM tournament.stage_item_input")).all())
                completed = dict(conn.execute(sa.text("SELECT id, completed_at FROM tournament.flow_node")).all())
        finally:
            engine.dispose()
    assert sources == {ids["flow_seat"]: "flow", ids["hand_seat"]: "manual", ids["empty_seat"]: "flow"}
    # Day 1 has a timed encounter; Day 2 has none and stays NULL (the engine ranks it last).
    assert completed[ids["day1"]] == ENDED
    assert completed[ids["day2"]] is None
