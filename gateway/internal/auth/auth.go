// Package auth validates the shared HS256 JWT locally (no call to auth-service).
//
// The access token (issued by auth-service) carries sub/email/username/
// is_superuser/sid/exp/type — NOT workspace membership. So this package
// authenticates the connection (signature + exp + type=="access" + sub) and
// surfaces is_superuser, which the topic ACL uses as a membership bypass
// (mirroring AuthUser.is_workspace_member: superusers pass every workspace).
// Per-workspace membership for non-superusers is resolved separately against
// the database (see internal/workspace).
package auth

import (
	"context"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// CookieName is the canonical access-token cookie; LegacyCookieName is read as a
// fallback during the aqt->owt rename so existing sessions are not logged out.
//
// The prefix is per-deployment (SESSION_COOKIE_PREFIX, default "owt", matching
// the frontend's NEXT_PUBLIC_COOKIE_PREFIX). A second deployment under the same
// registrable domain — the dev site at dev.owt.craazzzyyfoxx.me — is otherwise
// handed production's domain-wide cookie of the same name: the Cookie header
// carries no Domain, so the two are indistinguishable and the older one wins.
// Read once at init: the environment does not change under a running process.
var CookieName = cookiePrefix() + "_access_token"

const LegacyCookieName = "aqt_access_token"

func cookiePrefix() string {
	if p := strings.TrimSpace(os.Getenv("SESSION_COOKIE_PREFIX")); p != "" {
		return p
	}
	return "owt"
}

// APIKeyPrefix marks an opaque workspace-scoped API key
// ("aqt_sk_<public_id>_<secret>" — identity-service's ApiKeyService.PREFIX).
// Such a credential is not a JWT at all: it carries no claims and can only be
// judged by identity-svc, so parseToken must never be handed one.
const APIKeyPrefix = "aqt_sk_"

// IsAPIKey reports whether token is an opaque API key rather than a signed
// access token. It is a purely local prefix test, and that is what lets every
// surface skip the identity RPC for ordinary session traffic.
func IsAPIKey(token string) bool { return strings.HasPrefix(token, APIKeyPrefix) }

// APIKeyResolver judges an opaque API key against identity-svc and returns the
// principal it authenticates, or nil when the key is invalid or carries no
// usable authority. It is injected as a function rather than imported so this
// package keeps its zero-dependency local-JWT posture — the implementation
// speaks RPC (see internal/principal and ws.APIKeyAuth).
type APIKeyResolver func(ctx context.Context, token string) *User

// User is an authenticated WebSocket/HTTP principal. A nil *User means anonymous.
type User struct {
	ID int64
	// IsSuperuser mirrors the JWT's is_superuser claim. A superuser bypasses the
	// per-workspace membership check in the topic ACL, exactly as the Python
	// AuthUser.is_workspace_member does (`if self.is_superuser: return True`).
	IsSuperuser bool
	// ExpiresAt is the token's `exp` claim. The ws.Handler binds the connection
	// lifetime to it so an authenticated socket cannot outlive its access token
	// (a stale/expired session must stop receiving auth-gated events). Zero when
	// the token carries no exp (never happens for a valid access token, which the
	// parser already requires to be unexpired).
	ExpiresAt time.Time
}

// Authenticator decodes and verifies access tokens with the shared secret.
type Authenticator struct {
	secret []byte
	parser *jwt.Parser
	// apiKeys is nil unless a surface opted in via WithAPIKeys.
	apiKeys APIKeyResolver
}

// New returns an Authenticator bound to the shared JWT secret. Only HS256 is
// accepted; the explicit method allowlist defends against alg=none / algorithm
// confusion attacks.
func New(secret string) *Authenticator {
	return &Authenticator{
		secret: []byte(secret),
		parser: jwt.NewParser(jwt.WithValidMethods([]string{"HS256"})),
	}
}

// WithAPIKeys returns a COPY of a that additionally authenticates opaque API
// keys through resolve. A copy rather than a mutation because only some
// surfaces may pay for it: resolve performs an identity RPC on a cache miss,
// and httplog/metrics call UserFromRequest after the response is already
// written — an RPC there would put the identity backend on the access-log
// path. The WebSocket handler gets the api-key-aware authenticator; those two
// keep the JWT-only one.
func (a *Authenticator) WithAPIKeys(resolve APIKeyResolver) *Authenticator {
	c := *a
	c.apiKeys = resolve
	return &c
}

// UserFromRequest resolves the principal from a request. It mirrors the
// realtime-service behaviour: a missing OR invalid token yields anonymous
// (nil, nil) rather than rejecting the connection. Authorization is enforced
// later by the per-topic ACL.
func (a *Authenticator) UserFromRequest(r *http.Request) *User {
	token := extractToken(r)
	if token == "" {
		return nil
	}
	// An opaque API key can never parse as a JWT, so without this branch it
	// degraded silently to anonymous. Only surfaces that opted in via
	// WithAPIKeys resolve one; for the rest a key stays unauthenticated,
	// exactly as before.
	if IsAPIKey(token) {
		if a.apiKeys == nil {
			return nil
		}
		return a.apiKeys(r.Context(), token)
	}
	return a.parseToken(token)
}

// parseToken validates the token and returns the principal, or nil if invalid.
func (a *Authenticator) parseToken(token string) *User {
	claims := jwt.MapClaims{}
	parsed, err := a.parser.ParseWithClaims(token, claims, func(*jwt.Token) (any, error) {
		return a.secret, nil
	})
	if err != nil || !parsed.Valid {
		return nil
	}

	if t, _ := claims["type"].(string); t != "access" {
		return nil
	}

	sub, ok := claims["sub"].(string)
	if !ok {
		return nil
	}
	id, err := strconv.ParseInt(sub, 10, 64)
	if err != nil || id <= 0 {
		return nil
	}
	// is_superuser is optional; a missing/non-bool claim safely yields false.
	isSuperuser, _ := claims["is_superuser"].(bool)
	u := &User{ID: id, IsSuperuser: isSuperuser}
	if exp, err := claims.GetExpirationTime(); err == nil && exp != nil {
		u.ExpiresAt = exp.Time
	}
	return u
}

// extractToken pulls the bearer token from the query string, the Authorization
// header, or the access-token cookie — in that order (matching realtime-service).
func extractToken(r *http.Request) string {
	if q := r.URL.Query().Get("token"); q != "" {
		return strings.TrimSpace(strings.TrimPrefix(q, "Bearer "))
	}

	if h := r.Header.Get("Authorization"); h != "" {
		scheme, creds, found := strings.Cut(h, " ")
		if found && strings.EqualFold(scheme, "bearer") {
			if c := strings.TrimSpace(creds); c != "" {
				return c
			}
		}
	}

	for _, name := range []string{CookieName, LegacyCookieName} {
		if c, err := r.Cookie(name); err == nil && c.Value != "" {
			return strings.TrimSpace(strings.TrimPrefix(c.Value, "Bearer "))
		}
	}
	return ""
}
