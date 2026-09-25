"""Clamp every stored ``max_result_variants`` to the new ceiling of 100.

Revision ID: varcap01
Revises: ffa0001

``AlgorithmConfig.max_result_variants`` (and the mix preferences built on it)
now accepts at most 100, down from 500. A stored config above that would fail
validation the next time it is read or run -- a host's mixes would stop
balancing and their preferences page would stop loading -- so the values are
lowered once, here. Old code accepts 100 just as well, so this is safe to run
while the previous release is still serving.

Stored mix solver documents are NOT touched: they are upgraded on read
(``result_serializer.as_lobby_document``), because the previous release cannot
read the new form and keeps serving until this migration has finished.

``downgrade()`` is a no-op: the previous ceiling accepts every clamped value,
and the original numbers are not recoverable.
"""

from collections.abc import Sequence

from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "varcap01"
down_revision: str | Sequence[str] | None = "ffa0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CEILING = 100

# (table, column type) -- the JSON columns round-trip through jsonb for jsonb_set.
_CONFIG_TABLES = (
    ("balancer.tournament_config", "json"),
    ("balancer.workspace_config", "json"),
    ("balancer.balance", "json"),
    ("balancer.user_config", "jsonb"),
)


def upgrade() -> None:
    for table, column_type in _CONFIG_TABLES:
        op.execute(
            f"""
            UPDATE {table}
            SET config_json = jsonb_set(config_json::jsonb, '{{max_result_variants}}', '{_CEILING}'::jsonb)::{column_type}
            WHERE jsonb_typeof(config_json::jsonb -> 'max_result_variants') = 'number'
              AND (config_json::jsonb ->> 'max_result_variants')::numeric > {_CEILING}
            """
        )


def downgrade() -> None:
    pass
