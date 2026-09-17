// Package identity exposes the HTTP face of the auth/identity domain on the
// gateway, translating REST calls into RPC into identity-svc. Phase 1A added
// /validate; 1B adds register/login/refresh/logout. 1C+ add oauth/etc.
package identity

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/apierr"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/clientip"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/httplog"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
)

const (
	queueValidateToken = "rpc.identity.validate_token"
	queueRegister      = "rpc.identity.register"
	queueLogin         = "rpc.identity.login"
	queueRefresh       = "rpc.identity.refresh"
	queueLogout        = "rpc.identity.logout"
	queueLogoutAll     = "rpc.identity.logout_all"
	queueListSessions  = "rpc.identity.list_sessions"
	queueRevokeSession = "rpc.identity.revoke_session"
	queueGetMe         = "rpc.identity.get_me"
	queueUpdateMe      = "rpc.identity.update_me"
	queueDeleteMe      = "rpc.identity.delete_me"
	queueSetPassword   = "rpc.identity.set_password"

	queueServiceToken         = "rpc.identity.service_token"
	queueValidateServiceToken = "rpc.identity.validate_service_token"
	queueInvalidateSession    = "rpc.identity.invalidate_session"

	queueOAuthProviders   = "rpc.identity.oauth_providers"
	queueOAuthURL         = "rpc.identity.oauth_url"
	queueOAuthCallback    = "rpc.identity.oauth_callback"
	queueOAuthLink        = "rpc.identity.oauth_link"
	queueOAuthConnections = "rpc.identity.oauth_connections"
	queueOAuthUnlink      = "rpc.identity.oauth_unlink"
	queueSsoExchange      = "rpc.identity.sso_exchange"
	queueLinkComplete     = "rpc.identity.link_complete"

	queueListApiKeys     = "rpc.identity.list_api_keys"
	queueCreateApiKey    = "rpc.identity.create_api_key"
	queueUpdateApiKey    = "rpc.identity.update_api_key"
	queueRevokeApiKey    = "rpc.identity.revoke_api_key"
	queueSelfApiKey      = "rpc.identity.api_key.self"
	queueApiKeyQuota     = "rpc.identity.api_key.quota_usage"
	queueSetApiKeyQuota  = "rpc.identity.api_key.quota_set"
	queueSelfApiKeyQuota = "rpc.identity.api_key.self_quota"

	queueRbacListPermissions    = "rpc.identity.rbac.list_permissions"
	queueRbacCreatePermission   = "rpc.identity.rbac.create_permission"
	queueRbacDeletePermission   = "rpc.identity.rbac.delete_permission"
	queueRbacListRoles          = "rpc.identity.rbac.list_roles"
	queueRbacGetRole            = "rpc.identity.rbac.get_role"
	queueRbacCreateRole         = "rpc.identity.rbac.create_role"
	queueRbacUpdateRole         = "rpc.identity.rbac.update_role"
	queueRbacDeleteRole         = "rpc.identity.rbac.delete_role"
	queueRbacListAuthUsers      = "rpc.identity.rbac.list_auth_users"
	queueRbacGetAuthUser        = "rpc.identity.rbac.get_auth_user"
	queueRbacDeleteAuthUser     = "rpc.identity.rbac.delete_auth_user"
	queueRbacAssignLinkedPlayer = "rpc.identity.rbac.assign_linked_player"
	queueRbacRemoveLinkedPlayer = "rpc.identity.rbac.remove_linked_player"
	queueRbacAssignRole         = "rpc.identity.rbac.assign_role"
	queueRbacRemoveRole         = "rpc.identity.rbac.remove_role"
	queueRbacGetUserRoles       = "rpc.identity.rbac.get_user_roles"
	queueRbacListUserDenies     = "rpc.identity.rbac.list_user_denies"
	queueRbacAddUserDeny        = "rpc.identity.rbac.add_user_deny"
	queueRbacRemoveUserDeny     = "rpc.identity.rbac.remove_user_deny"
	queueRbacListOAuthConns     = "rpc.identity.rbac.list_oauth_connections"
	queueRbacListSessions       = "rpc.identity.rbac.list_sessions"
	queueRbacDeleteOAuthConn    = "rpc.identity.rbac.delete_oauth_connection"

	queuePlayerLink       = "rpc.identity.player.link"
	queuePlayerUnlink     = "rpc.identity.player.unlink"
	queuePlayerLinked     = "rpc.identity.player.linked"
	queuePlayerSetPrimary = "rpc.identity.player.set_primary"

	// maxJSONBody caps the request body before it is buffered into an RPC
	// message, matching edge.maxBody. Without it a slowloris/oversized body could
	// exhaust the container's memory (nginx's own cap is the only other guard).
	maxJSONBody = 12 << 20 // 12 MiB
)

// rpcTimeout bounds how long the gateway waits for an identity-svc RPC reply
// before returning 504. Most identity RPCs are sub-second, but oauth_callback
// performs external provider token+userinfo calls (Discord/Twitch/Battle.net)
// that can take several seconds from the ingress host — with the old 5s cap the
// gateway gave up while identity-svc was still completing a *successful* login,
// so the user landed back logged-out. Override with GATEWAY_IDENTITY_RPC_TIMEOUT
// (a Go duration, e.g. "20s"); keep it BELOW the frontend SSR fetch timeout
// (DEFAULT_SERVER_TIMEOUT_MS = 15s) or the Next server aborts before this reply
// lands.
var rpcTimeout = resolveRPCTimeout()

func resolveRPCTimeout() time.Duration {
	const def = 12 * time.Second
	if v := os.Getenv("GATEWAY_IDENTITY_RPC_TIMEOUT"); v != "" {
		if d, err := time.ParseDuration(v); err == nil && d > 0 {
			return d
		}
	}
	return def
}

// RPCCaller is the subset of rpc.Client the handlers need (eases testing).
type RPCCaller interface {
	Call(ctx context.Context, queue string, body []byte) ([]byte, error)
}

// Handler serves identity HTTP endpoints by calling identity-svc over RPC.
type Handler struct {
	rpc RPCCaller
	log *slog.Logger
}

// NewHandler wires the identity HTTP handler.
func NewHandler(caller RPCCaller, log *slog.Logger) *Handler {
	return &Handler{rpc: caller, log: log}
}

// Validate mirrors auth-service POST /validate: bearer access token / API key
// -> RBAC TokenPayload.
func (h *Handler) Validate(w http.ResponseWriter, r *http.Request) {
	h.validateBearer(w, r, queueValidateToken)
}

// ValidateService mirrors POST /service/validate: a service JWT -> ServiceTokenPayload.
func (h *Handler) ValidateService(w http.ResponseWriter, r *http.Request) {
	h.validateBearer(w, r, queueValidateServiceToken)
}

// validateBearer forwards a bearer token to a validation RPC method.
func (h *Handler) validateBearer(w http.ResponseWriter, r *http.Request, queue string) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"token": token})
	h.callIdentity(w, r, queue, body, http.StatusOK)
}

// ServiceToken mirrors POST /service/token: client credentials -> service token.
func (h *Handler) ServiceToken(w http.ResponseWriter, r *http.Request) {
	body, ok := decodeRawBody(w, r)
	if !ok {
		return
	}
	h.callIdentity(w, r, queueServiceToken, body, http.StatusOK)
}

// InvalidateSession mirrors POST /service/invalidate-session/{user_id} -> 204.
// Requires a valid service token (bearer).
//
// The name is historical: the worker drops the user's cached RBAC so their next
// request re-reads permissions from the database. It does NOT revoke a token or
// end a session -- see ServiceTokenService.invalidate_rbac in identity-service.
func (h *Handler) InvalidateSession(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"token": token, "user_id": r.PathValue("user_id")})
	h.callIdentity(w, r, queueInvalidateSession, body, http.StatusNoContent)
}

// Register mirrors POST /register -> 201 AuthUser.
func (h *Handler) Register(w http.ResponseWriter, r *http.Request) {
	body, ok := decodeRawBody(w, r)
	if !ok {
		return
	}
	h.callIdentity(w, r, queueRegister, body, http.StatusCreated)
}

// Login mirrors POST /login -> 200 Token. Client UA/IP are forwarded for the
// refresh-token session record.
func (h *Handler) Login(w http.ResponseWriter, r *http.Request) {
	body, ok := bodyWithMeta(w, r, nil)
	if !ok {
		return
	}
	h.callIdentity(w, r, queueLogin, body, http.StatusOK)
}

// Refresh mirrors POST /refresh -> 200 Token (rotation).
func (h *Handler) Refresh(w http.ResponseWriter, r *http.Request) {
	body, ok := bodyWithMeta(w, r, nil)
	if !ok {
		return
	}
	h.callIdentity(w, r, queueRefresh, body, http.StatusOK)
}

// Logout mirrors POST /logout -> 204. Requires a bearer access token plus the
// refresh token in the body.
func (h *Handler) Logout(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, ok := bodyWithMeta(w, r, map[string]any{"access_token": token})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueLogout, body, http.StatusNoContent)
}

// LogoutAll mirrors POST /logout-all -> 204 (revoke all refresh tokens).
func (h *Handler) LogoutAll(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueLogoutAll, http.StatusNoContent)
}

// Sessions mirrors GET /sessions -> 200 [SessionRead].
func (h *Handler) Sessions(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueListSessions, http.StatusOK)
}

// Me mirrors GET /me -> 200 AuthUser.
func (h *Handler) Me(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueGetMe, http.StatusOK)
}

// DeleteMe mirrors DELETE /me -> 204: the user deletes their OWN account.
// Historical data survives the deletion (see identity-svc auth_flows.delete_me);
// only auth-owned rows cascade away.
func (h *Handler) DeleteMe(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueDeleteMe, http.StatusNoContent)
}

// RevokeSession mirrors DELETE /sessions/{id} -> 204.
func (h *Handler) RevokeSession(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "session_id": r.PathValue("id")})
	h.callIdentity(w, r, queueRevokeSession, body, http.StatusNoContent)
}

// UpdateMe mirrors PATCH /me -> 200 AuthUser.
func (h *Handler) UpdateMe(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, ok := mergeBody(w, r, map[string]any{"access_token": token})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueUpdateMe, body, http.StatusOK)
}

// SetPassword mirrors POST /set-password -> 204.
func (h *Handler) SetPassword(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, ok := mergeBody(w, r, map[string]any{"access_token": token})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueSetPassword, body, http.StatusNoContent)
}

// --- OAuth (callbacks return Token JSON; the frontend handles redirects) ---

// OAuthProviders mirrors GET /oauth/providers.
func (h *Handler) OAuthProviders(w http.ResponseWriter, r *http.Request) {
	h.callIdentity(w, r, queueOAuthProviders, []byte("{}"), http.StatusOK)
}

// OAuthURL mirrors GET /oauth/{provider}/url?origin=&redirect=&action=&csrf=&guard_hash=.
// origin/redirect/action/csrf get signed into the OAuth state server-side
// (identity-service oauth_flows.get_url) so the callback can later redirect
// back to the originating host and bind the browser via the csrf cookie.
// guard_hash (Task 10R fix 1) is OPTIONAL -- only the frontend's
// custom-domain apex bounce supplies one (oauth-login.ts); identity-svc
// signs it into the state only when present and treats an empty string the
// same as absent.
func (h *Handler) OAuthURL(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	body, _ := json.Marshal(map[string]any{
		"provider":   r.PathValue("provider"),
		"origin":     q.Get("origin"),
		"redirect":   q.Get("redirect"),
		"action":     q.Get("action"),
		"csrf":       q.Get("csrf"),
		"guard_hash": q.Get("guard_hash"),
	})
	h.callIdentity(w, r, queueOAuthURL, body, http.StatusOK)
}

// OAuthCallbackPost mirrors POST /oauth/{provider}/callback (body code+state) -> Token.
func (h *Handler) OAuthCallbackPost(w http.ResponseWriter, r *http.Request) {
	body, ok := bodyWithMeta(w, r, map[string]any{"provider": r.PathValue("provider")})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueOAuthCallback, body, http.StatusOK)
}

// OAuthLink mirrors POST /oauth/{provider}/link. Auth is OPTIONAL at this
// layer (unlike every other authenticated identity route) -- identity-svc
// itself decides whether a bearer is required, branching on the signed
// OAuth state's origin: a platform-host link still needs a resolvable user
// (unchanged), but a custom-domain link never does -- it can only mint a
// single-use provider-identity ticket for a live session on that custom
// domain to redeem later via LinkComplete below (see oauth_flows.link,
// Task 10R). `access_token` is set from the bearer UNCONDITIONALLY --
// including as "" when there is none -- so a client-supplied body
// access_token can never survive mergeBody's overwrite either way.
func (h *Handler) OAuthLink(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	extra := map[string]any{"access_token": token, "provider": r.PathValue("provider")}
	body, ok := mergeBody(w, r, extra)
	if !ok {
		return
	}
	h.callIdentity(w, r, queueOAuthLink, body, http.StatusOK)
}

// LinkComplete mirrors POST /auth/link/complete (Task 10R). UNLIKE
// SsoExchange, this route IS authenticated: it redeems a pending-link
// ticket minted by a custom-domain OAuth link callback (mode="link_ticket")
// and attaches the PROVIDER identity it carries to the caller resolved from
// THIS bearer token -- that bearer user is ALWAYS the linked-to site
// account (SECURITY INVARIANTS #1/#4). A missing bearer is rejected here,
// before ever reaching identity-svc -- there is no anonymous use case for
// this route, unlike OAuthLink above.
//
// The client-supplied body (Task 10R fix 1: {ticket, guard}) round-trips
// through mergeBody unfiltered -- it only OVERWRITES "access_token" with the
// bearer above, never drops or renames any other client field -- so "guard"
// (the raw owt_xdomain_guard cookie value the frontend route read) reaches
// identity-svc's rpc.identity.link_complete alongside "ticket" with no
// per-field wiring needed here.
func (h *Handler) LinkComplete(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, ok := mergeBody(w, r, map[string]any{"access_token": token})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueLinkComplete, body, http.StatusOK)
}

// SsoExchange mirrors POST /auth/sso/exchange (public; body {ticket, guard}).
// Redeems a one-time Redis SSO ticket minted by a custom-domain OAuth
// callback (identity-svc oauth_flows.callback, mode="ticket") for the
// session tokens -- called by the custom domain's own frontend route, never
// by the apex. No client metadata is needed, so this skips bodyWithMeta.
//
// decodeRawBody re-marshals the ENTIRE client body verbatim, so "guard"
// (Task 10R fix 1: the raw owt_xdomain_guard cookie value the frontend route
// read) reaches identity-svc's rpc.identity.sso_exchange alongside "ticket"
// with no per-field wiring needed here.
func (h *Handler) SsoExchange(w http.ResponseWriter, r *http.Request) {
	body, ok := decodeRawBody(w, r)
	if !ok {
		return
	}
	h.callIdentity(w, r, queueSsoExchange, body, http.StatusOK)
}

// OAuthConnections mirrors GET /oauth/connections (authenticated).
func (h *Handler) OAuthConnections(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueOAuthConnections, http.StatusOK)
}

// OAuthUnlink mirrors DELETE /oauth/{provider}/unlink (authenticated) -> 204.
func (h *Handler) OAuthUnlink(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "provider": r.PathValue("provider")})
	h.callIdentity(w, r, queueOAuthUnlink, body, http.StatusNoContent)
}

// --- API keys (workspace-scoped, authenticated) ---

// ListApiKeys mirrors GET /api-keys?workspace_id=&page=&per_page=&sort=&order=&search=.
func (h *Handler) ListApiKeys(w http.ResponseWriter, r *http.Request) {
	h.authedAllQuery(w, r, queueListApiKeys, http.StatusOK)
}

// CreateApiKey mirrors POST /api-keys -> 201.
func (h *Handler) CreateApiKey(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, ok := mergeBody(w, r, map[string]any{"access_token": token})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueCreateApiKey, body, http.StatusCreated)
}

// UpdateApiKey mirrors PATCH /api-keys/{id}.
func (h *Handler) UpdateApiKey(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, ok := mergeBody(w, r, map[string]any{"access_token": token, "api_key_id": r.PathValue("id")})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueUpdateApiKey, body, http.StatusOK)
}

// RevokeApiKey mirrors DELETE /api-keys/{id} -> 204.
func (h *Handler) RevokeApiKey(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "api_key_id": r.PathValue("id")})
	h.callIdentity(w, r, queueRevokeApiKey, body, http.StatusNoContent)
}

// SelfApiKey mirrors GET /api-keys/self: the descriptor of the key the CALLER
// is presenting (name, scopes, expiry), so a scripted client can discover its
// own authority without an admin token.
//
// Deliberately not gated by credential type here. identity-svc resolves the
// bearer itself and answers 403 "API key credential required" for a browser
// session (which has no current key), the same way every other api-key RPC
// decides its own eligibility — the gateway stays credential-agnostic on this
// namespace.
func (h *Handler) SelfApiKey(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueSelfApiKey, http.StatusOK)
}

// ApiKeyQuota mirrors GET /api-keys/{id}/quota: the key's effective ceilings
// next to what has been spent, at both scopes it is subject to -- its own and
// its workspace's. Management credential, like the other admin-side key reads.
func (h *Handler) ApiKeyQuota(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "api_key_id": r.PathValue("id")})
	h.callIdentity(w, r, queueApiKeyQuota, body, http.StatusOK)
}

// SetApiKeyQuota mirrors PUT /api-keys/{id}/quota. The body is one ``limits``
// object whose five dimensions ride at the top of the RPC payload; an
// all-null one deletes the override rather than pinning five nulls.
//
// identity-svc decides the authority: a superuser may raise a dimension, a
// workspace manager may only lower it below what the plan grants, and the
// refusal is a 422 the client renders on the offending field.
func (h *Handler) SetApiKeyQuota(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body, ok := mergeBody(w, r, map[string]any{"access_token": token, "api_key_id": r.PathValue("id")})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueSetApiKeyQuota, body, http.StatusOK)
}

// SelfApiKeyQuota mirrors GET /api-keys/self/quota: the budget of the key the
// CALLER is presenting, so a scripted client can pace itself without an admin
// token. Same credential-agnostic stance as SelfApiKey above -- identity-svc
// answers 403 for a browser session, which holds no key.
func (h *Handler) SelfApiKeyQuota(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueSelfApiKeyQuota, http.StatusOK)
}

// --- RBAC admin (authenticated; permission checks enforced in identity-svc) ---
//
// Query filters (search/role_id/is_active/is_superuser/workspace_id/provider/
// status/user_id) ride as scalar fields in the RPC body; path params likewise.
// Permission checks + cache invalidation run in identity-svc's rbac_admin services.

// RbacListPermissions mirrors GET /rbac/permissions?page=&per_page=&sort=&order=&search=&workspace_id=.
func (h *Handler) RbacListPermissions(w http.ResponseWriter, r *http.Request) {
	h.authedAllQuery(w, r, queueRbacListPermissions, http.StatusOK)
}

// RbacCreatePermission mirrors POST /rbac/permissions -> 201.
func (h *Handler) RbacCreatePermission(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queueRbacCreatePermission, http.StatusCreated, nil)
}

// RbacDeletePermission mirrors DELETE /rbac/permissions/{permission_id} -> 204.
func (h *Handler) RbacDeletePermission(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacDeletePermission, http.StatusNoContent,
		map[string]any{"permission_id": r.PathValue("permission_id")})
}

// RbacListRoles mirrors GET /rbac/roles?page=&per_page=&sort=&order=&search=&workspace_id=.
func (h *Handler) RbacListRoles(w http.ResponseWriter, r *http.Request) {
	h.authedAllQuery(w, r, queueRbacListRoles, http.StatusOK)
}

// RbacGetRole mirrors GET /rbac/roles/{role_id}.
func (h *Handler) RbacGetRole(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacGetRole, http.StatusOK, map[string]any{"role_id": r.PathValue("role_id")})
}

// RbacCreateRole mirrors POST /rbac/roles -> 201.
func (h *Handler) RbacCreateRole(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queueRbacCreateRole, http.StatusCreated, nil)
}

// RbacUpdateRole mirrors PATCH /rbac/roles/{role_id}.
func (h *Handler) RbacUpdateRole(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queueRbacUpdateRole, http.StatusOK, map[string]any{"role_id": r.PathValue("role_id")})
}

// RbacDeleteRole mirrors DELETE /rbac/roles/{role_id} -> 204.
func (h *Handler) RbacDeleteRole(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacDeleteRole, http.StatusNoContent, map[string]any{"role_id": r.PathValue("role_id")})
}

// RbacListAuthUsers mirrors GET /rbac/users?page=&per_page=&sort=&order=&search=&role_id=&is_active=&is_superuser=&workspace_id=.
func (h *Handler) RbacListAuthUsers(w http.ResponseWriter, r *http.Request) {
	h.authedAllQuery(w, r, queueRbacListAuthUsers, http.StatusOK)
}

// RbacGetAuthUser mirrors GET /rbac/users/{user_id}.
func (h *Handler) RbacGetAuthUser(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacGetAuthUser, http.StatusOK, map[string]any{"user_id": r.PathValue("user_id")})
}

// RbacDeleteAuthUser mirrors DELETE /rbac/users/{user_id} -> 204 (superuser only, enforced in identity-svc).
func (h *Handler) RbacDeleteAuthUser(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacDeleteAuthUser, http.StatusNoContent,
		map[string]any{"user_id": r.PathValue("user_id")})
}

// RbacAssignLinkedPlayer mirrors POST /rbac/users/{user_id}/linked-players -> 204.
func (h *Handler) RbacAssignLinkedPlayer(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queueRbacAssignLinkedPlayer, http.StatusNoContent,
		map[string]any{"user_id": r.PathValue("user_id")})
}

// RbacRemoveLinkedPlayer mirrors DELETE /rbac/users/{user_id}/linked-players/{player_id} -> 204.
func (h *Handler) RbacRemoveLinkedPlayer(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacRemoveLinkedPlayer, http.StatusNoContent,
		map[string]any{"user_id": r.PathValue("user_id"), "player_id": r.PathValue("player_id")})
}

// RbacAssignRole mirrors POST /rbac/users/assign-role -> 204.
func (h *Handler) RbacAssignRole(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queueRbacAssignRole, http.StatusNoContent, nil)
}

// RbacRemoveRole mirrors POST /rbac/users/remove-role -> 204.
func (h *Handler) RbacRemoveRole(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queueRbacRemoveRole, http.StatusNoContent, nil)
}

// RbacListUserDenies mirrors GET /rbac/users/{user_id}/denies.
func (h *Handler) RbacListUserDenies(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacListUserDenies, http.StatusOK, map[string]any{"user_id": r.PathValue("user_id")})
}

// RbacAddUserDeny mirrors POST /rbac/users/{user_id}/denies
// (body: permission_id, reason?, workspace_id? — omitted/null = global deny).
func (h *Handler) RbacAddUserDeny(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queueRbacAddUserDeny, http.StatusOK, map[string]any{"user_id": r.PathValue("user_id")})
}

// RbacRemoveUserDeny mirrors DELETE /rbac/users/{user_id}/denies/{permission_id}?workspace_id=
// (query param optional; omitted = matches the global deny, not a workspace-scoped one).
func (h *Handler) RbacRemoveUserDeny(w http.ResponseWriter, r *http.Request) {
	extra := map[string]any{"user_id": r.PathValue("user_id"), "permission_id": r.PathValue("permission_id")}
	if v := r.URL.Query().Get("workspace_id"); v != "" {
		extra["workspace_id"] = v
	}
	h.authedFields(w, r, queueRbacRemoveUserDeny, http.StatusOK, extra)
}

// RbacGetUserRoles mirrors GET /rbac/users/{user_id}/roles.
func (h *Handler) RbacGetUserRoles(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacGetUserRoles, http.StatusOK, map[string]any{"user_id": r.PathValue("user_id")})
}

// RbacListOAuthConnections mirrors GET /rbac/oauth-connections?page=&per_page=&sort=&order=&search=&provider=.
func (h *Handler) RbacListOAuthConnections(w http.ResponseWriter, r *http.Request) {
	h.authedAllQuery(w, r, queueRbacListOAuthConns, http.StatusOK)
}

// RbacListSessions mirrors GET /rbac/sessions?page=&per_page=&sort=&order=&search=&user_id=&status=.
func (h *Handler) RbacListSessions(w http.ResponseWriter, r *http.Request) {
	h.authedAllQuery(w, r, queueRbacListSessions, http.StatusOK)
}

// RbacDeleteOAuthConnection mirrors DELETE /rbac/oauth-connections/{connection_id} -> 204.
func (h *Handler) RbacDeleteOAuthConnection(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacDeleteOAuthConn, http.StatusNoContent,
		map[string]any{"connection_id": r.PathValue("connection_id")})
}

// --- Player linking (authenticated; resolves the active user in identity-svc) ---

// PlayerLink mirrors POST /player/link -> 201.
func (h *Handler) PlayerLink(w http.ResponseWriter, r *http.Request) {
	h.authedMerge(w, r, queuePlayerLink, http.StatusCreated, nil)
}

// PlayerUnlink mirrors DELETE /player/unlink/{player_id} -> 204.
func (h *Handler) PlayerUnlink(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queuePlayerUnlink, http.StatusNoContent, map[string]any{"player_id": r.PathValue("player_id")})
}

// PlayerLinked mirrors GET /player/linked -> 200 [LinkedPlayer].
func (h *Handler) PlayerLinked(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queuePlayerLinked, http.StatusOK)
}

// PlayerSetPrimary mirrors PATCH /player/linked/{player_id}/primary -> 200.
func (h *Handler) PlayerSetPrimary(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queuePlayerSetPrimary, http.StatusOK, map[string]any{"player_id": r.PathValue("player_id")})
}

// authedFields handles a bearer-authenticated endpoint with no JSON request body,
// forwarding the access token plus fixed extra fields (path params) and the
// trusted client metadata (see setClientMeta) to identity-svc.
func (h *Handler) authedFields(w http.ResponseWriter, r *http.Request, queue string, successStatus int, extra map[string]any) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body := map[string]any{"access_token": token}
	for k, v := range extra {
		body[k] = v
	}
	setClientMeta(r, body)
	b, _ := json.Marshal(body)
	h.callIdentity(w, r, queue, b, successStatus)
}

// authedQuery handles a bearer-authenticated GET, forwarding the access token plus
// the named query params (omitting any that are absent) to identity-svc.
func (h *Handler) authedQuery(w http.ResponseWriter, r *http.Request, queue string, successStatus int, params ...string) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body := map[string]any{"access_token": token}
	for _, p := range params {
		if v := r.URL.Query().Get(p); v != "" {
			body[p] = v
		}
	}
	b, _ := json.Marshal(body)
	h.callIdentity(w, r, queue, b, successStatus)
}

// authedAllQuery handles a bearer-authenticated paginated GET, forwarding the
// access token plus ALL query params nested under "query" (as {key: [values]},
// mirroring edge.AllQuery). identity-svc rebuilds its query-params model via
// shared.rpc.query.build_query_model — pagination, sort, and filters all ride here.
func (h *Handler) authedAllQuery(w http.ResponseWriter, r *http.Request, queue string, successStatus int) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	// The metadata rides at the TOP level, never inside "query":
	// build_query_model only ever sees the nested map, so an audit field can
	// never be mistaken for (or collide with) a filter name.
	body := map[string]any{
		"access_token": token,
		"query":        map[string][]string(r.URL.Query()),
	}
	setClientMeta(r, body)
	b, _ := json.Marshal(body)
	h.callIdentity(w, r, queue, b, successStatus)
}

// authedMerge handles a bearer-authenticated endpoint with a JSON request body,
// merging the access token plus fixed extra fields (path params) and the trusted
// client metadata before forwarding.
func (h *Handler) authedMerge(w http.ResponseWriter, r *http.Request, queue string, successStatus int, extra map[string]any) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	merged := map[string]any{"access_token": token}
	for k, v := range extra {
		merged[k] = v
	}
	// mergeBody applies `merged` OVER the decoded client body, so stamping the
	// metadata into it here is still an unconditional post-merge overwrite --
	// the very mechanism that keeps a body-supplied access_token from surviving
	// in OAuthLink above.
	setClientMeta(r, merged)
	body, ok := mergeBody(w, r, merged)
	if !ok {
		return
	}
	h.callIdentity(w, r, queue, body, successStatus)
}

// A MISSING bearer is 401, never 403: 401 means "not authenticated" and invites
// the caller to refresh, 403 means "authenticated but not allowed". These
// handlers answered 403, which the frontend's refresh path (it only reacts to
// 401) read as a hard permission error — so an expired access cookie silently
// presented a still-valid 30-day session as logged out. edge/dispatch.go and the
// OpenAPI generator have always documented 401 here; keep every guard aligned.

// authedNoBody handles a bearer-authenticated endpoint with no request body,
// forwarding just the access token plus the trusted client metadata to identity-svc.
func (h *Handler) authedNoBody(w http.ResponseWriter, r *http.Request, queue string, successStatus int) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusUnauthorized, "Not authenticated")
		return
	}
	body := map[string]any{"access_token": token}
	setClientMeta(r, body)
	b, _ := json.Marshal(body)
	h.callIdentity(w, r, queue, b, successStatus)
}

// callIdentity performs the RPC and maps the reply envelope to an HTTP response.
func (h *Handler) callIdentity(w http.ResponseWriter, r *http.Request, queue string, body []byte, successStatus int) {
	ctx, cancel := context.WithTimeout(r.Context(), rpcTimeout)
	defer cancel()

	log := httplog.From(r.Context())
	raw, err := h.rpc.Call(ctx, queue, body)
	if err != nil {
		if rpc.IsUnavailable(err) {
			log.Error("identity rpc unavailable", "method", queue, "err", err)
			w.Header().Set("Retry-After", "1")
			writeDetail(w, http.StatusServiceUnavailable, "identity service unavailable")
			return
		}
		log.Error("identity rpc failed", "method", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "identity service timeout")
		return
	}

	var env rpc.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		log.Error("invalid rpc envelope", "method", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid identity response")
		return
	}

	if !env.OK {
		apierr.WriteEnvelopeError(w, env.Error)
		return
	}
	apierr.WriteOK(w, successStatus, env)
}

// decodeRawBody returns the request body bytes, rejecting invalid JSON.
func decodeRawBody(w http.ResponseWriter, r *http.Request) ([]byte, bool) {
	var probe map[string]any
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxJSONBody))
	if err := dec.Decode(&probe); err != nil {
		writeDetail(w, http.StatusBadRequest, "Invalid request body")
		return nil, false
	}
	body, _ := json.Marshal(probe)
	return body, true
}

// bodyWithMeta decodes the JSON body, merges client UA/IP (and any extra
// fields), and re-marshals it for the RPC request.
func bodyWithMeta(w http.ResponseWriter, r *http.Request, extra map[string]any) ([]byte, bool) {
	body := map[string]any{}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxJSONBody)).Decode(&body); err != nil {
		writeDetail(w, http.StatusBadRequest, "Invalid request body")
		return nil, false
	}
	for k, v := range extra {
		body[k] = v
	}
	ua, ip := clientMeta(r)
	body["user_agent"] = ua
	body["ip_address"] = ip
	b, _ := json.Marshal(body)
	return b, true
}

// mergeBody decodes the JSON body (tolerating an empty body) and merges extra
// fields, for authenticated endpoints that don't need client metadata.
func mergeBody(w http.ResponseWriter, r *http.Request, extra map[string]any) ([]byte, bool) {
	body := map[string]any{}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxJSONBody)).Decode(&body); err != nil && !errors.Is(err, io.EOF) {
		writeDetail(w, http.StatusBadRequest, "Invalid request body")
		return nil, false
	}
	for k, v := range extra {
		body[k] = v
	}
	b, _ := json.Marshal(body)
	return b, true
}

// bearerToken extracts credentials from an "Authorization: Bearer <x>" header.
func bearerToken(r *http.Request) string {
	scheme, creds, found := strings.Cut(r.Header.Get("Authorization"), " ")
	if found && strings.EqualFold(scheme, "bearer") {
		return strings.TrimSpace(creds)
	}
	return ""
}

// clientMeta extracts the original user-agent and the trusted client IP written
// to the session/audit record. Both come from the clientip package, which is
// also what edge.Dispatcher stamps onto every other route's RPC body -- one
// definition of which headers are trustworthy, not two. The IP trusts the
// nginx-set X-Real-IP (and the right-most, non-spoofable X-Forwarded-For hop) --
// never the left-most, client-controlled X-Forwarded-For entry.
func clientMeta(r *http.Request) (userAgent, ip string) {
	return clientip.UserAgent(r), clientip.From(r)
}

// setClientMeta stamps the trusted client IP/user-agent onto an outgoing RPC
// body under the names identity-svc already reads (`ip_address`/`user_agent`).
// These bearer-authenticated routes never pass through edge.Dispatcher, so this
// is the only place the caller's origin can be captured -- and they are the ones
// writing the platform audit log's security rows (role grants, API keys, session
// revocations, player links), where a missing IP costs the forensics.
//
// It is applied AFTER any client-supplied body is merged and overwrites
// unconditionally: a caller must never be able to forge the recorded origin of
// its own mutation, the same reason access_token is overwritten in OAuthLink.
func setClientMeta(r *http.Request, body map[string]any) {
	ua, ip := clientMeta(r)
	body["user_agent"] = ua
	body["ip_address"] = ip
}

// writeDetail emits the gateway's error body (see internal/apierr) for this
// handler's OWN failures. Upstream envelope errors go through
// apierr.WriteEnvelopeError instead, so their structured details survive.
func writeDetail(w http.ResponseWriter, status int, detail string, code ...string) {
	c := ""
	if len(code) > 0 {
		c = code[0]
	}
	apierr.WriteError(w, status, detail, c, nil)
}
