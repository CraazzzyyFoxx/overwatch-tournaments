"""Roster edits, organizer admission, lock, eligibility knobs, team subscription.

Revision ID: regteam0004
Revises: matchslim01
Create Date: 2026-09-10 00:00:00.000000

Pure expand. Every column is nullable or server-defaulted, so existing rows
mean "the old contract" without a backfill:

* ``subscription_scope='player'`` keeps the per-player admission gate;
* ``admission='pending'`` is the un-decided organizer axis, independent of
  occupancy ``status`` (forming/complete);
* ``is_team_manager=false`` is "captain only", the privilege that existed before
  this revision;
* team eligibility columns default off / NULL so live events do not grow new
  refusals on deploy day.

``down_revision`` is the current Alembic head, not ``regteam0003``. This repo
keeps one chain; pointing at the previous team-registration revision would
fork the graph.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "regteam0004"
down_revision: str | Sequence[str] | None = "matchslim01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registration_form",
        sa.Column("subscription_scope", sa.String(length=16), nullable=False, server_default="player"),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_rank_min", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_rank_max", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_max_rank_spread", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_unique_identity", sa.Boolean(), nullable=False, server_default="false"),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_require_discord_guild", sa.Boolean(), nullable=False, server_default="false"),
        schema="balancer",
    )

    op.add_column(
        "registration",
        sa.Column("is_team_manager", sa.Boolean(), nullable=False, server_default="false"),
        schema="balancer",
    )

    op.add_column(
        "registration_team",
        sa.Column("admission", sa.String(length=16), nullable=False, server_default="pending"),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("organizer_notes", sa.Text(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("roster_locked_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("roster_locked_by", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_covered_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_covered_by", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_provider", sa.String(length=32), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_tier_rank", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_registration_team_roster_locked_by",
        "registration_team",
        "user",
        ["roster_locked_by"],
        ["id"],
        source_schema="balancer",
        referent_schema="auth",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_registration_team_subscription_covered_by",
        "registration_team",
        "user",
        ["subscription_covered_by"],
        ["id"],
        source_schema="balancer",
        referent_schema="auth",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_registration_team_subscription_covered_by",
        "registration_team",
        schema="balancer",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_registration_team_roster_locked_by",
        "registration_team",
        schema="balancer",
        type_="foreignkey",
    )
    op.drop_column("registration_team", "subscription_expires_at", schema="balancer")
    op.drop_column("registration_team", "subscription_tier_rank", schema="balancer")
    op.drop_column("registration_team", "subscription_provider", schema="balancer")
    op.drop_column("registration_team", "subscription_covered_by", schema="balancer")
    op.drop_column("registration_team", "subscription_covered_at", schema="balancer")
    op.drop_column("registration_team", "roster_locked_by", schema="balancer")
    op.drop_column("registration_team", "roster_locked_at", schema="balancer")
    op.drop_column("registration_team", "organizer_notes", schema="balancer")
    op.drop_column("registration_team", "rejection_reason", schema="balancer")
    op.drop_column("registration_team", "admission", schema="balancer")
    op.drop_column("registration", "is_team_manager", schema="balancer")
    op.drop_column("registration_form", "team_require_discord_guild", schema="balancer")
    op.drop_column("registration_form", "team_unique_identity", schema="balancer")
    op.drop_column("registration_form", "team_max_rank_spread", schema="balancer")
    op.drop_column("registration_form", "team_rank_max", schema="balancer")
    op.drop_column("registration_form", "team_rank_min", schema="balancer")
    op.drop_column("registration_form", "subscription_scope", schema="balancer")
