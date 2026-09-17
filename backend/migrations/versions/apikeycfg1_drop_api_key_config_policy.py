"""Drop ``auth.api_key.config_policy_json``.

Revision ID: apikeycfg1
Revises: inpslot01
Create Date: 2026-09-17 00:00:00.000000

The column fed a balancer-side allowlist that rejected solver config fields an
API key was not permitted to set. There are no separate limits on the arguments
an API client may pass: the request is validated by ``ConfigOverrides`` /
``AlgorithmConfig`` exactly like a browser request, and compute stays bounded by
the per-key job quotas in ``limits_json`` plus the inline transport's own
``SYNC_TIME_LIMIT_MS`` clamp. With the enforcement gone the column is dead --
and it was never writable anyway: ``ApiKeyService.create`` always stored ``{}``
and no endpoint ever updated it, so every row holds the default.

``auth.api_key`` is read on every API-key request, so take ``lock_timeout``
rather than queueing readers behind an ACCESS EXCLUSIVE wait; DROP COLUMN is
metadata-only, so a failed attempt is a free retry of the migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "apikeycfg1"
down_revision: str | Sequence[str] | None = "inpslot01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.drop_column("api_key", "config_policy_json", schema="auth")


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.add_column(
        "api_key",
        sa.Column("config_policy_json", sa.JSON(), server_default="{}", nullable=False),
        schema="auth",
    )
