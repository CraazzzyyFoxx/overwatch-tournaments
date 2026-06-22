"""OpenAPI request/response model map for identity-service RPC subjects.

Schemas-only module consumed by the export script — see ``shared.rpc.openapi``.
The gateway's identity HTTP handler (gateway/internal/identity) is a transparent
pass-through of the RPC envelope's ``data``, so the client response body == the
Python handler's returned model. Models mirror the flow return annotations /
direct model construction in serve.py + src/services/*_flows.py.

Handlers returning ``rpc_ok(None)`` (204) or ad-hoc dicts are omitted (generic).
No generic-CRUD engine; KEY = the full RPC subject string.
"""

from __future__ import annotations

from shared.core.pagination import Paginated
from shared.rpc.openapi import Op

from src import schemas

OPERATIONS: dict[str, Op] = {
    # ── token / service validation ─────────────────────────────────────────
    "rpc.identity.validate_token": Op(response=schemas.TokenPayload),
    "rpc.identity.validate_service_token": Op(response=schemas.ServiceTokenPayload),
    "rpc.identity.service_token": Op(request=schemas.ServiceTokenRequest, response=schemas.ServiceToken),
    # ── auth core ──────────────────────────────────────────────────────────
    "rpc.identity.register": Op(request=schemas.UserRegister, response=schemas.AuthUser),
    "rpc.identity.login": Op(request=schemas.UserLogin, response=schemas.Token),
    "rpc.identity.refresh": Op(request=schemas.RefreshTokenRequest, response=schemas.Token),
    "rpc.identity.list_sessions": Op(response=schemas.SessionRead, response_array=True),
    "rpc.identity.get_me": Op(response=schemas.AuthUser),
    "rpc.identity.update_me": Op(request=schemas.UserUpdate, response=schemas.AuthUser),
    "rpc.identity.set_password": Op(request=schemas.PasswordSetRequest),
    "rpc.identity.me.avatar_set": Op(response=schemas.AuthUser),
    "rpc.identity.me.avatar_delete": Op(response=schemas.AuthUser),
    # ── oauth ──────────────────────────────────────────────────────────────
    "rpc.identity.oauth_providers": Op(response=schemas.OAuthProviderAvailability, response_array=True),
    "rpc.identity.oauth_url": Op(response=schemas.OAuthURL),
    "rpc.identity.oauth_callback": Op(response=schemas.Token),
    "rpc.identity.oauth_connections": Op(response=schemas.OAuthUserInfo, response_array=True),
    # ── api keys ───────────────────────────────────────────────────────────
    "rpc.identity.list_api_keys": Op(response=schemas.ApiKeyListResponse, query=schemas.ApiKeyListQueryParams),
    "rpc.identity.create_api_key": Op(request=schemas.ApiKeyCreate, response=schemas.ApiKeyCreateResponse),
    "rpc.identity.update_api_key": Op(request=schemas.ApiKeyUpdate, response=schemas.ApiKeyRead),
    # ── RBAC: permissions ──────────────────────────────────────────────────
    "rpc.identity.rbac.list_permissions": Op(response=Paginated[schemas.PermissionRead], query=schemas.PermissionListQueryParams),
    "rpc.identity.rbac.create_permission": Op(request=schemas.PermissionCreate, response=schemas.PermissionRead),
    # ── RBAC: roles ────────────────────────────────────────────────────────
    "rpc.identity.rbac.list_roles": Op(response=Paginated[schemas.RoleRead], query=schemas.RoleListQueryParams),
    "rpc.identity.rbac.get_role": Op(response=schemas.RoleWithPermissions),
    "rpc.identity.rbac.create_role": Op(request=schemas.RoleCreate, response=schemas.RoleRead),
    "rpc.identity.rbac.update_role": Op(request=schemas.RoleUpdate, response=schemas.RoleRead),
    # ── RBAC: auth users ───────────────────────────────────────────────────
    "rpc.identity.rbac.list_auth_users": Op(response=Paginated[schemas.AuthUserListRead], query=schemas.AuthUserListQueryParams),
    "rpc.identity.rbac.get_auth_user": Op(response=schemas.AuthUserDetailRead),
    "rpc.identity.rbac.get_user_roles": Op(response=schemas.RoleRead, response_array=True),
    "rpc.identity.rbac.assign_linked_player": Op(request=schemas.AuthUserPlayerLinkAssign),
    "rpc.identity.rbac.assign_role": Op(request=schemas.UserRoleAssign),
    "rpc.identity.rbac.remove_role": Op(request=schemas.UserRoleRemove),
    # ── RBAC: oauth connections / sessions (admin) ─────────────────────────
    "rpc.identity.rbac.list_oauth_connections": Op(response=Paginated[schemas.OAuthConnectionAdminRead], query=schemas.OAuthConnectionListQueryParams),
    "rpc.identity.rbac.list_sessions": Op(response=Paginated[schemas.AdminSessionRead], query=schemas.SessionListQueryParams),
    # ── player linking ─────────────────────────────────────────────────────
    "rpc.identity.player.link": Op(request=schemas.PlayerLinkRequest, response=schemas.PlayerLinkResponse),
    "rpc.identity.player.linked": Op(response=schemas.LinkedPlayer, response_array=True),
}
