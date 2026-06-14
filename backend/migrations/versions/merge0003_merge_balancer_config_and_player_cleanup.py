"""merge_balancer_config_and_player_cleanup

Revision ID: merge0003
Revises: cfg20260417, d9e3f5a7b9c1
Create Date: 2026-04-17 22:05:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union


revision: str = "merge0003"
down_revision: Union[str, Sequence[str], None] = ("cfg20260417", "d9e3f5a7b9c1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
