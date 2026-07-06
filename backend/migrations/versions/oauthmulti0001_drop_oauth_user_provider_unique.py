"""Allow multiple OAuth connections of the same provider per user.

Drops the ``uq_user_provider`` (auth_user_id, provider) unique constraint so a
user can link more than one account of the same provider (e.g. two battle.net),
each verified into its own ``social_account``. ``uq_provider_user``
(provider, provider_user_id) stays — an external account still maps to one user.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "oauthmulti0001"
down_revision: str | Sequence[str] | None = "acctdeny0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_user_provider", "oauth_connections", schema="auth", type_="unique")


def downgrade() -> None:
    # Re-adding requires at most one connection per (auth_user_id, provider).
    op.create_unique_constraint("uq_user_provider", "oauth_connections", ["auth_user_id", "provider"], schema="auth")
