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
	frontend, frontendPath := echoServer(t, "frontend")

	const unused = "http://127.0.0.1:1"
	p, err := New(config.Upstreams{
		Frontend:  frontend.URL,
		Parser:    unused,
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
		// /api/v1/* (every backend domain, all typed RPC) is no longer proxied;
		// in the bare proxy it falls through to the frontend catch-all. The
		// mux-level guard (see edge/apiv1_guard_test.go) returns 404 for
		// unmatched /api/v1/*.
		{"/api/v1/users/1", "frontend", "/api/v1/users/1", frontendPath},
		{"/api/v1/tournaments/5", "frontend", "/api/v1/tournaments/5", frontendPath},
		// The frontend's own surface: served by Next, reached through "/" with no
		// spec of its own. `/api/account` was its old spelling and is gone.
		{"/bff/account/sessions", "frontend", "/bff/account/sessions", frontendPath},
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

// A spoofed `x-owt-workspace-id` would make the frontend render another
// tenant's white-label chrome and scope its SSR reads to that workspace, so the
// edge must drop the whole family regardless of casing.
func TestProxy_StripsClientSuppliedScopeHeaders(t *testing.T) {
	var seen http.Header
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r.Header.Clone()
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	p, err := New(config.Upstreams{Frontend: upstream.URL})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	srv := httptest.NewServer(p)
	defer srv.Close()

	req, err := http.NewRequest(http.MethodGet, srv.URL+"/tournaments/5", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("x-owt-workspace-id", "999")
	req.Header.Set("X-OWT-Host-Mode", "tenant")
	req.Header.Set("x-owt-zone", "admin")
	req.Header.Set("Accept-Language", "ru")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	for _, key := range []string{"X-Owt-Workspace-Id", "X-Owt-Host-Mode", "X-Owt-Zone"} {
		if got := seen.Get(key); got != "" {
			t.Fatalf("upstream saw %s=%q; the edge must strip client-supplied scope headers", key, got)
		}
	}
	if got := seen.Get("Accept-Language"); got != "ru" {
		t.Fatalf("unrelated header dropped: Accept-Language=%q, want %q", got, "ru")
	}
}

func TestNew_InvalidUpstream(t *testing.T) {
	_, err := New(config.Upstreams{Parser: "://bad", Frontend: "y"})
	if err == nil {
		t.Fatal("expected error for invalid upstream url")
	}
}
