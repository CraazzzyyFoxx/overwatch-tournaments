"""anjobmerge001 — merge anjob0001 with encred001

Both branched off ``mergeheads001``; the analytics-job pipeline and the
encred refactor are independent, so we just merge the heads here. No DDL.

Revision ID: anjobmerge001
Revises: anjob0001, encred001
Create Date: 2026-05-18 16:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union


revision: str = "anjobmerge001"
down_revision: Union[str, Sequence[str], None] = ("anjob0001", "encred001")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
