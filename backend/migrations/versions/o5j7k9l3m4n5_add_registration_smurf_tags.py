"""add_registration_smurf_tags

Adds balancer.registration.smurf_tags_json column.

Revision ID: o5j7k9l3m4n5
Revises: n4i6j8k2l3m4
Create Date: 2026-04-10 02:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "o5j7k9l3m4n5"
down_revision: Union[str, None] = "n4i6j8k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "registration",
        sa.Column("smurf_tags_json", sa.JSON(), nullable=True),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("registration", "smurf_tags_json", schema="balancer")
