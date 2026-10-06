"""Pin the ``public.audit_log`` model contract.

Three properties of this table are load-bearing and none of them is self-evident
from the model alone:

- **No foreign keys.** The journal must outlive the actor and the entity it
  describes. A CASCADE added "for referential hygiene" would delete a deleted
  tournament's history; a SET NULL would blank the actor. Both apply cleanly and
  destroy the only thing the table exists for.
- **No ``payload_json``, no ``method``.** The first was removed so that raw
  request bodies -- secrets, 16 MB base64 blobs -- are never captured at all,
  which is what makes "no secrets in the journal" structural rather than a
  denylist. The second had no reader. Re-adding either is a regression, not a
  feature.
- **Exactly three indexes, all trailing in ``created_at``.** A fourth taxes every
  INSERT on a growing table; sorting on ``id`` instead would order the feed
  wrongly, because ``now()`` is the transaction start time.

These tests compile the model against the Postgres dialect and assert those
properties. The mirror-image assertions against the hand-written ``audit0001``
revision went away with the ``initial_v6`` squash, which replaced every
per-revision file with one generated baseline. This is a metadata check, not a
substitute for applying the schema: run ``alembic upgrade heads`` against a real
database too.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from shared import models
from shared.rbac.catalog import permission_names_for_workspace_role

# The design's column contract, pinned literally. Deriving the expectation from
# the model would let both sides drift together in silence; this way a change has
# to be made here as well, which is where a reviewer will see it.
#
# (name, rendered PG type, nullable, the type as the revision spells it)
_EXPECTED: tuple[tuple[str, str, bool, str], ...] = (
    ("id", "BIGSERIAL", False, "sa.BigInteger()"),
    ("created_at", "TIMESTAMP WITH TIME ZONE", False, "sa.DateTime(timezone=True)"),
    ("workspace_id", "BIGINT", True, "sa.BigInteger()"),
    ("actor_auth_user_id", "BIGINT", True, "sa.BigInteger()"),
    ("actor_label", "VARCHAR(255)", True, "sa.String(length=255)"),
    ("source", "VARCHAR(16)", False, "sa.String(length=16)"),
    ("action", "VARCHAR(64)", False, "sa.String(length=64)"),
    ("entity_type", "VARCHAR(64)", True, "sa.String(length=64)"),
    ("entity_id", "BIGINT", True, "sa.BigInteger()"),
    ("entity_label", "VARCHAR(255)", True, "sa.String(length=255)"),
    ("before_json", "JSONB", True, "postgresql.JSONB()"),
    ("after_json", "JSONB", True, "postgresql.JSONB()"),
    ("reason", "TEXT", True, "sa.Text()"),
    ("ip_address", "VARCHAR(45)", True, "sa.String(length=45)"),
    ("user_agent", "VARCHAR(255)", True, "sa.String(length=255)"),
    ("correlation_id", "VARCHAR(64)", True, "sa.String(length=64)"),
)

_INDEXES: dict[str, tuple[str, ...]] = {
    "ix_audit_log_workspace_created": ("workspace_id", "created_at"),
    "ix_audit_log_entity_created": ("entity_type", "entity_id", "created_at"),
    "ix_audit_log_actor_created": ("actor_auth_user_id", "created_at"),
}


def _ddl() -> str:
    return str(CreateTable(models.AuditLog.__table__).compile(dialect=postgresql.dialect()))


class TestColumnParity:
    def test_model_declares_exactly_the_expected_columns_in_order(self):
        names = tuple(models.AuditLog.__table__.columns.keys())
        assert names == tuple(name for name, *_ in _EXPECTED)

    def test_rendered_types_match(self):
        ddl = _ddl()
        for name, sql_type, _, _ in _EXPECTED:
            assert f"{name} {sql_type}" in ddl, f"{name} is not {sql_type} in the model DDL"

    def test_source_and_action_are_required(self):
        """The two columns a row is worthless without: ``source`` distinguishes a
        machine write from an admin one, ``action`` is the whole semantics.
        ``record_audit`` takes both as required keywords for the same reason."""
        ddl = _ddl()
        assert "source VARCHAR(16) NOT NULL" in ddl
        assert "action VARCHAR(64) NOT NULL" in ddl


class TestNoForeignKeys:
    def test_model_has_none(self):
        """The row must survive the deletion of its actor, its entity and its
        workspace -- the convention ``event_outbox`` and ``workspace_event``
        already follow. Hence the ``*_label`` snapshots instead."""
        assert models.AuditLog.__table__.foreign_keys == set()
        assert "REFERENCES" not in _ddl()

    def test_the_label_snapshots_exist(self):
        """They are what makes a row readable once its referent is gone; drop
        them and the missing FK becomes data loss instead of a design choice."""
        columns = models.AuditLog.__table__.columns
        for name in ("actor_label", "entity_label"):
            assert name in columns
            assert columns[name].nullable is True


class TestRemovedColumns:
    def test_the_replacements_are_present(self):
        columns = models.AuditLog.__table__.columns
        assert {"before_json", "after_json", "action", "correlation_id"} <= set(columns.keys())


class TestIndexes:
    def test_model_declares_exactly_three(self):
        """A fourth composite index under `action`/`source` would tax every
        INSERT on a growing table; at ~45 MB/year those stay heap filters. Same
        trade as ``test_only_the_composite_index_exists`` for the result audit."""
        actual = {
            index.name: tuple(column.name for column in index.columns) for index in models.AuditLog.__table__.indexes
        }
        assert actual == _INDEXES

    def test_every_index_trails_in_created_at(self):
        """``now()`` is the transaction start time, so ``id`` order is not time
        order: reads sort on ``created_at`` with ``id`` as a tiebreaker, and each
        index has to end in the sort column to serve them."""
        for columns in _INDEXES.values():
            assert columns[-1] == "created_at"


class TestPermissionCatalog:
    def test_the_admin_role_is_the_one_with_a_gap(self):
        """``owner`` holds the ``admin.*`` wildcard and needs no row; ``admin``
        is an enumerated list, so a new catalog entry has to be attached."""
        assert permission_names_for_workspace_role("owner") == ("admin.*",)
        assert "audit.read" in permission_names_for_workspace_role("admin")
        assert "audit.read" not in permission_names_for_workspace_role("player")
