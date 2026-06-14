"""add_built_in_fields_and_additional_roles

Adds:
- balancer.registration_form.built_in_fields_json (toggleable built-in field config)
- balancer.registration.additional_roles_json (secondary roles)

Revision ID: n4i6j8k2l3m4
Revises: m3h5i7j1k2l3
Create Date: 2026-04-10 01:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "n4i6j8k2l3m4"
down_revision: Union[str, None] = "m3h5i7j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "registration_form",
        sa.Column("built_in_fields_json", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "registration",
        sa.Column("additional_roles_json", sa.JSON(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration",
        sa.Column("smurf_tags_json", sa.JSON(), nullable=True),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("registration", "smurf_tags_json", schema="balancer")
    op.drop_column("registration", "additional_roles_json", schema="balancer")
    op.drop_column("registration_form", "built_in_fields_json", schema="balancer")
