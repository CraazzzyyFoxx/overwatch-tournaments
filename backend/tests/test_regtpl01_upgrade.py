"""regtpl01 gives every registration form template its game (spec §8.4).

A disposable populated database is taken to ``achievement06``, templates of every backfill class are added, and the
real Alembic process applies ``regtpl01``. Only locally owned scratch databases are touched (``stats_parity``).
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa

from shared.testing.db import MIGRATION_PROOF_SKIP, migration_proofs_enabled
from shared.testing.stats_parity import legacy_database, seed_legacy, upgrade_database


def _schema(*required_identities: str, optional: tuple[str, ...] = ()) -> str:
    fields = [
        {"key": f"identity_{provider}", "kind": "builtin", "required": True} for provider in required_identities
    ] + [{"key": f"identity_{provider}", "kind": "builtin", "required": False} for provider in optional]
    return json.dumps({"schema_version": 1, "sections": [{"key": "accounts", "fields": fields}]})


_TEMPLATES = {
    # name: (schema, the game the backfill must pick)
    "battletag": (_schema("battlenet", optional=("discord",)), "overwatch"),
    "riot": (_schema("riot"), "lol"),
    # A required identity of no game, and an optional game identity only: the workspace's first enabled game.
    "discord-only": (_schema("discord", optional=("battlenet",)), "lol"),
    # Two games' identities required: ambiguous, the workspace's first enabled game.
    "both": (_schema("battlenet", "riot"), "lol"),
}


@pytest.fixture(scope="module")
def populated_achievement06():
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    with legacy_database() as url:
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = seed_legacy(conn)
        finally:
            engine.dispose()
        result = upgrade_database(url, "achievement06")
        assert result.returncode == 0, result.stdout + result.stderr
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                # League first: "first enabled" is then distinguishable from an Overwatch guess.
                conn.execute(
                    sa.text(
                        "UPDATE public.workspace SET disciplines_enabled = ARRAY['lol', 'overwatch'] WHERE id = :ws"
                    ),
                    {"ws": ids["workspace"]},
                )
                for name, (schema, _expected) in _TEMPLATES.items():
                    conn.execute(
                        sa.text(
                            "INSERT INTO balancer.registration_form_template (workspace_id, name, schema_json) "
                            "VALUES (:ws, :name, CAST(:schema AS json))"
                        ),
                        {"ws": ids["workspace"], "name": name, "schema": schema},
                    )
        finally:
            engine.dispose()
        yield url


def _rows(url: str, statement: str) -> list:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(sa.text(statement))]
    finally:
        engine.dispose()


def test_upgrade_gives_every_template_its_game(populated_achievement06):
    with legacy_database(template_url=populated_achievement06) as url:
        result = upgrade_database(url, "regtpl01")
        assert result.returncode == 0, result.stdout + result.stderr

        picked = dict(_rows(url, "SELECT name, discipline FROM balancer.registration_form_template"))
        assert picked == {name: expected for name, (_schema_json, expected) in _TEMPLATES.items()}
        assert _rows(
            url,
            "SELECT is_nullable FROM information_schema.columns WHERE table_schema = 'balancer' "
            "AND table_name = 'registration_form_template' AND column_name = 'discipline'",
        ) == [("NO",)]
        assert ("fk_registration_form_template_discipline",) in _rows(
            url,
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = CAST('balancer.registration_form_template' AS regclass)",
        )


def test_revision_chain_is_linear_after_achievement06():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from shared.testing.stats_parity import _BACKEND

    script = ScriptDirectory.from_config(Config(str(_BACKEND / "alembic.ini")))
    assert script.get_revision("regtpl01").down_revision == "achievement06"
    assert len(script.get_heads()) == 1
