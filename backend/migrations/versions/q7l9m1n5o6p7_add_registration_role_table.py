"""add_registration_role_table

Normalizes registration roles into balancer.registration_role table (3NF).
Replaces: primary_role, additional_roles_json, custom_fields._primary_subrole/_additional_subroles

Revision ID: q7l9m1n5o6p7
Revises: p6k8l0m4n5o6
Create Date: 2026-04-10 04:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "q7l9m1n5o6p7"
down_revision: Union[str, None] = "p6k8l0m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registration_role",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registration_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("subrole", sa.String(32), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["registration_id"], ["balancer.registration.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("registration_id", "role", name="uq_balancer_registration_role"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_registration_role_registration_id",
        "registration_role",
        ["registration_id"],
        schema="balancer",
    )

    # Migrate existing data: primary_role -> registration_role
    op.execute("""
        INSERT INTO balancer.registration_role (id, registration_id, role, subrole, is_primary, priority, created_at)
        SELECT
            nextval('balancer.registration_role_id_seq'),
            r.id,
            r.primary_role,
            r.custom_fields_json->>'_primary_subrole',
            true,
            0,
            r.created_at
        FROM balancer.registration r
        WHERE r.primary_role IS NOT NULL
        ON CONFLICT (registration_id, role) DO NOTHING
    """)

    # Migrate additional_roles_json -> registration_role
    op.execute("""
        INSERT INTO balancer.registration_role (id, registration_id, role, subrole, is_primary, priority, created_at)
        SELECT
            nextval('balancer.registration_role_id_seq'),
            r.id,
            ar.value::text,
            (r.custom_fields_json->'_additional_subroles'->>ar.value::text),
            false,
            ar.ordinality,
            r.created_at
        FROM balancer.registration r,
             jsonb_array_elements_text(r.additional_roles_json::jsonb) WITH ORDINALITY AS ar(value, ordinality)
        WHERE r.additional_roles_json IS NOT NULL
          AND jsonb_array_length(r.additional_roles_json::jsonb) > 0
        ON CONFLICT (registration_id, role) DO NOTHING
    """)

    # Drop legacy columns
    op.drop_column("registration", "primary_role", schema="balancer")
    op.drop_column("registration", "additional_roles_json", schema="balancer")

    # Clean up _primary_subrole and _additional_subroles from custom_fields_json
    op.execute("""
        UPDATE balancer.registration
        SET custom_fields_json = (custom_fields_json::jsonb - '_primary_subrole' - '_additional_subroles')::json
        WHERE custom_fields_json IS NOT NULL
          AND (custom_fields_json::jsonb ? '_primary_subrole' OR custom_fields_json::jsonb ? '_additional_subroles')
    """)


def downgrade() -> None:
    op.add_column("registration", sa.Column("primary_role", sa.String(16), nullable=True), schema="balancer")
    op.add_column("registration", sa.Column("additional_roles_json", sa.JSON(), nullable=True), schema="balancer")
    op.drop_table("registration_role", schema="balancer")
