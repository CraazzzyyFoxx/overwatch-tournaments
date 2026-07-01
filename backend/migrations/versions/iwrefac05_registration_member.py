"""identity refactor: registration on workspace_member_id (drop auth_user_id + workspace_id)

Re-bases ``balancer.registration`` onto ``workspace_member_id`` (FK
``public.workspace_member.id``, ON DELETE SET NULL) instead of the
denormalized ``auth_user_id``/``workspace_id`` columns. Backfills
``workspace_member_id`` by joining the account that submitted the
registration (``auth_user_id``) to its ``players.user`` row and then to the
``workspace_member`` row for the registration's own ``workspace_id``.

Sheet/CSV imports (no registering account, ``auth_user_id`` NULL) keep
``workspace_member_id = NULL`` — expected; the partial unique index treats
multiple NULLs as distinct, matching today's behavior for tag-only rows.

Recreates ``uq_balancer_registration_user`` — the partial unique index
guarding one active registration per tournament — on
``(tournament_id, workspace_member_id)`` instead of
``(tournament_id, auth_user_id)``.

Revision ID: iwrefac05
Revises: iwrefac04
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "iwrefac05"
down_revision: Union[str, None] = "iwrefac04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "registration",
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )
    op.execute(
        """
        UPDATE balancer.registration r
        SET workspace_member_id = wm.id
        FROM workspace_member wm
        JOIN players."user" pu ON pu.id = wm.player_id
        WHERE pu.auth_user_id = r.auth_user_id
          AND wm.workspace_id = r.workspace_id
        """
    )
    op.create_foreign_key(
        "fk_registration_workspace_member",
        "registration",
        "workspace_member",
        ["workspace_member_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="public",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_balancer_registration_workspace_member_id",
        "registration",
        ["workspace_member_id"],
        schema="balancer",
    )

    # Recreate the active-registration uniqueness on the new anchor.
    op.drop_index("uq_balancer_registration_user", table_name="registration", schema="balancer")
    op.create_index(
        "uq_balancer_registration_user",
        "registration",
        ["tournament_id", "workspace_member_id"],
        unique=True,
        schema="balancer",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # auth_user_id/workspace_id FKs were created unnamed (inline ForeignKeyConstraint in
    # m3h5i7j1k2l3_normalize_balancer_3nf), so Postgres auto-named them
    # (registration_auth_user_id_fkey / registration_workspace_id_fkey) — dropping the
    # columns cascades those constraints without an explicit drop_constraint.
    op.drop_index("ix_balancer_registration_auth_user_id", table_name="registration", schema="balancer")
    op.drop_column("registration", "auth_user_id", schema="balancer")
    op.drop_column("registration", "workspace_id", schema="balancer")


def downgrade() -> None:
    # NOTE: sheet/CSV rows (workspace_member_id IS NULL) have no member to walk back
    # through, so their auth_user_id/workspace_id cannot be recovered here — they were
    # NULL/derived-only before this migration too, so this matches prior behavior for
    # those rows (auth_user_id was already NULL; workspace_id was NOT NULL and is
    # re-derived from the tournament below as a best-effort fallback).
    op.add_column(
        "registration",
        sa.Column("workspace_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration",
        sa.Column("auth_user_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )

    op.execute(
        """
        UPDATE balancer.registration r
        SET auth_user_id = pu.auth_user_id,
            workspace_id = wm.workspace_id
        FROM workspace_member wm
        JOIN players."user" pu ON pu.id = wm.player_id
        WHERE wm.id = r.workspace_member_id
        """
    )
    # Sheet/CSV rows (no member) still need workspace_id populated — re-derive it from
    # the owning tournament, mirroring how workspace_id was originally denormalized.
    op.execute(
        """
        UPDATE balancer.registration r
        SET workspace_id = t.workspace_id
        FROM tournament.tournament t
        WHERE t.id = r.tournament_id
          AND r.workspace_id IS NULL
        """
    )
    op.alter_column("registration", "workspace_id", nullable=False, schema="balancer")

    op.create_foreign_key(
        "registration_workspace_id_fkey",
        "registration",
        "workspace",
        ["workspace_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="public",
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "registration_auth_user_id_fkey",
        "registration",
        "user",
        ["auth_user_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="auth",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_balancer_registration_auth_user_id",
        "registration",
        ["auth_user_id"],
        schema="balancer",
    )

    op.drop_index("uq_balancer_registration_user", table_name="registration", schema="balancer")
    op.create_index(
        "uq_balancer_registration_user",
        "registration",
        ["tournament_id", "auth_user_id"],
        unique=True,
        schema="balancer",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.drop_index("ix_balancer_registration_workspace_member_id", table_name="registration", schema="balancer")
    op.drop_constraint("fk_registration_workspace_member", "registration", schema="balancer", type_="foreignkey")
    op.drop_column("registration", "workspace_member_id", schema="balancer")
