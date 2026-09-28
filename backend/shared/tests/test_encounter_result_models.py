"""Pin the encounter-result model contract.

``tournament.encounter_result_audit`` is the trail behind every result decision,
and the three columns ``encres0001`` retired (``submitted_by_id``,
``submitted_at``, ``confirmed_by_id``) must stay retired: the audit rows carry
that history now, and re-mapping a scalar beside them would give two answers to
"who reported this".

These tests compile the models against the Postgres dialect and assert the
properties the audit table depends on. The assertions that read the
``encres0001`` revision file -- its CHECK expression, its enum ``create_type``
flags, its ``op.drop_column`` calls -- went away with the ``initial_v6`` squash,
which replaced every per-revision file with one generated baseline. This is a
metadata check, not a substitute for applying the schema: run
``alembic upgrade heads`` against a real database too.
"""

from __future__ import annotations

import typing

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from shared import models
from shared.core import enums
from shared.services.encounter.finalize import FinalizeSource


def _ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))


class TestDroppedColumns:
    def test_model_no_longer_maps_them(self):
        columns = set(models.Encounter.__table__.columns.keys())
        assert not columns & {"submitted_by_id", "submitted_at", "confirmed_by_id"}

    def test_confirmed_at_is_kept(self):
        """The only timestamp an admin confirmation with zero captain reports
        leaves behind; lists sort on it without joining the audit."""
        assert "confirmed_at" in models.Encounter.__table__.columns


class TestAuditTableDDL:
    def test_pk_is_bigserial(self):
        """db.TimeStampIntegerMixin uses BigInteger, not Integer."""
        assert "id BIGSERIAL NOT NULL" in _ddl(models.EncounterResultAudit)

    def test_actor_and_adopted_team_survive_deletion(self):
        """A deleted account or team must not erase the trail."""
        ddl = _ddl(models.EncounterResultAudit)
        assert 'FOREIGN KEY(actor_user_id) REFERENCES players."user" (id) ON DELETE SET NULL' in ddl
        assert "FOREIGN KEY(adopted_team_id) REFERENCES tournament.team (id) ON DELETE SET NULL" in ddl

    def test_actor_is_nullable_for_machine_decisions(self):
        """Challonge import and the bracket cascade have no human actor, and
        that NULL is how the trail tells them apart from an admin."""
        assert models.EncounterResultAudit.__table__.c.actor_user_id.nullable is True

    def test_source_fits_every_value_it_records(self):
        """``source`` holds a ``FinalizeSource`` on a series-level row and an
        ``EncounterGameResultSource`` on a per-game one. It was sized for the
        first set alone, so ``captain_agreement`` -- written by every
        captain-agreed map result -- overflowed ``varchar(16)`` and the insert
        died at the driver."""
        width = models.EncounterResultAudit.__table__.c.source.type.length
        longest = max(
            *(len(member.value) for member in enums.EncounterGameResultSource),
            *(len(literal) for literal in typing.get_args(FinalizeSource)),
        )
        assert width >= longest, f"source varchar({width}) cannot hold a {longest}-character value"
