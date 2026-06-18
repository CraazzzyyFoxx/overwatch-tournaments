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
