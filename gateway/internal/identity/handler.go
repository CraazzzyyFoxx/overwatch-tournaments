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
	"net"
	"net/http"
	"strings"
	"time"

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

	queueListApiKeys  = "rpc.identity.list_api_keys"
	queueCreateApiKey = "rpc.identity.create_api_key"
	queueUpdateApiKey = "rpc.identity.update_api_key"
	queueRevokeApiKey = "rpc.identity.revoke_api_key"

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
	queueRbacAssignLinkedPlayer = "rpc.identity.rbac.assign_linked_player"
	queueRbacRemoveLinkedPlayer = "rpc.identity.rbac.remove_linked_player"
	queueRbacAssignRole         = "rpc.identity.rbac.assign_role"
	queueRbacRemoveRole         = "rpc.identity.rbac.remove_role"
	queueRbacGetUserRoles       = "rpc.identity.rbac.get_user_roles"
	queueRbacListOAuthConns     = "rpc.identity.rbac.list_oauth_connections"
	queueRbacListSessions       = "rpc.identity.rbac.list_sessions"
	queueRbacDeleteOAuthConn    = "rpc.identity.rbac.delete_oauth_connection"

	queuePlayerLink       = "rpc.identity.player.link"
	queuePlayerUnlink     = "rpc.identity.player.unlink"
	queuePlayerLinked     = "rpc.identity.player.linked"
	queuePlayerSetPrimary = "rpc.identity.player.set_primary"

	rpcTimeout = 5 * time.Second
)

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
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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
func (h *Handler) InvalidateSession(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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

// RevokeSession mirrors DELETE /sessions/{id} -> 204.
func (h *Handler) RevokeSession(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "session_id": r.PathValue("id")})
	h.callIdentity(w, r, queueRevokeSession, body, http.StatusNoContent)
}

// UpdateMe mirrors PATCH /me -> 200 AuthUser.
func (h *Handler) UpdateMe(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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

// OAuthURL mirrors GET /oauth/{provider}/url.
func (h *Handler) OAuthURL(w http.ResponseWriter, r *http.Request) {
	body, _ := json.Marshal(map[string]any{"provider": r.PathValue("provider")})
	h.callIdentity(w, r, queueOAuthURL, body, http.StatusOK)
}

// OAuthCallbackGet mirrors GET /oauth/{provider}/callback?code=&state= -> Token.
func (h *Handler) OAuthCallbackGet(w http.ResponseWriter, r *http.Request) {
	ua, ip := clientMeta(r)
	body, _ := json.Marshal(map[string]any{
		"provider":   r.PathValue("provider"),
		"code":       r.URL.Query().Get("code"),
		"state":      r.URL.Query().Get("state"),
		"user_agent": ua,
		"ip_address": ip,
	})
	h.callIdentity(w, r, queueOAuthCallback, body, http.StatusOK)
}

// OAuthCallbackPost mirrors POST /oauth/{provider}/callback (body code+state) -> Token.
func (h *Handler) OAuthCallbackPost(w http.ResponseWriter, r *http.Request) {
	body, ok := bodyWithMeta(w, r, map[string]any{"provider": r.PathValue("provider")})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueOAuthCallback, body, http.StatusOK)
}

// OAuthLink mirrors POST /oauth/{provider}/link (authenticated).
func (h *Handler) OAuthLink(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body, ok := mergeBody(w, r, map[string]any{"access_token": token, "provider": r.PathValue("provider")})
	if !ok {
		return
	}
	h.callIdentity(w, r, queueOAuthLink, body, http.StatusOK)
}

// OAuthConnections mirrors GET /oauth/connections (authenticated).
func (h *Handler) OAuthConnections(w http.ResponseWriter, r *http.Request) {
	h.authedNoBody(w, r, queueOAuthConnections, http.StatusOK)
}

// OAuthUnlink mirrors DELETE /oauth/{provider}/unlink (authenticated) -> 204.
func (h *Handler) OAuthUnlink(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "provider": r.PathValue("provider")})
	h.callIdentity(w, r, queueOAuthUnlink, body, http.StatusNoContent)
}

// --- API keys (workspace-scoped, authenticated) ---

// ListApiKeys mirrors GET /api-keys?workspace_id=.
func (h *Handler) ListApiKeys(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "workspace_id": r.URL.Query().Get("workspace_id")})
	h.callIdentity(w, r, queueListApiKeys, body, http.StatusOK)
}

// CreateApiKey mirrors POST /api-keys -> 201.
func (h *Handler) CreateApiKey(w http.ResponseWriter, r *http.Request) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token, "api_key_id": r.PathValue("id")})
	h.callIdentity(w, r, queueRevokeApiKey, body, http.StatusNoContent)
}

// --- RBAC admin (authenticated; permission checks enforced in identity-svc) ---
//
// Query filters (search/role_id/is_active/is_superuser/workspace_id/provider/
// status/user_id) ride as scalar fields in the RPC body; path params likewise.
// Permission checks + cache invalidation run in identity-svc's rbac_flows.

// RbacListPermissions mirrors GET /rbac/permissions?workspace_id=.
func (h *Handler) RbacListPermissions(w http.ResponseWriter, r *http.Request) {
	h.authedQuery(w, r, queueRbacListPermissions, http.StatusOK, "workspace_id")
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

// RbacListRoles mirrors GET /rbac/roles?workspace_id=.
func (h *Handler) RbacListRoles(w http.ResponseWriter, r *http.Request) {
	h.authedQuery(w, r, queueRbacListRoles, http.StatusOK, "workspace_id")
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

// RbacListAuthUsers mirrors GET /rbac/users?search=&role_id=&is_active=&is_superuser=&workspace_id=.
func (h *Handler) RbacListAuthUsers(w http.ResponseWriter, r *http.Request) {
	h.authedQuery(w, r, queueRbacListAuthUsers, http.StatusOK,
		"search", "role_id", "is_active", "is_superuser", "workspace_id")
}

// RbacGetAuthUser mirrors GET /rbac/users/{user_id}.
func (h *Handler) RbacGetAuthUser(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacGetAuthUser, http.StatusOK, map[string]any{"user_id": r.PathValue("user_id")})
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

// RbacGetUserRoles mirrors GET /rbac/users/{user_id}/roles.
func (h *Handler) RbacGetUserRoles(w http.ResponseWriter, r *http.Request) {
	h.authedFields(w, r, queueRbacGetUserRoles, http.StatusOK, map[string]any{"user_id": r.PathValue("user_id")})
}

// RbacListOAuthConnections mirrors GET /rbac/oauth-connections?search=&provider=.
func (h *Handler) RbacListOAuthConnections(w http.ResponseWriter, r *http.Request) {
	h.authedQuery(w, r, queueRbacListOAuthConns, http.StatusOK, "search", "provider")
}

// RbacListSessions mirrors GET /rbac/sessions?user_id=&search=&status=.
func (h *Handler) RbacListSessions(w http.ResponseWriter, r *http.Request) {
	h.authedQuery(w, r, queueRbacListSessions, http.StatusOK, "user_id", "search", "status")
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
// forwarding the access token plus fixed extra fields (path params) to identity-svc.
func (h *Handler) authedFields(w http.ResponseWriter, r *http.Request, queue string, successStatus int, extra map[string]any) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body := map[string]any{"access_token": token}
	for k, v := range extra {
		body[k] = v
	}
	b, _ := json.Marshal(body)
	h.callIdentity(w, r, queue, b, successStatus)
}

// authedQuery handles a bearer-authenticated GET, forwarding the access token plus
// the named query params (omitting any that are absent) to identity-svc.
func (h *Handler) authedQuery(w http.ResponseWriter, r *http.Request, queue string, successStatus int, params ...string) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
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

// authedMerge handles a bearer-authenticated endpoint with a JSON request body,
// merging the access token plus fixed extra fields (path params) before forwarding.
func (h *Handler) authedMerge(w http.ResponseWriter, r *http.Request, queue string, successStatus int, extra map[string]any) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	merged := map[string]any{"access_token": token}
	for k, v := range extra {
		merged[k] = v
	}
	body, ok := mergeBody(w, r, merged)
	if !ok {
		return
	}
	h.callIdentity(w, r, queue, body, successStatus)
}

// authedNoBody handles a bearer-authenticated endpoint with no request body,
// forwarding just the access token to identity-svc.
func (h *Handler) authedNoBody(w http.ResponseWriter, r *http.Request, queue string, successStatus int) {
	token := bearerToken(r)
	if token == "" {
		writeDetail(w, http.StatusForbidden, "Not authenticated")
		return
	}
	body, _ := json.Marshal(map[string]any{"access_token": token})
	h.callIdentity(w, r, queue, body, successStatus)
}

// callIdentity performs the RPC and maps the reply envelope to an HTTP response.
func (h *Handler) callIdentity(w http.ResponseWriter, r *http.Request, queue string, body []byte, successStatus int) {
	ctx, cancel := context.WithTimeout(r.Context(), rpcTimeout)
	defer cancel()

	raw, err := h.rpc.Call(ctx, queue, body)
	if err != nil {
		if errors.Is(err, rpc.ErrNotConnected) || errors.Is(err, rpc.ErrDisconnected) {
			h.log.Error("identity rpc unavailable", "method", queue, "err", err)
			writeDetail(w, http.StatusServiceUnavailable, "identity service unavailable")
			return
		}
		h.log.Error("identity rpc failed", "method", queue, "err", err)
		writeDetail(w, http.StatusGatewayTimeout, "identity service timeout")
		return
	}

	var env rpc.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		h.log.Error("invalid rpc envelope", "method", queue, "err", err)
		writeDetail(w, http.StatusBadGateway, "invalid identity response")
		return
	}

	if !env.OK {
		status := http.StatusInternalServerError
		msg := "internal error"
		if env.Error != nil {
			status = rpc.StatusForCode(env.Error.Code)
			msg = env.Error.Message
		}
		writeDetail(w, status, msg)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(successStatus)
	if successStatus != http.StatusNoContent && len(env.Data) > 0 && string(env.Data) != "null" {
		_, _ = w.Write(env.Data)
	}
}

// decodeRawBody returns the request body bytes, rejecting invalid JSON.
func decodeRawBody(w http.ResponseWriter, r *http.Request) ([]byte, bool) {
	var probe map[string]any
	dec := json.NewDecoder(r.Body)
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
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
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
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil && !errors.Is(err, io.EOF) {
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

// clientMeta extracts the original user-agent and client IP, preferring
// proxy-forwarded headers — a port of auth_service.get_request_client_metadata.
func clientMeta(r *http.Request) (userAgent, ip string) {
	userAgent = firstNonEmpty(r.Header.Get("X-Original-User-Agent"), r.Header.Get("User-Agent"))

	forwarded := firstNonEmpty(r.Header.Get("X-Forwarded-For"), r.Header.Get("X-Vercel-Forwarded-For"))
	if forwarded != "" {
		for _, candidate := range strings.Split(forwarded, ",") {
			candidate = strings.TrimSpace(candidate)
			if candidate != "" && !strings.EqualFold(candidate, "unknown") {
				ip = candidate
				break
			}
		}
	}
	if ip == "" {
		ip = firstNonEmpty(
			r.Header.Get("X-Real-IP"),
			r.Header.Get("CF-Connecting-IP"),
			r.Header.Get("True-Client-IP"),
			r.Header.Get("X-Client-IP"),
		)
	}
	if ip == "" {
		if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
			ip = host
		}
	}
	return userAgent, ip
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

// writeDetail emits a FastAPI-style error body: {"detail": "..."}.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}
