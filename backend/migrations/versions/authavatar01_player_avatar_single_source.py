"""Avatar single source: ``players.user.avatar_url``; ``auth."user".avatar_url`` is retired.

Revision ID: authavatar01
Revises: pbentry01
Create Date: 2026-10-26 20:00:00.000000

An account's avatar lived twice: the auth column (header, My Account, chat, workspace members) and the linked
player's column (public profile, admin dialog). Every upload wrote both, but an OAuth login synced the provider's
avatar onto the account only, and an account without a player had nowhere to mirror to, so the two drifted. Every
reader now shows the linked player's avatar, and the ORM no longer maps the auth column.

Before the switch, nothing shown today is lost:

* an account with an avatar but no player gets one, named like ``UserRepository.ensure_for_auth_user`` would
  (the username; ``username (id)`` when that name is taken);
* a linked player without an avatar takes the account's.

Where both are set the player's wins -- it is what the public profile already shows.

The column itself is NOT dropped here. Migrations run while the old containers still serve
(``ops/deploy/remote-deploy.sh``), and the old identity-service selects it on every token validation, so dropping it
in the same release would fail sign-ins until the new containers are up. The next release drops it.

Downgrade copies each linked player's avatar back into the still-present column, so rolled-back code shows what this
release's code wrote; the players provisioned here stay.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "authavatar01"
down_revision: str | Sequence[str] | None = "pbentry01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO players."user" (name, auth_user_id, avatar_url)
        SELECT CASE
                 WHEN EXISTS (SELECT 1 FROM players."user" taken WHERE taken.name = a.username)
                   THEN a.username || ' (' || a.id || ')'
                 ELSE a.username
               END,
               a.id,
               a.avatar_url
        FROM auth."user" a
        WHERE a.avatar_url IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM players."user" p WHERE p.auth_user_id = a.id)
        """
    )
    op.execute(
        """
        UPDATE players."user" p
        SET avatar_url = a.avatar_url
        FROM auth."user" a
        WHERE p.auth_user_id = a.id
          AND p.avatar_url IS NULL
          AND a.avatar_url IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE auth."user" a
        SET avatar_url = p.avatar_url
        FROM players."user" p
        WHERE p.auth_user_id = a.id
        """
    )
