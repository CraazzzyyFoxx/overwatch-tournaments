package auth

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const testSecret = "test-secret-key"

func signHS256(t *testing.T, claims jwt.MapClaims) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	s, err := tok.SignedString([]byte(testSecret))
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func accessClaims(sub string) jwt.MapClaims {
	return jwt.MapClaims{
		"sub":  sub,
		"type": "access",
		"exp":  time.Now().Add(time.Hour).Unix(),
	}
}

func TestParseToken_Valid(t *testing.T) {
	a := New(testSecret)
	u := a.parseToken(signHS256(t, accessClaims("42")))
	if u == nil || u.ID != 42 {
		t.Fatalf("expected user 42, got %+v", u)
	}
	if u.IsSuperuser {
		t.Fatal("is_superuser must default to false when the claim is absent")
	}
}

func TestParseToken_Superuser(t *testing.T) {
	a := New(testSecret)
	c := accessClaims("42")
	c["is_superuser"] = true
	u := a.parseToken(signHS256(t, c))
	if u == nil || u.ID != 42 || !u.IsSuperuser {
		t.Fatalf("expected superuser 42, got %+v", u)
	}
}

func TestParseToken_PopulatesExpiry(t *testing.T) {
	a := New(testSecret)
	exp := time.Now().Add(30 * time.Minute).Truncate(time.Second)
	c := accessClaims("42")
	c["exp"] = exp.Unix()
	u := a.parseToken(signHS256(t, c))
	if u == nil {
		t.Fatal("expected a user")
	}
	if !u.ExpiresAt.Equal(exp) {
		t.Fatalf("ExpiresAt = %v, want %v", u.ExpiresAt, exp)
	}
}

func TestParseToken_Rejected(t *testing.T) {
	a := New(testSecret)

	t.Run("expired", func(t *testing.T) {
		c := accessClaims("42")
		c["exp"] = time.Now().Add(-time.Hour).Unix()
		if u := a.parseToken(signHS256(t, c)); u != nil {
			t.Fatal("expired token must be rejected")
		}
	})

	t.Run("bad signature", func(t *testing.T) {
		tok := jwt.NewWithClaims(jwt.SigningMethodHS256, accessClaims("42"))
		s, _ := tok.SignedString([]byte("wrong-secret"))
		if u := a.parseToken(s); u != nil {
			t.Fatal("bad signature must be rejected")
		}
	})

	t.Run("alg none", func(t *testing.T) {
		tok := jwt.NewWithClaims(jwt.SigningMethodNone, accessClaims("42"))
		s, _ := tok.SignedString(jwt.UnsafeAllowNoneSignatureType)
		if u := a.parseToken(s); u != nil {
			t.Fatal("alg=none must be rejected")
		}
	})

	t.Run("wrong type", func(t *testing.T) {
		c := accessClaims("42")
		c["type"] = "service"
		if u := a.parseToken(signHS256(t, c)); u != nil {
			t.Fatal("non-access token must be rejected")
		}
	})

	t.Run("non-numeric sub", func(t *testing.T) {
		c := accessClaims("abc")
		if u := a.parseToken(signHS256(t, c)); u != nil {
			t.Fatal("non-numeric sub must be rejected")
		}
	})

	t.Run("garbage", func(t *testing.T) {
		if u := a.parseToken("not.a.jwt"); u != nil {
			t.Fatal("garbage token must be rejected")
		}
	})
}

func TestUserFromRequest_Sources(t *testing.T) {
	a := New(testSecret)
	token := signHS256(t, accessClaims("7"))

	t.Run("query param", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws?token="+token, nil)
		if u := a.UserFromRequest(r); u == nil || u.ID != 7 {
			t.Fatalf("query token: got %+v", u)
		}
	})

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

	t.Run("anonymous when no token", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws", nil)
		if u := a.UserFromRequest(r); u != nil {
			t.Fatalf("expected anonymous, got %+v", u)
		}
	})

	t.Run("anonymous when invalid token", func(t *testing.T) {
		r := httptest.NewRequest(http.MethodGet, "/ws?token=garbage", nil)
		if u := a.UserFromRequest(r); u != nil {
			t.Fatalf("expected anonymous on invalid token, got %+v", u)
		}
	})
}

func TestIsAPIKey(t *testing.T) {
	cases := map[string]bool{
		"owt_sk_pub_secret":        true,
		"owt_sk_":                  true, // malformed, but identity-svc's problem to reject
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

// TestUserFromRequest_APIKeyWithoutResolverIsAnonymous pins the default: a
// plain Authenticator (httplog's and metrics') never resolves an API key, so it
// costs no identity RPC there and a key stays unauthenticated — exactly the
// pre-change behaviour.
func TestUserFromRequest_APIKeyWithoutResolverIsAnonymous(t *testing.T) {
	a := New(testSecret)
	r := httptest.NewRequest(http.MethodGet, "/ws?token=owt_sk_pub_secret", nil)
	if u := a.UserFromRequest(r); u != nil {
		t.Fatalf("expected anonymous without an api-key resolver, got %+v", u)
	}
}

// TestUserFromRequest_APIKeyResolved covers the opted-in surface: the key is
// handed to the resolver verbatim and its principal is returned.
func TestUserFromRequest_APIKeyResolved(t *testing.T) {
	base := New(testSecret)
	var seen string
	a := base.WithAPIKeys(func(_ context.Context, token string) *User {
		seen = token
		return &User{ID: 42}
	})

	r := httptest.NewRequest(http.MethodGet, "/ws?token=owt_sk_pub_secret", nil)
	u := a.UserFromRequest(r)
	if u == nil || u.ID != 42 {
		t.Fatalf("expected the resolved principal, got %+v", u)
	}
	if seen != "owt_sk_pub_secret" {
		t.Errorf("resolver got %q, want the raw key", seen)
	}
	// WithAPIKeys returns a copy: the original must stay JWT-only, or httplog
	// and metrics would start resolving keys over RPC too.
	if u := base.UserFromRequest(r); u != nil {
		t.Fatalf("WithAPIKeys must not mutate the receiver, got %+v", u)
	}
}

// TestUserFromRequest_JWTPathUnchangedWithAPIKeys proves opting in costs the
// session path nothing: a JWT never reaches the resolver.
func TestUserFromRequest_JWTPathUnchangedWithAPIKeys(t *testing.T) {
	called := false
	a := New(testSecret).WithAPIKeys(func(context.Context, string) *User {
		called = true
		return &User{ID: 99}
	})

	r := httptest.NewRequest(http.MethodGet, "/ws?token="+signHS256(t, accessClaims("7")), nil)
	if u := a.UserFromRequest(r); u == nil || u.ID != 7 {
		t.Fatalf("session token must still decode locally, got %+v", u)
	}
	if called {
		t.Fatal("a JWT must never be sent to the api-key resolver")
	}
}

// TestUserFromRequest_APIKeyRejectedStaysAnonymous: an invalid or
// insufficiently-scoped key resolves to nil, which must degrade to anonymous
// rather than a zero-valued principal (user id 0 would pass nil checks).
func TestUserFromRequest_APIKeyRejectedStaysAnonymous(t *testing.T) {
	a := New(testSecret).WithAPIKeys(func(context.Context, string) *User { return nil })
	r := httptest.NewRequest(http.MethodGet, "/ws?token=owt_sk_pub_secret", nil)
	if u := a.UserFromRequest(r); u != nil {
		t.Fatalf("a rejected key must be anonymous, got %+v", u)
	}
}
