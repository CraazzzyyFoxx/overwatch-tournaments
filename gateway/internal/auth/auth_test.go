package auth

import (
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
