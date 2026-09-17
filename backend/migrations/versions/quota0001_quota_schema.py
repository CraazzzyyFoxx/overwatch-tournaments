"""Add the ``quota`` schema and drop ``auth.api_key.limits_json``.

Revision ID: quota0001
Revises: apikeycfg1
Create Date: 2026-09-17 01:00:00.000000

Relational quota policy: plans, their per-scope ceilings, the metered-operation
catalogue and the two override tables (per workspace, per API key). ``NULL`` in
a dimension is load-bearing -- "unlimited" in a plan row, "inherit" in an
override row -- which is why no dimension is ``NOT NULL`` and why the
non-negativity CHECK is written over ``COALESCE``. ``scope`` carries no CHECK on
purpose: a fourth scope must be a data change, not a migration, the same
precedent ``workspace.verification_status`` and ``newcomer_scope`` set.

``limits_json`` goes in the same migration. It was written exactly once, as
``{}`` by ``ApiKeyService.create``, and no RPC, admin surface or backfill ever
set a value, so both readers always fell back to their own hardcoded defaults --
the same trajectory ``config_policy_json`` was on before ``apikeycfg1``. The
tables below are where a real per-key ceiling now lives.

The seed ships with the DDL rather than in a follow-up revision: an empty
``plan_limit`` reads as unlimited, so a gap between the two would be a window
with no quotas at all. The four seeded plans are deliberately **identical** --
each gets the same ``key`` and ``session`` rows, copied from today's hardcoded
``DEFAULT_LIMITS``/``SESSION_LIMITS`` in the balancer's ``api_key_limiter`` --
so this migration changes nothing observable. Differentiating the tiers is an
ops decision, taken later against live numbers, not a schema change.

Three plan slugs mirror ``workspace.verification_status``; the fourth,
``default``, is the one no workspace maps to. It applies to a principal acting
outside any tenant -- a session user polling a job by id -- which would
otherwise resolve no plan at all and so no limit at all.

No ``workspace``-scope rows are seeded either: the tenant-wide budget starts
unlimited, because tightening a shared pool below what its keys already spend
is exactly the kind of change that should be made deliberately and per tenant.
Only ``balancer.job`` is seeded into ``quota.operation``: the remaining
operations land together with their call sites, and an enabled slug nobody
charges would be a lie in the catalogue.

``auth.api_key`` is read on every API-key request, so take ``lock_timeout``
rather than queueing readers behind an ACCESS EXCLUSIVE wait; DROP COLUMN and
ADD COLUMN (nullable, no default) are metadata-only, so a failed attempt is a
free retry of the migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "quota0001"
down_revision: str | Sequence[str] | None = "apikeycfg1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quota")

    op.create_table(
        "plan",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="quota",
    )
    op.create_index(op.f("ix_quota_plan_slug"), "plan", ["slug"], unique=True, schema="quota")

    op.create_table(
        "plan_limit",
        sa.Column("plan_id", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("requests_per_minute", sa.Integer(), nullable=True),
        sa.Column("heavy_per_day", sa.Integer(), nullable=True),
        sa.Column("concurrent_heavy", sa.Integer(), nullable=True),
        sa.Column("max_upload_bytes", sa.BigInteger(), nullable=True),
        sa.Column("max_items_per_request", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "COALESCE(requests_per_minute, 0) >= 0 AND COALESCE(heavy_per_day, 0) >= 0 AND "
            "COALESCE(concurrent_heavy, 0) >= 0 AND COALESCE(max_upload_bytes, 0) >= 0 AND "
            "COALESCE(max_items_per_request, 0) >= 0",
            name="ck_quota_plan_limit_nonneg",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["quota.plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "scope"),
        schema="quota",
    )

    op.create_table(
        "operation",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("cost", sa.Integer(), server_default="1", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint("cost >= 0", name="ck_quota_operation_cost"),
        sa.PrimaryKeyConstraint("id"),
        schema="quota",
    )
    op.create_index(op.f("ix_quota_operation_slug"), "operation", ["slug"], unique=True, schema="quota")

    op.create_table(
        "workspace_limit",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("requests_per_minute", sa.Integer(), nullable=True),
        sa.Column("heavy_per_day", sa.Integer(), nullable=True),
        sa.Column("concurrent_heavy", sa.Integer(), nullable=True),
        sa.Column("max_upload_bytes", sa.BigInteger(), nullable=True),
        sa.Column("max_items_per_request", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("workspace_id", "scope"),
        schema="quota",
    )

    op.create_table(
        "api_key_limit",
        sa.Column("api_key_id", sa.BigInteger(), nullable=False),
        sa.Column("requests_per_minute", sa.Integer(), nullable=True),
        sa.Column("heavy_per_day", sa.Integer(), nullable=True),
        sa.Column("concurrent_heavy", sa.Integer(), nullable=True),
        sa.Column("max_upload_bytes", sa.BigInteger(), nullable=True),
        sa.Column("max_items_per_request", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["api_key_id"], ["auth.api_key.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["auth.user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("api_key_id"),
        schema="quota",
    )

    op.add_column("workspace", sa.Column("quota_plan_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_workspace_quota_plan_id",
        "workspace",
        "plan",
        ["quota_plan_id"],
        ["id"],
        referent_schema="quota",
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_workspace_quota_plan_id"), "workspace", ["quota_plan_id"], unique=False)

    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.drop_column("api_key", "limits_json", schema="auth")

    op.execute(
        """
        INSERT INTO quota.plan (slug, title) VALUES
            ('unverified', 'Unverified workspace'),
            ('verified',   'Verified workspace'),
            ('trusted',    'Trusted workspace'),
            ('default',    'No workspace in the request')
        """
    )
    op.execute(
        """
        INSERT INTO quota.plan_limit (
            plan_id, scope, requests_per_minute, heavy_per_day,
            concurrent_heavy, max_upload_bytes, max_items_per_request
        )
        SELECT p.id, s.scope, s.requests_per_minute, s.heavy_per_day,
               s.concurrent_heavy, s.max_upload_bytes, s.max_items_per_request
        FROM quota.plan AS p
        CROSS JOIN (VALUES
            ('key',      60, 100, 2, 10485760::bigint,  500),
            ('session', 120, 500, 3, 26214400::bigint, 1000)
        ) AS s(scope, requests_per_minute, heavy_per_day,
               concurrent_heavy, max_upload_bytes, max_items_per_request)
        WHERE p.slug IN ('unverified', 'verified', 'trusted', 'default')
        """
    )
    op.execute(
        """
        INSERT INTO quota.operation (slug, cost, enabled) VALUES
            ('balancer.job', 1, true)
        """
    )


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    op.add_column(
        "api_key",
        sa.Column("limits_json", sa.JSON(), server_default="{}", nullable=False),
        schema="auth",
    )

    op.drop_index(op.f("ix_workspace_quota_plan_id"), table_name="workspace")
    op.drop_constraint("fk_workspace_quota_plan_id", "workspace", type_="foreignkey")
    op.drop_column("workspace", "quota_plan_id")

    op.drop_table("api_key_limit", schema="quota")
    op.drop_table("workspace_limit", schema="quota")
    op.drop_index(op.f("ix_quota_operation_slug"), table_name="operation", schema="quota")
    op.drop_table("operation", schema="quota")
    op.drop_table("plan_limit", schema="quota")
    op.drop_index(op.f("ix_quota_plan_slug"), table_name="plan", schema="quota")
    op.drop_table("plan", schema="quota")
    op.execute("DROP SCHEMA IF EXISTS quota")
