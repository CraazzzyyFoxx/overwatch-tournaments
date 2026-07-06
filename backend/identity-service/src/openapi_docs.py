"""Human-readable docs (summary + description) for identity-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Prose only.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    # ── token / service validation ─────────────────────────────────────────
    "rpc.identity.validate_token": {
        "summary": "Validate token",
        "description": "Validates a bearer access token or API key and returns the RBAC token payload (user, permissions); 403 if not authenticated.",
    },
    "rpc.identity.validate_service_token": {
        "summary": "Validate service token",
        "description": "Validates a service JWT and returns the service token payload; 401 if the service token is missing or invalid.",
    },
    "rpc.identity.service_token": {
        "summary": "Issue service token",
        "description": "Exchanges service client credentials (client_id + client_secret) for a signed service access token.",
    },
    "rpc.identity.invalidate_session": {
        "summary": "Invalidate user session",
        "description": "Service-token-authenticated call that revokes all sessions for the given user_id; returns 204 No Content.",
    },
    # ── auth core ──────────────────────────────────────────────────────────
    "rpc.identity.register": {
        "summary": "Register user",
        "description": "Creates a new auth user from email/password registration and returns the created user (201).",
    },
    "rpc.identity.login": {
        "summary": "Login",
        "description": "Authenticates email + password and returns an access+refresh token, recording the session with the forwarded user-agent and IP.",
    },
    "rpc.identity.refresh": {
        "summary": "Refresh token",
        "description": "Rotates a valid refresh token and returns a fresh access+refresh token pair.",
    },
    "rpc.identity.logout": {
        "summary": "Logout",
        "description": "Revokes the supplied refresh token for the bearer-authenticated user; returns 204 No Content.",
    },
    "rpc.identity.logout_all": {
        "summary": "Logout all sessions",
        "description": "Revokes every refresh-token session for the active user; returns 204 No Content.",
    },
    "rpc.identity.list_sessions": {
        "summary": "List sessions",
        "description": "Returns all active refresh-token sessions for the bearer-authenticated user.",
    },
    "rpc.identity.revoke_session": {
        "summary": "Revoke session",
        "description": "Revokes one of the active user's sessions by session id; returns 204 No Content (400 on an invalid session id).",
    },
    "rpc.identity.get_me": {
        "summary": "Get current user",
        "description": "Returns the profile of the bearer-authenticated user.",
    },
    "rpc.identity.update_me": {
        "summary": "Update current user",
        "description": "Applies a partial profile update to the active user and returns the updated user.",
    },
    "rpc.identity.set_password": {
        "summary": "Set password",
        "description": "Sets or changes the active user's password; returns 204 No Content.",
    },
    "rpc.identity.me.avatar_set": {
        "summary": "Set avatar",
        "description": "Uploads the active user's avatar image to S3 (base64 multipart body) and returns the updated user.",
    },
    "rpc.identity.me.avatar_delete": {
        "summary": "Delete avatar",
        "description": "Removes the active user's avatar from S3 and returns the updated user.",
    },
    # ── oauth ──────────────────────────────────────────────────────────────
    "rpc.identity.oauth_providers": {
        "summary": "List OAuth providers",
        "description": "Returns the configured OAuth providers and their availability.",
    },
    "rpc.identity.oauth_url": {
        "summary": "Get OAuth URL",
        "description": "Returns the provider's authorization redirect URL to start the OAuth flow; 400 if the provider is missing.",
    },
    "rpc.identity.oauth_callback": {
        "summary": "OAuth callback",
        "description": "Exchanges the provider's code+state for an access+refresh token, logging in or creating the user; 422 if provider/code/state are missing.",
    },
    "rpc.identity.oauth_link": {
        "summary": "Link OAuth provider",
        "description": "Exchanges the provider code+state and links the connection to the active user (platform apex/subdomain), or -- for a workspace custom domain, which has no live session here -- mints a single-use provider-identity ticket (mode='link_ticket') for rpc.identity.link_complete to redeem instead.",
    },
    "rpc.identity.link_complete": {
        "summary": "Complete custom-domain OAuth link",
        "description": "Redeems a pending-link ticket minted by rpc.identity.oauth_link and attaches the provider identity it carries to the bearer-authenticated caller; 400 if the ticket is invalid, expired, or already used.",
    },
    "rpc.identity.oauth_connections": {
        "summary": "List OAuth connections",
        "description": "Returns the OAuth provider connections linked to the active user.",
    },
    "rpc.identity.oauth_unlink": {
        "summary": "Unlink OAuth provider",
        "description": "Unlinks the named OAuth provider from the active user; returns 204 and refuses to remove the last provider when no password is set.",
    },
    # ── api keys ───────────────────────────────────────────────────────────
    "rpc.identity.list_api_keys": {
        "summary": "List API keys",
        "description": "Returns the active user's API keys for the given workspace_id (422 if workspace_id is missing).",
    },
    "rpc.identity.create_api_key": {
        "summary": "Create API key",
        "description": "Creates a workspace-scoped API key for the active user and returns it including the one-time plaintext key (201).",
    },
    "rpc.identity.update_api_key": {
        "summary": "Update API key",
        "description": "Updates the named API key (by id) for the active user and returns the updated record.",
    },
    "rpc.identity.revoke_api_key": {
        "summary": "Revoke API key",
        "description": "Revokes the active user's API key by id; returns 204 No Content.",
    },
    # ── RBAC: permissions ──────────────────────────────────────────────────
    "rpc.identity.rbac.list_permissions": {
        "summary": "List permissions",
        "description": "Returns RBAC permissions, optionally filtered by workspace_id, after the active user's permission check.",
    },
    "rpc.identity.rbac.create_permission": {
        "summary": "Create permission",
        "description": "Creates a new RBAC permission and returns it (201), enforcing the active user's permission check.",
    },
    "rpc.identity.rbac.delete_permission": {
        "summary": "Delete permission",
        "description": "Deletes the RBAC permission by id; returns 204 No Content.",
    },
    # ── RBAC: roles ────────────────────────────────────────────────────────
    "rpc.identity.rbac.list_roles": {
        "summary": "List roles",
        "description": "Returns RBAC roles, optionally filtered by workspace_id, after the active user's permission check.",
    },
    "rpc.identity.rbac.get_role": {
        "summary": "Get role",
        "description": "Returns a single role with its permissions by role_id (422 if role_id is missing).",
    },
    "rpc.identity.rbac.create_role": {
        "summary": "Create role",
        "description": "Creates a new RBAC role and returns it (201), enforcing the active user's permission check.",
    },
    "rpc.identity.rbac.update_role": {
        "summary": "Update role",
        "description": "Updates the role by role_id and returns it, invalidating the RBAC cache.",
    },
    "rpc.identity.rbac.delete_role": {
        "summary": "Delete role",
        "description": "Deletes the role by role_id; returns 204 No Content.",
    },
    # ── RBAC: auth users ───────────────────────────────────────────────────
    "rpc.identity.rbac.list_auth_users": {
        "summary": "List auth users",
        "description": "Returns auth users filtered by search/role_id/is_active/is_superuser/workspace_id, after the active user's permission check.",
    },
    "rpc.identity.rbac.get_auth_user": {
        "summary": "Get auth user",
        "description": "Returns detailed info for a single auth user by user_id (422 if user_id is missing).",
    },
    "rpc.identity.rbac.get_user_roles": {
        "summary": "Get user roles",
        "description": "Returns the roles assigned to the given user_id.",
    },
    "rpc.identity.rbac.assign_linked_player": {
        "summary": "Assign linked player",
        "description": "Links a game player to the given auth user (admin); returns 204 No Content.",
    },
    "rpc.identity.rbac.remove_linked_player": {
        "summary": "Remove linked player",
        "description": "Removes a linked game player from the given auth user (admin) by user_id/player_id; returns 204 No Content.",
    },
    "rpc.identity.rbac.assign_role": {
        "summary": "Assign role",
        "description": "Assigns a role to a user and invalidates the RBAC cache; returns 204 No Content.",
    },
    "rpc.identity.rbac.remove_role": {
        "summary": "Remove role",
        "description": "Removes a role from a user and invalidates the RBAC cache; returns 204 No Content.",
    },
    # ── RBAC: oauth connections / sessions (admin) ─────────────────────────
    "rpc.identity.rbac.list_oauth_connections": {
        "summary": "List OAuth connections (admin)",
        "description": "Returns all OAuth connections (admin), optionally filtered by search and provider.",
    },
    "rpc.identity.rbac.list_sessions": {
        "summary": "List all sessions (admin)",
        "description": "Returns auth-user sessions (admin), filterable by user_id/search and status (active/revoked/expired).",
    },
    "rpc.identity.rbac.delete_oauth_connection": {
        "summary": "Delete OAuth connection",
        "description": "Deletes an OAuth connection by connection_id (admin); returns 204 No Content.",
    },
    # ── player linking ─────────────────────────────────────────────────────
    "rpc.identity.player.link": {
        "summary": "Link player",
        "description": "Links a game player to the active user and returns the link details (201).",
    },
    "rpc.identity.player.unlink": {
        "summary": "Unlink player",
        "description": "Unlinks a game player from the active user by player_id; returns 204 No Content.",
    },
    "rpc.identity.player.linked": {
        "summary": "List linked players",
        "description": "Returns all game players linked to the active user.",
    },
    "rpc.identity.player.set_primary": {
        "summary": "Set primary player",
        "description": "Marks a linked player as the active user's primary player and returns the updated link.",
    },
}
