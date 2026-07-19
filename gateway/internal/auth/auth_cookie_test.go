package auth

import (
	"net/http"
	"testing"
)

func TestExtractTokenPrefersOwtThenAqtCookie(t *testing.T) {
	cases := []struct {
		name    string
		cookies []*http.Cookie
		want    string
	}{
		{"owt only", []*http.Cookie{{Name: "owt_access_token", Value: "N"}}, "N"},
		{"aqt fallback", []*http.Cookie{{Name: "aqt_access_token", Value: "O"}}, "O"},
		{"owt wins", []*http.Cookie{{Name: "aqt_access_token", Value: "O"}, {Name: "owt_access_token", Value: "N"}}, "N"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r, _ := http.NewRequest("GET", "/", nil)
			for _, ck := range c.cookies {
				r.AddCookie(ck)
			}
			if got := extractToken(r); got != c.want {
				t.Fatalf("got %q want %q", got, c.want)
			}
		})
	}
}
