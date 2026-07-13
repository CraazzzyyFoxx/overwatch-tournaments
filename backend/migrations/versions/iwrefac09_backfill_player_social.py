"""identity refactor: backfill players.user + verified social_account for legacy auth users.

Restores the "every auth user has a linked players.user" invariant for accounts
that predate it. ``iwrefac01`` only backfilled ``players.user.auth_user_id`` from
the PRIMARY ``auth.user_player`` link, and ``ensure_player_for_auth_user`` (the
provision-on-signup guarantee) only fires for NEW signups — so any auth user who
never had a primary player link was left with no player at all. Those users hit
``404 "No linked player profile"`` on ``GET /api/v1/me/social`` (My Account →
Linked accounts), and any OAuth they had linked never became a ``social_account``
because ``_attach_verified_social_account`` no-ops when there is no player.

This one-shot heal, in a single atomic statement:
  1. provisions a bare ``players.user`` (name = username/email) for every
     ``auth.user`` with no linked player;
  2. upserts a VERIFIED ``social_account`` from each of that user's
     ``auth.oauth_connections`` rows (battlenet/discord/twitch — the OAuth-backed
     providers), mirroring ``OAuthService._attach_verified_social_account``;
  3. seeds a global visibility row for each new account (parity with
     ``upsert_social_account(ensure_global_visibility=True)``), so the recovered
     identities show on the public profile exactly as a fresh OAuth link would.

Scope: only auth users who had NO player. Existing-player users already got their
social accounts attached at link time and never 404'd, so they are left untouched.

Idempotent: step 1's ``WHERE pu.id IS NULL`` and step 2's ``ON CONFLICT DO NOTHING``
make a re-run a no-op. Handle normalization matches ``owrank0002`` / social0001
(SQL ``lower()`` ≈ Python ``casefold()`` for the ASCII handles these providers use).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "iwrefac09"
down_revision: str | Sequence[str] | None = "hidden0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# NB raw string: the battletag normalizer passes the POSIX regex `\s*#\s*` through
# to Postgres verbatim (standard_conforming_strings). Matches shared.core.social.
_HEAL = r"""
WITH ins_players AS (
    INSERT INTO players."user" (name, auth_user_id)
    SELECT
        -- Bare display name; reconciled at registration. Disambiguate on the
        -- rare collision with an existing unlinked player of the same name.
        -- ponytail: conditional suffix; a double-collision aborts the (single,
        -- transactional) migration cleanly rather than corrupting — fix by hand.
        CASE
            WHEN EXISTS (
                SELECT 1 FROM players."user" p2
                WHERE p2.name = COALESCE(au.username, au.email, 'user_' || au.id)
            )
            THEN COALESCE(au.username, au.email, 'user_' || au.id) || ' [' || au.id || ']'
            ELSE COALESCE(au.username, au.email, 'user_' || au.id)
        END,
        au.id
    FROM auth."user" au
    LEFT JOIN players."user" pu ON pu.auth_user_id = au.id
    WHERE pu.id IS NULL
    RETURNING id AS user_id, auth_user_id
),
conns AS (
    SELECT
        ip.user_id,
        oc.id AS conn_id,
        oc.provider,
        oc.provider_user_id,
        CASE
            WHEN oc.provider = 'battlenet'
            THEN COALESCE(oc.provider_data->>'battletag', oc.provider_data->>'battle_tag', oc.username)
            ELSE oc.username
        END AS handle
    FROM auth.oauth_connections oc
    JOIN ins_players ip ON ip.auth_user_id = oc.auth_user_id
    WHERE oc.provider IN ('battlenet', 'discord', 'twitch')
),
ins_social AS (
    INSERT INTO players.social_account
        (user_id, provider, username, username_normalized, provider_user_id, is_verified, is_primary)
    SELECT
        c.user_id,
        c.provider,
        c.handle,
        CASE
            WHEN c.provider = 'battlenet'
            THEN lower(replace(regexp_replace(btrim(c.handle), '\s*#\s*', '#', 'g'), ' ', ''))
            ELSE lower(btrim(c.handle))
        END,
        c.provider_user_id,
        TRUE,
        -- First account per (player, provider) is primary — mirrors
        -- upsert_social_account's is_first rule.
        (row_number() OVER (PARTITION BY c.user_id, c.provider ORDER BY c.conn_id) = 1)
    FROM conns c
    ON CONFLICT DO NOTHING
    RETURNING id AS account_id
)
INSERT INTO players.social_account_visibility (account_id, workspace_id)
SELECT account_id, NULL FROM ins_social;
"""


def upgrade() -> None:
    op.execute(_HEAL)


def downgrade() -> None:
    # Irreversible data heal: deleting the provisioned players / recovered social
    # accounts could destroy identity that has since been used (registrations,
    # rank telemetry keyed on social_account). Leave the healed rows in place.
    pass
