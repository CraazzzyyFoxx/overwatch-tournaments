package auth

import (
	"crypto/ed25519"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/auth/authtest"
)

func TestVerify_Valid(t *testing.T) {
	a := New(authtest.PublicKey)
	exp := time.Now().Add(30 * time.Minute).Truncate(time.Second)
	c := authtest.Claims("42")
	c["exp"] = exp.Unix()
	c["is_superuser"] = true // a stray claim identity-svc no longer sends grants nothing
	token := authtest.Sign(c)

	u := a.Verify(token)
	if u == nil || u.ID != 42 || !u.ExpiresAt.Equal(exp) || u.Token != token {
		t.Fatalf("expected user 42 expiring %v carrying its token, got %+v", exp, u)
	}
	if u.IsSuperuser {
		t.Fatal("superuser comes from identity-svc, never from a token claim")
	}
}

func TestVerify_Rejected(t *testing.T) {
	a := New(authtest.PublicKey)
	mutated := func(f func(jwt.MapClaims)) string {
		c := authtest.Claims("42")
		f(c)
		return authtest.Sign(c)
	}
	_, otherKey, _ := ed25519.GenerateKey(nil)
	forged, _ := jwt.NewWithClaims(jwt.SigningMethodEdDSA, authtest.Claims("42")).SignedString(otherKey)
	hs256, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, authtest.Claims("42")).SignedString([]byte(authtest.PublicKey))
	none, _ := jwt.NewWithClaims(jwt.SigningMethodNone, authtest.Claims("42")).SignedString(jwt.UnsafeAllowNoneSignatureType)

	for name, token := range map[string]string{
		"expired":            mutated(func(c jwt.MapClaims) { c["exp"] = time.Now().Add(-time.Hour).Unix() }),
		"no exp":             mutated(func(c jwt.MapClaims) { delete(c, "exp") }),
		"wrong issuer":       mutated(func(c jwt.MapClaims) { c["iss"] = "someone-else" }),
		"no issuer":          mutated(func(c jwt.MapClaims) { delete(c, "iss") }),
		"wrong audience":     mutated(func(c jwt.MapClaims) { c["aud"] = "other" }),
		"no audience":        mutated(func(c jwt.MapClaims) { delete(c, "aud") }),
		"service token":      mutated(func(c jwt.MapClaims) { c["type"] = "service" }),
		"non-numeric sub":    mutated(func(c jwt.MapClaims) { c["sub"] = "abc" }),
		"forged signature":   forged,
		"hs256 with pub key": hs256,
		"alg none":           none,
		"garbage":            "not.a.jwt",
	} {
		if u := a.Verify(token); u != nil {
			t.Errorf("%s: must be rejected, got %+v", name, u)
		}
	}
}

func TestUserFromRequest_Sources(t *testing.T) {
	a := New(authtest.PublicKey)
	token := authtest.Token("7")

	t.Run("authorization header", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws", nil)
		r.Header.Set("Authorization", "Bearer "+token)
		if u := a.UserFromRequest(r); u == nil || u.ID != 7 {
			t.Fatalf("header token: got %+v", u)
		}
	})

	t.Run("cookie", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws", nil)
		r.AddCookie(&http.Cookie{Name: CookieName, Value: token})
		if u := a.UserFromRequest(r); u == nil || u.ID != 7 {
			t.Fatalf("cookie token: got %+v", u)
		}
	})

	// A credential in a URL lands in every proxy log: the query string is
	// never read, not even as a last resort.
	t.Run("query param ignored", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws?token="+token, nil)
		if u := a.UserFromRequest(r); u != nil {
			t.Fatalf("a ?token= credential must be ignored, got %+v", u)
		}
	})

	t.Run("anonymous when no token", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws", nil)
		if u := a.UserFromRequest(r); u != nil {
			t.Fatalf("expected anonymous, got %+v", u)
		}
	})

	t.Run("anonymous when invalid token", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws", nil)
		r.Header.Set("Authorization", "Bearer garbage")
		if u := a.UserFromRequest(r); u != nil {
			t.Fatalf("expected anonymous on invalid token, got %+v", u)
		}
	})

	// httplog and metrics must never pay an identity RPC, so a key — which
	// only identity-svc can judge — stays anonymous here.
	t.Run("api key stays anonymous", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws", nil)
		r.Header.Set("Authorization", "Bearer "+wellFormedKey)
		if u := a.UserFromRequest(r); u != nil {
			t.Fatalf("expected anonymous for an api key, got %+v", u)
		}
	})
}

var wellFormedKey = "owt_sk_" + strings.Repeat("a1", 8) + "_" + strings.Repeat("0f", 32)

func TestIsAPIKey(t *testing.T) {
	cases := map[string]bool{
		"owt_sk_pub_secret":        true,
		"owt_sk_":                  true, // malformed, but still a key, never a JWT
		"aqt_sk_pub_secret":        true, // minted before the rebrand, still validated
		"eyJhbGciOiJIUzI1NiJ9.a.b": false,
		"":                         false,
		"sk_owt_pub_secret":        false,
		"prefix_owt_sk_pub_secret": false,
		"OWT_SK_pub_secret":        false, // the prefix is case-sensitive, like the issuer
	}
	for token, want := range cases {
		if got := IsAPIKey(token); got != want {
			t.Errorf("IsAPIKey(%q) = %v, want %v", token, got, want)
		}
	}
}

func TestIsWellFormedAPIKey(t *testing.T) {
	pub, secret := strings.Repeat("a1", 8), strings.Repeat("0f", 32)
	cases := map[string]bool{
		wellFormedKey:                                   true,
		"aqt_sk_" + pub + "_" + secret:                  true,
		"owt_sk_pub_secret":                             false,
		"owt_sk_" + pub + secret:                        false, // no separator
		"owt_sk_" + pub + "_" + secret + "0":            false, // too long
		"owt_sk_" + pub[:15] + "__" + secret:            false, // separator in the wrong place
		"owt_sk_" + strings.ToUpper(pub) + "_" + secret: false, // token_hex is lowercase
		"owt_sk_" + pub + "_" + secret[:63] + "g":       false,
		"xyz_sk_" + pub + "_" + secret:                  false,
	}
	for token, want := range cases {
		if got := IsWellFormedAPIKey(token); got != want {
			t.Errorf("IsWellFormedAPIKey(%q) = %v, want %v", token, got, want)
		}
	}
}
