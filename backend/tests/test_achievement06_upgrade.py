"""achievement06 drops the rule discipline default and nothing else.

A disposable populated database is taken to ``ingest01``, a second game's rule is added, and the real Alembic process
applies ``achievement06``. Only locally owned scratch databases are touched (``stats_parity``); the shared test
database is never reset.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from shared.testing.db import MIGRATION_PROOF_SKIP, migration_proofs_enabled
from shared.testing.stats_parity import legacy_database, seed_legacy, upgrade_database

_RULE_STATE = (
    "SELECT id, workspace_id, slug, discipline, entity_id, entity_kind, grain, enabled, rule_version "
    "FROM achievements.rule ORDER BY id"
)
_DISCIPLINE_COLUMN = (
    "SELECT column_default, is_nullable FROM information_schema.columns "
    "WHERE table_schema = 'achievements' AND table_name = 'rule' AND column_name = 'discipline'"
)
_CONSTRAINTS = (
    "SELECT conname, contype FROM pg_constraint WHERE conrelid = CAST('achievements.rule' AS regclass) ORDER BY conname"
)


@pytest.fixture(scope="module")
def populated_ingest01():
    """One populated database at ``ingest01``, shared read-only by the cases below."""
    if not migration_proofs_enabled():
        pytest.skip(MIGRATION_PROOF_SKIP)
    with legacy_database() as url:
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                ids = seed_legacy(conn)
        finally:
            engine.dispose()
        result = upgrade_database(url, "ingest01")
        assert result.returncode == 0, result.stdout + result.stderr
        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                # A rule that still relies on the server default, and a second game's rule.
                conn.execute(
                    sa.text(
                        "INSERT INTO achievements.rule (workspace_id, slug, name, description_ru, description_en, "
                        "category, scope, grain) VALUES (:ws, 'defaulted', 'd', 'd', 'd', 'overall', 'global', 'user')"
                    ),
                    {"ws": ids["workspace"]},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO achievements.rule (workspace_id, slug, name, description_ru, description_en, "
                        "discipline, category, scope, grain) "
                        "VALUES (:ws, 'lol-rule', 'l', 'l', 'l', 'lol', 'overall', 'global', 'user')"
                    ),
                    {"ws": ids["workspace"]},
                )
        finally:
            engine.dispose()
        yield url, ids


def _rows(url: str, statement: str) -> list:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.execute(sa.text(statement))]
    finally:
        engine.dispose()


def test_upgrade_removes_only_the_default_and_preserves_every_rule(populated_ingest01):
    template, _ids = populated_ingest01
    before_default = _rows(template, _DISCIPLINE_COLUMN)
    assert before_default == [("'overwatch'::character varying", "NO")]
    before_rows = _rows(template, _RULE_STATE)
    before_constraints = _rows(template, _CONSTRAINTS)
    assert {row[2]: row[3] for row in before_rows}["lol-rule"] == "lol"
    assert {row[2]: row[3] for row in before_rows}["defaulted"] == "overwatch"

    with legacy_database(template_url=template) as url:
        result = upgrade_database(url, "achievement06")
        assert result.returncode == 0, result.stdout + result.stderr

        # No default left, still NOT NULL; ids, values, links and every constraint are exactly as they were.
        assert _rows(url, _DISCIPLINE_COLUMN) == [(None, "NO")]
        assert _rows(url, _RULE_STATE) == before_rows
        assert _rows(url, _CONSTRAINTS) == before_constraints
        names = {row[0] for row in before_constraints}
        assert {"fk_rule_discipline", "fk_rule_entity", "uq_achievement_rule_workspace_slug"} <= names

        # A writer that forgets the discipline now fails instead of becoming an Overwatch rule.
        engine = sa.create_engine(url)
        try:
            with engine.connect() as conn, pytest.raises(sa.exc.IntegrityError, match="discipline"):
                conn.execute(
                    sa.text(
                        "INSERT INTO achievements.rule (workspace_id, slug, name, description_ru, description_en, "
                        "category, scope, grain) SELECT id, 'nameless', 'n', 'n', 'n', 'overall', 'global', 'user' "
                        "FROM public.workspace LIMIT 1"
                    )
                )
        finally:
            engine.dispose()

        # Re-running is a no-op and a second head is impossible: the chain stays linear.
        repeated = upgrade_database(url, "head")
        assert repeated.returncode == 0, repeated.stdout + repeated.stderr
        assert _rows(url, _RULE_STATE) == before_rows


def test_revision_chain_is_linear_after_ingest01():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from shared.testing.stats_parity import _BACKEND

    script = ScriptDirectory.from_config(Config(str(_BACKEND / "alembic.ini")))
    assert script.get_revision("achievement06").down_revision == "ingest01"
    assert len(script.get_heads()) == 1


def test_downgrade_refuses_instead_of_restoring_the_implicit_overwatch_default():
    import importlib.util

    from shared.testing.stats_parity import _BACKEND

    spec = importlib.util.spec_from_file_location(
        "achievement06_revision", _BACKEND / "migrations/versions/achievement06_rule_discipline_default.py"
    )
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    with pytest.raises(RuntimeError, match="forward-fix-only"):
        revision.downgrade()
