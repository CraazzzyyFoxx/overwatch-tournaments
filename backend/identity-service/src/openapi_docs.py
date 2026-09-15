"""Human-readable docs (summary + description) for identity-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    # ── token / service validation ─────────────────────────────────────────
    "rpc.identity.validate_token": {
        "summary": "Validate token",
        # 401, not 403: every not-authenticated path in validate_token raises
        # HTTP_401_UNAUTHORIZED (token_validation.py), and
        # the gateway pins that mapping in TestValidate_ErrorEnvelopeMapsStatus.
        # This line said 403 and the committed manifest said 401, which is what
        # had the OpenAPI drift gate — and so all of Lint Backend — red on master.
        "description": "Permission: public; no caller authentication — the submitted token is itself the credential being introspected. Validates a bearer access token or API key and returns the RBAC token payload (user, permissions); 401 if not authenticated.",
    },
    "rpc.identity.validate_service_token": {
        "summary": "Validate service token",
        "description": "Permission: public; no caller authentication — the submitted service token is itself the credential being introspected. Validates a service JWT and returns the service token payload; 401 if the service token is missing or invalid.",
    },
    "rpc.identity.service_token": {
        "summary": "Issue service token",
        "description": "Permission: public; authenticated by the service `client_id`/`client_secret` in the body, not by any user credential. Exchanges service client credentials (client_id + client_secret) for a signed service access token.",
    },
    "rpc.identity.invalidate_session": {
        "summary": "Invalidate cached permissions for a user",
        "description": (
            "Permission: a valid service token (any scope); no user credential and no per-scope check. "
            "Drops the cached RBAC entry for the given user_id, so "
            "their next request re-resolves roles and permissions from the database instead of waiting out "
            "the cache TTL; returns 204 No Content. Despite the endpoint name it does NOT revoke tokens or "
            "end sessions — an issued access token stays valid until it expires. Use the session endpoints "
            "for revocation."
        ),
    },
    # ── auth core ──────────────────────────────────────────────────────────
    "rpc.identity.register": {
        "summary": "Register user",
        "description": "Permission: public; no authentication required. Creates a new auth user from email/password registration and returns the created user (201).",
    },
    "rpc.identity.login": {
        "summary": "Login",
        "description": "Permission: public; no authentication required — the email/password pair is the credential. Authenticates email + password and returns an access+refresh token, recording the session with the forwarded user-agent and IP.",
    },
    "rpc.identity.refresh": {
        "summary": "Refresh token",
        "description": "Permission: public; no authentication required — the supplied refresh token is the credential. Rotates a valid refresh token and returns a fresh access+refresh token pair.",
    },
    "rpc.identity.logout": {
        "summary": "Logout",
        "description": "Permission: authenticated (active) user; self-service — 403 when the refresh token belongs to another account. Revokes the supplied refresh token for the bearer-authenticated user; returns 204 No Content.",
    },
    "rpc.identity.logout_all": {
        "summary": "Logout all sessions",
        "description": "Permission: authenticated (active) user; self-service — only the caller's own sessions. Revokes every refresh-token session for the active user; returns 204 No Content.",
    },
    "rpc.identity.list_sessions": {
        "summary": "List sessions",
        "description": "Permission: authenticated (active) user; self-service — only the caller's own sessions. Returns all active refresh-token sessions for the bearer-authenticated user.",
    },
    "rpc.identity.revoke_session": {
        "summary": "Revoke session",
        "description": "Permission: authenticated (active) user; self-service — the session is resolved under the caller's own id. Revokes one of the active user's sessions by session id; returns 204 No Content (400 on an invalid session id).",
    },
    "rpc.identity.get_me": {
        "summary": "Get current user",
        "description": "Permission: authenticated (active) user, session bearer or API key; self-service. Returns the profile of the bearer-authenticated user.",
    },
    "rpc.identity.update_me": {
        "summary": "Update current user",
        "description": "Permission: authenticated (active) user, session bearer only; self-service. Applies a partial profile update to the active user and returns the updated user.",
    },
    "rpc.identity.delete_me": {
        "summary": "Delete current account",
        "description": "Permission: authenticated (active) user; self-service — the caller's own account only. Permanently deletes the active user's own account (sessions, OAuth connections, API keys, role grants) and returns 204. Historical data is preserved: the linked player identity survives with its account link nulled, so tournaments, matches, statistics and registrations are untouched. 400 for a superuser account.",
    },
    "rpc.identity.set_password": {
        "summary": "Set password",
        "description": "Permission: authenticated (active) user; self-service — the current password must be supplied when one is already set. Sets or changes the active user's password; returns 204 No Content.",
    },
    "rpc.identity.me.avatar_set": {
        "summary": "Set avatar",
        "description": "Permission: authenticated (active) user; self-service, and refused when the caller carries an `account.avatar` deny. Uploads the active user's avatar image to S3 (base64 multipart body) and returns the updated user.",
    },
    "rpc.identity.me.avatar_delete": {
        "summary": "Delete avatar",
        "description": "Permission: authenticated (active) user; self-service, and refused when the caller carries an `account.avatar` deny. Removes the active user's avatar from S3 and returns the updated user.",
    },
    # ── oauth ──────────────────────────────────────────────────────────────
    "rpc.identity.oauth_providers": {
        "summary": "List OAuth providers",
        "description": "Permission: public; no authentication required. Returns the configured OAuth providers and their availability.",
    },
    "rpc.identity.oauth_url": {
        "summary": "Get OAuth URL",
        "description": "Permission: public; no authentication required. Returns the provider's authorization redirect URL to start the OAuth flow; 400 if the provider is missing.",
    },
    "rpc.identity.oauth_callback": {
        "summary": "OAuth callback",
        "description": "Permission: public; no authentication required — the provider's code+state is the credential. Exchanges the provider's code+state for an access+refresh token, logging in or creating the user; 422 if provider/code/state are missing.",
    },
    "rpc.identity.sso_exchange": {
        "summary": "Redeem SSO ticket",
        "description": (
            "Permission: public; no bearer authentication required. Redemption of the single-use, short-lived Redis ticket minted by an OAuth"
            " callback on a workspace custom domain, returning the session access+refresh token pair. It"
            " exists so the callback can hand a session back to the tenant origin without ever putting"
            " tokens in a redirect URL. Called by the custom domain's own frontend route, never by the"
            " apex, and the ticket plus the owt_xdomain_guard cookie value together are the credential."
            " The ticket is burned before the guard is checked, so replay -- like an expired, unknown or"
            " guard-mismatched ticket -- fails closed with an indistinguishable 400."
        ),
    },
    "rpc.identity.oauth_link": {
        "summary": "Link OAuth provider",
        "description": "Permission: public entry point; a bearer is optional and resolved best-effort — a platform-host link needs a resolvable active user, a custom-domain link needs none. Exchanges the provider code+state and links the connection to the active user (platform apex/subdomain), or -- for a workspace custom domain, which has no live session here -- mints a single-use provider-identity ticket (mode='link_ticket') for rpc.identity.link_complete to redeem instead.",
    },
    "rpc.identity.link_complete": {
        "summary": "Complete custom-domain OAuth link",
        "description": "Permission: authenticated (active) user; self-service — the identity attaches to the bearer caller and the owt_xdomain_guard cookie must match. Redeems a pending-link ticket minted by rpc.identity.oauth_link and attaches the provider identity it carries to the bearer-authenticated caller; 400 if the ticket is invalid, expired, or already used.",
    },
    "rpc.identity.oauth_connections": {
        "summary": "List OAuth connections",
        "description": "Permission: authenticated (active) user; self-service. Returns the OAuth provider connections linked to the active user.",
    },
    "rpc.identity.oauth_unlink": {
        "summary": "Unlink OAuth provider",
        "description": "Permission: authenticated (active) user; self-service. Unlinks the named OAuth provider from the active user; returns 204 and refuses to remove the last provider when no password is set.",
    },
    # ── api keys ───────────────────────────────────────────────────────────
    "rpc.identity.list_api_keys": {
        "summary": "List API keys",
        "description": "Permission: workspace `team.create` on the requested workspace, which must be active (a global `team.create` grant or superuser also passes). Returns the active user's API keys for the given workspace_id (422 if workspace_id is missing).",
    },
    "rpc.identity.create_api_key": {
        "summary": "Create API key",
        "description": "Permission: workspace `team.create` on the target workspace, which must be active (a global `team.create` grant or superuser also passes), and the key can only carry scopes the creator already holds there. Creates a workspace-scoped API key for the active user and returns it including the one-time plaintext key (201).",
    },
    "rpc.identity.update_api_key": {
        "summary": "Update API key",
        "description": "Permission: workspace `team.create` on the key's own workspace, which must be active (a global `team.create` grant or superuser also passes), not restricted to the key's owner. Updates the named API key (by id) for the active user and returns the updated record.",
    },
    "rpc.identity.revoke_api_key": {
        "summary": "Revoke API key",
        "description": "Permission: workspace `team.create` on the key's own workspace, which must be active (a global `team.create` grant or superuser also passes), not restricted to the key's owner. Revokes the active user's API key by id; returns 204 No Content.",
    },
    "rpc.identity.api_key.self": {
        "summary": "Describe the calling API key",
        "description": (
            "Permission: an API-key credential; no further grant is checked. "
            "Returns the descriptor -- name, scopes, limits, config policy, expiry -- of the API key "
            "presented on this request, so a scripted client can discover its own authority and budget. "
            "A session bearer gets 403."
        ),
    },
    # ── RBAC: permissions ──────────────────────────────────────────────────
    "rpc.identity.rbac.list_permissions": {
        "summary": "List permissions",
        "description": "Permission: `permission.read` — checked in the workspace when workspace_id is given, globally otherwise. Returns RBAC permissions, optionally filtered by workspace_id.",
    },
    "rpc.identity.rbac.create_permission": {
        "summary": "Create permission",
        "description": "Permission: superuser only. Creates a new RBAC permission and returns it (201).",
    },
    "rpc.identity.rbac.delete_permission": {
        "summary": "Delete permission",
        "description": "Permission: superuser only. Deletes the RBAC permission by id; returns 204 No Content.",
    },
    # ── RBAC: roles ────────────────────────────────────────────────────────
    "rpc.identity.rbac.list_roles": {
        "summary": "List roles",
        "description": "Permission: `role.read` — workspace `role.read` with a global `role.read` fallback when workspace_id is given, global `role.read` otherwise. Returns RBAC roles, optionally filtered by workspace_id.",
    },
    "rpc.identity.rbac.get_role": {
        "summary": "Get role",
        "description": "Permission: `role.read` in the role's own scope, with a global `role.read` fallback for a workspace role. Returns a single role with its permissions by role_id (422 if role_id is missing).",
    },
    "rpc.identity.rbac.create_role": {
        "summary": "Create role",
        "description": "Permission: `role.create` in the new role's own scope — workspace `role.create` for a workspace role (no global fallback), global `role.create` otherwise — and the role may not carry a permission the caller lacks. Creates a new RBAC role and returns it (201).",
    },
    "rpc.identity.rbac.update_role": {
        "summary": "Update role",
        "description": "Permission: `role.update` in the role's own scope (a workspace role needs the workspace grant, no global fallback), and a replaced permission set may not exceed the caller's own permissions. Updates the role by role_id and returns it, invalidating the RBAC cache.",
    },
    "rpc.identity.rbac.delete_role": {
        "summary": "Delete role",
        "description": "Permission: `role.delete` in the role's own scope (a workspace role needs the workspace grant, no global fallback). Deletes the role by role_id; returns 204 No Content.",
    },
    # ── RBAC: auth users ───────────────────────────────────────────────────
    "rpc.identity.rbac.list_auth_users": {
        "summary": "List auth users",
        "description": "Permission: `auth_user.read` — checked in the workspace when workspace_id is given, globally otherwise. Returns auth users filtered by search/role_id/is_active/is_superuser/workspace_id.",
    },
    "rpc.identity.rbac.get_auth_user": {
        "summary": "Get auth user",
        "description": "Permission: global `auth_user.read`. Returns detailed info for a single auth user by user_id (422 if user_id is missing).",
    },
    "rpc.identity.rbac.get_user_roles": {
        "summary": "Get user roles",
        "description": "Permission: global `auth_user.read`. Returns the roles assigned to the given user_id.",
    },
    "rpc.identity.rbac.assign_linked_player": {
        "summary": "Assign linked player",
        "description": "Permission: global `auth_user.update`. Links a game player to the given auth user (admin); returns 204 No Content.",
    },
    "rpc.identity.rbac.remove_linked_player": {
        "summary": "Remove linked player",
        "description": "Permission: global `auth_user.update`. Removes a linked game player from the given auth user (admin) by user_id/player_id; returns 204 No Content.",
    },
    "rpc.identity.rbac.delete_auth_user": {
        "summary": "Delete auth user",
        "description": (
            "Permission: superuser only. Permanently deletes another user's login account: the auth user row and,"
            " by cascade, its roles, permission denies, sessions/refresh tokens, OAuth connections, API"
            " keys and preview-access grants; returns 204. The linked players.user survives with its"
            " auth_user_id nulled, so tournament history, statistics and workspace membership outlive"
            " the login account. 400 when deleting yourself, 404 if the user id is unknown."
        ),
    },
    "rpc.identity.rbac.assign_role": {
        "summary": "Assign role",
        "description": "Permission: `role.update` in the granted role's own scope (a workspace role needs the workspace grant, no global fallback), and the role may not carry a permission the caller lacks. Assigns a role to a user and invalidates the RBAC cache; returns 204 No Content.",
    },
    "rpc.identity.rbac.remove_role": {
        "summary": "Remove role",
        "description": "Permission: `role.update` in the role's own scope (a workspace role needs the workspace grant, no global fallback). Removes a role from a user and invalidates the RBAC cache; returns 204 No Content.",
    },
    # ── RBAC: user permission denies (negative overlay) ────────────────────
    "rpc.identity.rbac.list_user_denies": {
        "summary": "List user permission denies",
        "description": (
            "Permission: global `auth_user.read`. Returns the permissions explicitly denied to the given user, each with the workspace_id it"
            " is scoped to (null = denied everywhere). Denies are a subtractive overlay on the"
            " grant-only role catalog: a deny always beats a grant, which is the whole reason the"
            " overlay exists."
        ),
    },
    "rpc.identity.rbac.add_user_deny": {
        "summary": "Deny a permission to a user",
        "description": (
            "Permission: global `auth_user.update`. Adds a deny for one permission on the given user and returns the user's full deny list."
            " workspace_id scopes the deny to a single workspace; omitted or null denies the permission"
            " everywhere, and a user may hold both at once. The deny takes precedence over every role"
            " grant that would otherwise confer the permission, and the RBAC cache is busted so it"
            " applies to the next request. Idempotent. 400 for a governance"
            " permission (denying the RBAC surface itself could lock administration out), 404 for an"
            " unknown user, permission or workspace."
        ),
    },
    "rpc.identity.rbac.remove_user_deny": {
        "summary": "Remove a user permission deny",
        "description": (
            "Permission: global `auth_user.update`. Lifts one deny and returns the user's remaining deny list, restoring whatever the user's"
            " roles grant. The scope must match exactly: with no workspace_id query param this removes"
            " only the global deny, never a workspace-scoped one for the same permission (and vice"
            " versa). Idempotent, and busts the RBAC cache."
        ),
    },
    # ── RBAC: oauth connections / sessions (admin) ─────────────────────────
    "rpc.identity.rbac.list_oauth_connections": {
        "summary": "List OAuth connections (admin)",
        "description": "Permission: global `auth_user.read`. Returns all OAuth connections (admin), optionally filtered by search and provider.",
    },
    "rpc.identity.rbac.list_sessions": {
        "summary": "List all sessions (admin)",
        "description": "Permission: superuser only. Returns auth-user sessions (admin), filterable by user_id/search and status (active/revoked/expired).",
    },
    "rpc.identity.rbac.delete_oauth_connection": {
        "summary": "Delete OAuth connection",
        "description": "Permission: global `auth_user.update`. Deletes an OAuth connection by connection_id (admin); returns 204 No Content.",
    },
    # ── player linking ─────────────────────────────────────────────────────
    "rpc.identity.player.link": {
        "summary": "Link player",
        "description": "Permission: authenticated (active) user; self-service — the link is made to the caller's own account and only when one of the caller's Discord/Battle.net OAuth identities matches the player's handles. Links a game player to the active user and returns the link details (201).",
    },
    "rpc.identity.player.unlink": {
        "summary": "Unlink player",
        "description": "Permission: authenticated (active) user; self-service — 404 unless the player is linked to the caller. Unlinks a game player from the active user by player_id; returns 204 No Content.",
    },
    "rpc.identity.player.linked": {
        "summary": "List linked players",
        "description": "Permission: authenticated (active) user; self-service — only the caller's own link. Returns all game players linked to the active user.",
    },
    "rpc.identity.player.set_primary": {
        "summary": "Set primary player",
        "description": "Permission: authenticated (active) user; self-service — 404 unless the player is the caller's own link. Marks a linked player as the active user's primary player and returns the updated link.",
    },
}
