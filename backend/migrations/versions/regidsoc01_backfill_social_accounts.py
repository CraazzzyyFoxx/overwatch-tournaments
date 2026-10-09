"""Every registration identity lands on the player's profile.

Revision ID: regidsoc01
Revises: regident01
Create Date: 2026-10-09 00:00:00.000000

From now on a registration's handles are written straight into
``players.social_account`` as they are answered (decision 7 of the unified
registration identities design). Handles given BEFORE that -- every row
``regident01`` moved out of ``battle_tag``/``smurf_tags_json`` included -- never
reached a profile, so this revision replays them once.

Mirrors ``SocialIdentityService.upsert`` exactly, in SQL:

* one account per ``(player, provider, normalized handle)``; an existing one is
  left untouched (``ON CONFLICT ... DO NOTHING``), never re-pointed or renamed;
* ``is_verified`` false -- a handle typed into a form proves nothing;
* ``is_primary`` only for the first account a player gets for a provider, and
  only when the profile has none for it yet. "First" is the earliest
  registration, then the lowest ``position``, so re-running picks the same row;
* a global visibility row (``workspace_id IS NULL``) for each account actually
  inserted, the same seeding ``upsert(ensure_global_visibility=True)`` does.

Registrations with no ``workspace_member`` have no player to write to, and
soft-deleted ones are skipped: a withdrawn sign-up should not add identities to
a profile.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "regidsoc01"
down_revision: str | Sequence[str] | None = "regident01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL = sa.text(
    """
    WITH candidate AS (
        SELECT DISTINCT ON (wm.player_id, i.provider, i.handle_normalized)
               wm.player_id AS user_id,
               i.provider,
               i.handle,
               i.handle_normalized,
               r.id AS registration_id,
               i.position
        FROM balancer.registration_identity AS i
        JOIN balancer.registration AS r ON r.id = i.registration_id
        JOIN workspace_member AS wm ON wm.id = r.workspace_member_id
        WHERE r.deleted_at IS NULL
        ORDER BY wm.player_id, i.provider, i.handle_normalized, r.id, i.position
    ),
    ranked AS (
        SELECT c.*,
               row_number() OVER (
                   PARTITION BY c.user_id, c.provider ORDER BY c.registration_id, c.position
               ) AS rank_in_provider
        FROM candidate AS c
    ),
    inserted AS (
        INSERT INTO players.social_account
            (user_id, provider, username, username_normalized, is_verified, is_primary)
        SELECT ranked.user_id,
               ranked.provider,
               ranked.handle,
               ranked.handle_normalized,
               false,
               ranked.rank_in_provider = 1
                   AND NOT EXISTS (
                       SELECT 1 FROM players.social_account AS existing
                       WHERE existing.user_id = ranked.user_id AND existing.provider = ranked.provider
                   )
        FROM ranked
        ON CONFLICT ON CONSTRAINT uq_social_account_user_provider_handle DO NOTHING
        RETURNING id
    )
    INSERT INTO players.social_account_visibility (account_id, workspace_id)
    SELECT id, NULL FROM inserted
    """
)


def upgrade() -> None:
    op.get_bind().execute(BACKFILL)


def downgrade() -> None:
    """Deliberately empty.

    An account on a profile is not owned by the registration that revealed it:
    the player may have edited, verified or re-shared it since, and the same
    handle can reach the profile from OAuth, an import or an admin. There is no
    marker separating "inserted here" from "was already there" after the fact,
    so deleting anything on the way down would destroy identities this revision
    never created. Leaving the rows is the inverse that cannot lose data --
    ``regident01`` still removes the registration-side rows.
    """
