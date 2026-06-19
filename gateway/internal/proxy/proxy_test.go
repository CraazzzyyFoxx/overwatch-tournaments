package proxy

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
)

func echoServer(t *testing.T, name string) (*httptest.Server, *string) {
	t.Helper()
	var lastPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		lastPath = r.URL.Path
		w.Header().Set("X-Upstream", name)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(name))
	}))
	t.Cleanup(srv.Close)
	return srv, &lastPath
}

func TestProxy_LongestPrefixRouting(t *testing.T) {
	app, appPath := echoServer(t, "app")
	frontend, frontendPath := echoServer(t, "frontend")

	const unused = "http://127.0.0.1:1"
	p, err := New(config.Upstreams{
		App:       app.URL,
		Frontend:  frontend.URL,
		Parser:    unused,
		Balancer:  unused,
		Analytics: unused,
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	srv := httptest.NewServer(p)
	defer srv.Close()

	cases := []struct {
		path     string
		wantHdr  string
		wantPath string
		seen     *string
	}{
		{"/api/v1/core/users/1", "app", "/api/v1/core/users/1", appPath},
		// /api/v1/* (non-core) is no longer proxied (served by gateway RPC routes);
		// in the bare proxy it falls through to the frontend catch-all.
		{"/api/v1/tournaments/5", "frontend", "/api/v1/tournaments/5", frontendPath},
		{"/api/account/me", "frontend", "/api/account/me", frontendPath},
		{"/tournaments/5", "frontend", "/tournaments/5", frontendPath},
	}
	for _, c := range cases {
		t.Run(c.path, func(t *testing.T) {
			resp, err := http.Get(srv.URL + c.path)
			if err != nil {
				t.Fatal(err)
			}
			defer resp.Body.Close()
			if got := resp.Header.Get("X-Upstream"); got != c.wantHdr {
				t.Fatalf("routed to %q, want %q", got, c.wantHdr)
			}
			if *c.seen != c.wantPath {
				t.Fatalf("upstream saw path %q, want %q (path must be preserved)", *c.seen, c.wantPath)
			}
		})
	}
}

func TestMatchPrefix(t *testing.T) {
	cases := []struct {
		path, prefix string
		want         bool
	}{
		{"/api/v1", "/api/v1", true},
		{"/api/v1/x", "/api/v1", true},
		{"/api/v1xyz", "/api/v1", false},
		{"/anything", "/", true},
	}
	for _, c := range cases {
		if got := matchPrefix(c.path, c.prefix); got != c.want {
			t.Fatalf("matchPrefix(%q,%q)=%v want %v", c.path, c.prefix, got, c.want)
		}
	}
}

func TestNew_InvalidUpstream(t *testing.T) {
	_, err := New(config.Upstreams{App: "://bad", Frontend: "y"})
	if err == nil {
		t.Fatal("expected error for invalid upstream url")
	}
}
