"""Drop the legacy player-identity tables, fully superseded by players.social_account.

Completes the social_account decommission (A7): ``players.battle_tag`` /
``players.discord`` / ``players.twitch`` / ``players.external_account`` are no
longer written or read by any service (all identity reads/writes go through
``players.social_account`` since social0001 + the ingestion cutover). No FK
references them (the OW-rank subsystem was repointed in owrank0002).

Downgrade recreates the four tables and backfills them from social_account by
provider (best-effort; ``ON CONFLICT DO NOTHING`` respects the legacy unique
constraints), so the chain is reversible.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "social0002"
down_revision = "owrank0002"
branch_labels = None
depends_on = None

_LEGACY_TABLES = ("battle_tag", "discord", "twitch", "external_account")


def upgrade() -> None:
    for table in _LEGACY_TABLES:
        op.drop_table(table, schema="players")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.create_table(
        "discord",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("name"),
        schema="players",
    )
    op.create_index("ix_players_discord_name", "discord", ["name"], unique=True, schema="players")

    op.create_table(
        "battle_tag",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.Column("battle_tag", sa.String(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("battle_tag"),
        schema="players",
    )
    op.create_index("ix_players_battle_tag_name", "battle_tag", ["name"], schema="players")
    op.create_index("ix_players_battle_tag_battle_tag", "battle_tag", ["battle_tag"], unique=True, schema="players")
    op.create_index(
        "ix_battle_tag_battle_tag_trgm",
        "battle_tag",
        ["battle_tag"],
        schema="players",
        postgresql_using="gin",
        postgresql_ops={"battle_tag": "gin_trgm_ops"},
    )

    op.create_table(
        "twitch",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("name"),
        schema="players",
    )
    op.create_index("ix_players_twitch_name", "twitch", ["name"], unique=True, schema="players")

    op.create_table(
        "external_account",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("url", sa.String(500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "provider", "username", name="uq_external_account"),
        schema="players",
    )
    op.create_index("ix_players_external_account_user_id", "external_account", ["user_id"], schema="players")
    op.create_index("ix_players_external_account_provider", "external_account", ["provider"], schema="players")

    # Best-effort reverse backfill from the unified table (split by provider).
    op.execute(
        """
        INSERT INTO players.battle_tag (user_id, name, tag, battle_tag)
        SELECT user_id, split_part(username, '#', 1), split_part(username, '#', 2), username
        FROM players.social_account WHERE provider = 'battlenet' AND username LIKE '%#%'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO players.discord (user_id, name)
        SELECT user_id, username FROM players.social_account WHERE provider = 'discord'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO players.twitch (user_id, name)
        SELECT user_id, username FROM players.social_account WHERE provider = 'twitch'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO players.external_account (user_id, provider, username, url)
        SELECT user_id, provider, username, url FROM players.social_account
        WHERE provider NOT IN ('battlenet', 'discord', 'twitch')
        ON CONFLICT DO NOTHING
        """
    )
