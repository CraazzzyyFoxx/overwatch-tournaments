"""``flowP7_01_drop_team_formation`` on a populated database, up and back down.

A disposable database is taken to ``flowP4_03_seat_source``, seeded with tournaments of every formation shape, and the
real Alembic process applies the revision (``stats_parity`` scratch databases; the shared ``anak_test`` is never
touched). Upgrade moves ``draft_format_json`` into the flow; downgrade rebuilds both columns from the nodes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

from shared.testing.stats_parity import legacy_database, upgrade_database

PARENT = "flowP4_03_seat_source"
REVISION = "flowP7_01_drop_team_formation"
BACKEND = Path(__file__).resolve().parents[1]
CUSTOM = {"format": "custom", "round_rules": ["reverse"], "avg_tie_seed_reverse": True}


def _seed(conn: sa.Connection) -> dict[str, int]:
    def one(sql: str, **params: object) -> int:
        return conn.execute(sa.text(sql + " RETURNING id"), params).scalar_one()

    ws = one("INSERT INTO public.workspace (slug, name) VALUES ('p7up1', 'p7up1')")

    def tournament(slug: str, team_formation: str, draft_format: dict | None) -> int:
        return one(
            "INSERT INTO tournament.tournament (workspace_id, name, status, slug, team_formation, draft_format_json) "
            "VALUES (:w, :n, 'live', :n, :tf, CAST(:df AS jsonb))",
            w=ws,
            n=slug,
            tf=team_formation,
            df=json.dumps(draft_format) if draft_format is not None else None,
        )

    def node(tournament_id: int, kind: str, config: dict) -> int:
        return one(
            "INSERT INTO tournament.flow_node (tournament_id, kind, name, status, config) "
            "VALUES (:t, :k, :k, 'draft', CAST(:c AS jsonb))",
            t=tournament_id,
            k=kind,
            c=json.dumps(config),
        )

    ids: dict[str, int] = {}
    ids["draft"] = tournament("p7-draft", "draft", CUSTOM)
    ids["draft_reg"] = node(ids["draft"], "registration", {"check_in": False, "intake": "solo"})
    ids["draft_node"] = node(ids["draft"], "formation", {"mode": "draft"})
    ids["homeless"] = tournament("p7-homeless", "balancer", CUSTOM)
    ids["homeless_node"] = node(ids["homeless"], "formation", {"mode": "balancer"})
    ids["orphan"] = tournament("p7-orphan", "balancer", CUSTOM)
    ids["plain"] = tournament("p7-plain", "draft", None)
    ids["plain_node"] = node(ids["plain"], "formation", {"mode": "draft"})
    ids["teams"] = tournament("p7-teams", "registration", None)
    node(ids["teams"], "registration", {"check_in": False, "intake": "team"})
    node(ids["teams"], "formation", {"mode": "registered"})
    ids["solo"] = tournament("p7-solo", "solo", None)
    node(ids["solo"], "formation", {"mode": "manual"})
    return ids


def _downgrade(url: str, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", target],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url, "OWT_APPLY_ENCOUNTER_LAYER_DROP": "1", "OWT_APPLY_LEGACY_DROP": "1"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _configs(conn: sa.Connection) -> dict[int, dict]:
    return dict(conn.execute(sa.text("SELECT id, config FROM tournament.flow_node")).all())


def test_upgrade_moves_the_draft_format_into_the_flow_and_downgrade_rebuilds_the_columns() -> None:
    with legacy_database() as url:
        assert upgrade_database(url, PARENT).returncode == 0
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = _seed(conn)
                before = _configs(conn)
            done = upgrade_database(url, REVISION)
            assert done.returncode == 0, done.stdout + done.stderr
            with engine.connect() as conn:
                columns = {
                    r[0]
                    for r in conn.execute(
                        sa.text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'tournament' AND table_name = 'tournament'"
                        )
                    )
                }
                upgraded = _configs(conn)
            back = _downgrade(url, PARENT)
            assert back.returncode == 0, back.stdout + back.stderr
            with engine.connect() as conn:
                restored = {
                    r.slug: (r.team_formation, r.draft_format_json)
                    for r in conn.execute(
                        sa.text("SELECT slug, team_formation, draft_format_json FROM tournament.tournament")
                    )
                }
                downgraded = _configs(conn)
        finally:
            engine.dispose()
    assert not columns & {"team_formation", "draft_format_json"}
    # A draft node takes the format; a tournament without a draft node parks it on its first formation node.
    assert upgraded[ids["draft_node"]] == {"mode": "draft", "draft_format": CUSTOM}
    assert upgraded[ids["homeless_node"]] == {"mode": "balancer", "draft_format": CUSTOM}
    assert upgraded[ids["plain_node"]] == {"mode": "draft"}
    assert all(upgraded[i] == before[i] for i in (ids["draft_reg"],))
    # Downgrade: both columns come back from the flow and the nodes are as the previous release wrote them.
    assert restored == {
        "p7-draft": ("draft", CUSTOM),
        "p7-homeless": ("balancer", None),  # parked on a non-draft node: the old column had nowhere to keep it
        "p7-orphan": ("balancer", None),  # no formation node at all: the format was dropped on the way up
        "p7-plain": ("draft", None),
        "p7-teams": ("registration", None),
        "p7-solo": ("solo", None),
    }
    assert downgraded == before
