"""tournament.encounter status indexes (dashboard + live/upcoming feeds)

Adds:
  * a composite ``(tournament_id, status)`` index — the common "encounters
    for this tournament, filtered by status" query currently only has
    ``tournament_id`` indexed, so the status filter is applied after a
    tournament-scoped scan.
  * a partial index for the live/upcoming feed
    (``status IN ('PENDING', 'OPEN')``) — that predicate is highly
    selective once a tournament accumulates COMPLETED encounters, so a
    small partial index serves it far better than the composite above.

GOTCHA (verified against the DDL, not assumed): ``Encounter.status`` is
``Enum(enums.EncounterStatus)`` declared WITHOUT ``values_callable``, so
SQLAlchemy's default ``Enum`` type persists the Python member NAME, not
``.value`` — the underlying Postgres type was created by the very first
migration (``a7634c02717d_initial_v5``) as
``sa.Enum('COMPLETED', 'PENDING', 'OPEN', name='encounterstatus')``, i.e.
uppercase labels, not ``completed``/``pending``/``open``.

A second, easy-to-miss gotcha: that ``CREATE TYPE`` ran with no explicit
schema, so ``encounterstatus`` lives in the **default/public** schema — even
though the ``encounter`` table itself was later relocated to the
``tournament`` schema by ``b8e2f4a1c903_split_domain_schemas``. ``ALTER
TABLE ... SET SCHEMA`` moves the table only, not types it depends on, and
no later migration moved the type. (Contrast with the newer
``result_status`` column on the same model, whose enum
(``encounterresultstatus``) *was* explicitly created in the ``tournament``
schema — the two columns' enum types do not share a schema.) The partial
index below therefore casts to ``public.encounterstatus`` explicitly.

Built CONCURRENTLY (via autocommit_block) so building them does not lock
writes on the encounter table.

Revision ID: perfidx04
Revises: perfidx03
Create Date: 2026-07-04 00:00:01.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "perfidx04"
down_revision: str | None = "perfidx03"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_encounter_tournament_status",
            "encounter",
            ["tournament_id", "status"],
            schema="tournament",
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_encounter_status_live_upcoming",
            "encounter",
            ["tournament_id", "status"],
            schema="tournament",
            unique=False,
            postgresql_where=sa.text("status IN ('PENDING'::public.encounterstatus, 'OPEN'::public.encounterstatus)"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_encounter_status_live_upcoming",
            table_name="encounter",
            schema="tournament",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_encounter_tournament_status",
            table_name="encounter",
            schema="tournament",
            postgresql_concurrently=True,
            if_exists=True,
        )
