"""add players.social_account (+ visibility) and backfill from legacy identity tables

Part A / Phase A1: introduce the unified ``players.social_account`` table (and
``players.social_account_visibility``) that consolidates the legacy
``battle_tag`` / ``discord`` / ``twitch`` / ``external_account`` tables. The
legacy tables are LEFT IN PLACE here (dropped in a later decommission migration);
this migration only creates the new tables and backfills them so old and new
read paths can run side by side.

Backfill:
  * one ``social_account`` row per legacy identity row (provider-mapped,
    ``username_normalized`` canonicalized like ``shared.core.social``);
  * ``is_primary`` = oldest row per (user, provider);
  * a global (``workspace_id IS NULL``) visibility row per account, preserving
    the current "shown on profile" behaviour;
  * best-effort ``is_verified`` + ``provider_user_id`` for accounts whose
    (provider, normalized handle) matches an existing ``auth.oauth_connections``
    row on a linked player.

Revision ID: social0001
Revises: draft0004
Create Date: 2026-06-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "social0001"
down_revision: str | Sequence[str] | None = "draft0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Canonicalize a handle inside SQL, mirroring shared.core.social.normalize_social_handle:
# everything is lower-cased; BattleTags additionally have whitespace / '#' spacing normalized.
_NORMALIZE_BATTLETAG = r"lower(replace(regexp_replace(btrim({col}), '\s*#\s*', '#', 'g'), ' ', ''))"


def upgrade() -> None:
    op.create_table(
        "social_account",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("username_normalized", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("provider_user_id", sa.String(length=255), nullable=True),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["players.user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "username_normalized",
            name="uq_social_account_user_provider_handle",
        ),
        schema="players",
    )
    op.create_index("ix_social_account_user_id", "social_account", ["user_id"], schema="players")
    op.create_index("ix_social_account_provider", "social_account", ["provider"], schema="players")
    op.create_index(
        "ix_social_account_username_normalized", "social_account", ["username_normalized"], schema="players"
    )
    op.create_index(
        "ix_social_account_provider_user_id", "social_account", ["provider_user_id"], schema="players"
    )
    op.create_index(
        "uq_social_account_provider_subject",
        "social_account",
        ["provider", "provider_user_id"],
        unique=True,
        schema="players",
        postgresql_where=sa.text("provider_user_id IS NOT NULL"),
    )

    op.create_table(
        "social_account_visibility",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["players.social_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        schema="players",
    )
    op.create_index(
        "ix_social_account_visibility_account_id", "social_account_visibility", ["account_id"], schema="players"
    )
    op.create_index(
        "ix_social_account_visibility_workspace_id",
        "social_account_visibility",
        ["workspace_id"],
        schema="players",
    )
    op.create_index(
        "uq_social_visibility_global",
        "social_account_visibility",
        ["account_id"],
        unique=True,
        schema="players",
        postgresql_where=sa.text("workspace_id IS NULL"),
    )
    op.create_index(
        "uq_social_visibility_workspace",
        "social_account_visibility",
        ["account_id", "workspace_id"],
        unique=True,
        schema="players",
        postgresql_where=sa.text("workspace_id IS NOT NULL"),
    )

    bt_norm = _NORMALIZE_BATTLETAG.format(col="bt.battle_tag")

    # --- Backfill identities (one row per legacy identity) -------------------
    op.execute(
        f"""
        INSERT INTO players.social_account
            (user_id, provider, username, username_normalized, url, provider_user_id,
             is_verified, is_primary, created_at)
        SELECT bt.user_id, 'battlenet', bt.battle_tag, {bt_norm}, NULL, NULL, false, false, bt.created_at
        FROM players.battle_tag bt
        ON CONFLICT ON CONSTRAINT uq_social_account_user_provider_handle DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO players.social_account
            (user_id, provider, username, username_normalized, url, provider_user_id,
             is_verified, is_primary, created_at)
        SELECT d.user_id, 'discord', d.name, lower(btrim(d.name)), NULL, NULL, false, false, d.created_at
        FROM players.discord d
        ON CONFLICT ON CONSTRAINT uq_social_account_user_provider_handle DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO players.social_account
            (user_id, provider, username, username_normalized, url, provider_user_id,
             is_verified, is_primary, created_at)
        SELECT t.user_id, 'twitch', t.name, lower(btrim(t.name)), NULL, NULL, false, false, t.created_at
        FROM players.twitch t
        ON CONFLICT ON CONSTRAINT uq_social_account_user_provider_handle DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO players.social_account
            (user_id, provider, username, username_normalized, url, provider_user_id,
             is_verified, is_primary, created_at)
        SELECT e.user_id, e.provider, e.username, lower(btrim(e.username)), e.url, NULL, false, false, e.created_at
        FROM players.external_account e
        ON CONFLICT ON CONSTRAINT uq_social_account_user_provider_handle DO NOTHING
        """
    )

    # --- is_primary = oldest row per (user, provider) ------------------------
    op.execute(
        """
        UPDATE players.social_account sa
        SET is_primary = true
        FROM (
            SELECT DISTINCT ON (user_id, provider) id
            FROM players.social_account
            ORDER BY user_id, provider, created_at, id
        ) first
        WHERE sa.id = first.id
        """
    )

    # --- global visibility row per account (preserve "shown on profile") -----
    op.execute(
        """
        INSERT INTO players.social_account_visibility (account_id, workspace_id, created_at)
        SELECT id, NULL, now() FROM players.social_account
        """
    )

    # --- best-effort verified backfill from existing OAuth connections -------
    op.execute(
        r"""
        UPDATE players.social_account sa
        SET provider_user_id = oc.provider_user_id, is_verified = true
        FROM auth.oauth_connections oc
        JOIN auth.user_player up ON up.auth_user_id = oc.auth_user_id
        WHERE sa.user_id = up.player_id
          AND sa.provider = oc.provider
          AND oc.provider_user_id IS NOT NULL
          AND sa.username_normalized = (
              CASE WHEN oc.provider = 'battlenet'
                   THEN lower(replace(regexp_replace(btrim(oc.username), '\s*#\s*', '#', 'g'), ' ', ''))
                   ELSE lower(btrim(oc.username))
              END
          )
        """
    )


def downgrade() -> None:
    op.drop_table("social_account_visibility", schema="players")
    op.drop_table("social_account", schema="players")
