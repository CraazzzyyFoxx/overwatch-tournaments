// Package auth verifies access tokens locally (no call to identity-svc).
//
// An access token is an EdDSA (Ed25519) JWT signed by identity-svc; the
// gateway holds only the public key (JWT_PUBLIC_KEY). It carries sub/sid/type/
// iat/exp/iss/aud/jti — no email, username, is_superuser or workspace
// membership. So this package only authenticates (signature + type=="access" +
// iss + aud + exp + sub); every fact the gateway authorizes on, superuser
// included, comes from identity-svc's validate_token (see internal/principal).
package auth

import (
	"crypto/ed25519"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// tokenIssuer and tokenAudience are the iss/aud identity-svc stamps on every
// access token (TokenCodec); a token naming anything else is not ours.
const (
	tokenIssuer   = "owt-identity"
	tokenAudience = "owt"
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
// ("owt_sk_<public_id>_<secret>" — identity-service's ApiKeyService.PREFIX).
// Such a credential is not a JWT at all: it carries no claims and can only be
// judged by identity-svc, so Verify must never be handed one.
const APIKeyPrefix = "owt_sk_"

// legacyAPIKeyPrefix is what keys minted before the owt rebrand still carry.
// identity-svc keeps validating them (ApiKeyService._LEGACY_PREFIXES), so this
// test has to keep recognising them: a key it misses is verified as a JWT,
// which makes the socket anonymous and skips the per-key limiter.
const legacyAPIKeyPrefix = "aqt_sk_"

// IsAPIKey reports whether token is an opaque API key rather than a signed
// access token. It is a purely local prefix test, and that is what lets every
// surface skip the identity RPC for ordinary session traffic.
func IsAPIKey(token string) bool {
	return strings.HasPrefix(token, APIKeyPrefix) || strings.HasPrefix(token, legacyAPIKeyPrefix)
}

// IsWellFormedAPIKey reports whether token has the exact shape identity-svc
// mints (ApiKeyService.create: "<prefix>_<token_hex(8)>_<token_hex(32)>", the
// same since the first aqt_sk_ key): a key prefix, then 16 and 64 lowercase
// hex digits. A prefixed token of any other shape can never validate, so the
// resolver turns it away without an RPC.
func IsWellFormedAPIKey(token string) bool {
	rest, ok := strings.CutPrefix(token, APIKeyPrefix)
	if !ok {
		rest, ok = strings.CutPrefix(token, legacyAPIKeyPrefix)
	}
	return ok && len(rest) == 16+1+64 && rest[16] == '_' && isLowerHex(rest[:16]) && isLowerHex(rest[17:])
}

func isLowerHex(s string) bool {
	for i := range len(s) {
		if c := s[i]; (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

// User is an authenticated WebSocket/HTTP principal. A nil *User means anonymous.
type User struct {
	ID int64
	// IsSuperuser is identity-svc's is_superuser verdict (the access token no
	// longer carries it, so Verify never sets it). A superuser bypasses the
	// per-workspace membership check in the topic ACL, exactly as the Python
	// AuthUser.is_workspace_member does (`if self.is_superuser: return True`).
	// Never true for an API key.
	IsSuperuser bool
	// ExpiresAt is the token's `exp` claim. The ws.Handler binds the connection
	// lifetime to it so an authenticated socket cannot outlive its access token
	// (a stale/expired session must stop receiving auth-gated events). Zero for
	// an API key, which has no exp to bind to.
	ExpiresAt time.Time
	// APIKeyWorkspaceID is the one workspace a workspace-scoped API key is
	// pinned to; zero for a session. Non-zero confines the principal: the topic
	// ACL grants it nothing workspace-scoped outside that workspace and none of
	// its owner's personal topics — it acts as the key, not as the user.
	APIKeyWorkspaceID int64
	// Token is the credential this principal was authenticated from, kept so a
	// live socket can be judged again when identity-svc announces that its
	// user's sessions or grants changed (ws.TopicRevoker).
	Token string
}

// Authenticator verifies access tokens with identity-svc's public key.
type Authenticator struct {
	key    ed25519.PublicKey
	parser *jwt.Parser
}

// New returns an Authenticator bound to identity-svc's Ed25519 public key.
// Only EdDSA is accepted — the explicit method allowlist defends against
// alg=none and algorithm confusion (e.g. an HS256 token keyed with the public
// key) — and iss, aud and exp are required.
func New(publicKey ed25519.PublicKey) *Authenticator {
	return &Authenticator{
		key: publicKey,
		parser: jwt.NewParser(
			jwt.WithValidMethods([]string{jwt.SigningMethodEdDSA.Alg()}),
			jwt.WithIssuer(tokenIssuer),
			jwt.WithAudience(tokenAudience),
			jwt.WithExpirationRequired(),
		),
	}
}

// UserFromRequest is the request's session principal by the local check
// alone, for the surfaces that must not pay an RPC (httplog, metrics): nil for
// no credential, an invalid one, or an API key — a key carries no claims, and
// resolving it here would put identity-svc on the access-log path.
func (a *Authenticator) UserFromRequest(r *http.Request) *User {
	token := TokenFromRequest(r)
	if token == "" || IsAPIKey(token) {
		return nil
	}
	return a.Verify(token)
}

// Verify checks an access token locally and returns its principal (ID,
// ExpiresAt, Token — never IsSuperuser), or nil when it is invalid.
func (a *Authenticator) Verify(token string) *User {
	claims := jwt.MapClaims{}
	parsed, err := a.parser.ParseWithClaims(token, claims, func(*jwt.Token) (any, error) {
		return a.key, nil
	})
	if err != nil || !parsed.Valid {
		return nil
	}
	if t, _ := claims["type"].(string); t != "access" {
		return nil
	}
	sub, _ := claims["sub"].(string)
	id, err := strconv.ParseInt(sub, 10, 64)
	if err != nil || id <= 0 {
		return nil
	}
	exp, err := claims.GetExpirationTime() // present: the parser requires it
	if err != nil || exp == nil {
		return nil
	}
	return &User{ID: id, ExpiresAt: exp.Time, Token: token}
}

// TokenFromRequest returns the request's credential: the Authorization bearer,
// else the access-token cookie. Never the query string — a credential in a URL
// lands in every proxy access log and in browser history.
func TokenFromRequest(r *http.Request) string {
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
