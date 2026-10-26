# One writer per identity table, one avatar: release note

Every service still creates players, attaches handles and grants workspace roles inside its own transaction, but now
only through the module that owns the rules for that table (`backend/ARCHITECTURE.md`, "Cross-service data access"):

| Table | Writer module |
| --- | --- |
| `players.user` (row creation, `auth_user_id` link) | `UserRepository.create_player` / `ensure_for_auth_user` / `link_auth_user` |
| `players.social_account`, `…_visibility` | `SocialIdentityService` (unchanged) |
| `auth.*` rows | identity-service (unchanged) |
| `auth.user_roles` workspace grants | `shared/rbac/bootstrap.py` (unchanged) |

`backend/tests/test_identity_write_ownership.py` fails on a `models.User(...)` / social-account / account-row
construction, a `.auth_user_id =` assignment or a `user_roles` write outside those modules.

## Behaviour changes

- **A taken player name no longer fails.** Registration (`ensure_player_identity`) and scrim captains used the raw
  handle / username and hit the unique index on a collision. Every new player now gets the same suffix: ` (<auth id>)`
  when it is born linked, else ` (<provider>:<hash8>)` of the handle it is named after.
- **Mix roster virtual players** take that suffix too: `Name (riot:1a2b3c4d)` instead of `Name (2)`, the same name
  match-log ingest gives the same handle.
- **One avatar: `players.user.avatar_url`.** The header, My Account, chat and the workspace member/owner payloads
  read the linked player's avatar, the one the public profile already showed. Where the two had drifted (an OAuth
  login rewrote only the account's), the header now shows the profile's.
- **OAuth sign-in no longer overwrites a chosen avatar.** The provider's avatar fills the player's only while it is
  empty or still that provider's previous one; a custom upload stays.
- **Self-service avatar upload** provisions the account's player first, so an account created before sign-up
  provisioning existed no longer uploads into nothing.

Wire shapes are unchanged: every `avatar_url` field keeps its name, only its source moved.

## Migration and deploy

One migration after `pbentry01`: **`authavatar01`**.

1. An account with an avatar and no player gets one, named like `ensure_for_auth_user` would (`username`, or
   `username (id)` when taken).
2. A linked player without an avatar takes the account's; where both are set the player's wins.

The column `auth."user".avatar_url` stays in the database: migrations run while the old containers still serve
(`ops/deploy/remote-deploy.sh`), and the old identity-service selects it on every token validation. The ORM no longer
maps it. **The next release drops it** with a migration of its own (`ALTER TABLE auth."user" DROP COLUMN
avatar_url`).

Deploy from one SHA: the migration, then every backend service (identity, app, tournament, balancer, stats).

Downgrade copies each linked player's avatar back into the account column, so rolled-back code shows what this
release wrote. The players the upgrade provisioned stay.
