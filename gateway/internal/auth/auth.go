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
	"net/http"
	"strconv"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

// CookieName is where the frontend stores the access token.
const CookieName = "aqt_access_token"

// User is an authenticated WebSocket/HTTP principal. A nil *User means anonymous.
type User struct {
	ID int64
	// IsSuperuser mirrors the JWT's is_superuser claim. A superuser bypasses the
	// per-workspace membership check in the topic ACL, exactly as the Python
	// AuthUser.is_workspace_member does (`if self.is_superuser: return True`).
	IsSuperuser bool
}

// Authenticator decodes and verifies access tokens with the shared secret.
type Authenticator struct {
	secret []byte
	parser *jwt.Parser
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

// UserFromRequest resolves the principal from a request. It mirrors the
// realtime-service behaviour: a missing OR invalid token yields anonymous
// (nil, nil) rather than rejecting the connection. Authorization is enforced
// later by the per-topic ACL.
func (a *Authenticator) UserFromRequest(r *http.Request) *User {
	token := extractToken(r)
	if token == "" {
		return nil
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
	return &User{ID: id, IsSuperuser: isSuperuser}
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

	if c, err := r.Cookie(CookieName); err == nil && c.Value != "" {
		return strings.TrimSpace(strings.TrimPrefix(c.Value, "Bearer "))
	}
	return ""
}
