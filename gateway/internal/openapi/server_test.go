package openapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/config"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

func testServer(cfg config.Docs) *http.ServeMux {
	pub := []Group{{Tag: "Public", Routes: []edge.RouteSpec{
		{Method: "GET", Pattern: "/api/v1/things", Queue: "rpc.thing.list", Auth: edge.AuthNone},
	}}}
	adm := []Group{{Tag: "Admin", Routes: []edge.RouteSpec{
		{Method: "POST", Pattern: "/api/v1/admin/things", Queue: "rpc.thing.create", Body: true, Auth: edge.AuthRequired},
	}}}
	srv := New(cfg, Info{Title: "Gateway API", Version: "1"}, pub, adm)
	mux := http.NewServeMux()
	srv.Register(mux)
	return mux
}

func get(t *testing.T, mux *http.ServeMux, path string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec
}

func TestRegister_PublicAlwaysOn(t *testing.T) {
	mux := testServer(config.Docs{Enabled: true, AdminEnabled: false, CDN: "https://cdn.example/scalar@1.60.0"})

	page := get(t, mux, "/api/docs")
	if page.Code != http.StatusOK {
		t.Fatalf("/api/docs status = %d, want 200", page.Code)
	}
	if ct := page.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/html") {
		t.Errorf("/api/docs content-type = %q", ct)
	}
	body := page.Body.String()
	for _, want := range []string{"/api/openapi.json", "https://cdn.example/scalar@1.60.0", "createApiReference"} {
		if !strings.Contains(body, want) {
			t.Errorf("/api/docs body missing %q", want)
		}
	}

	spec := get(t, mux, "/api/openapi.json")
	if spec.Code != http.StatusOK {
		t.Fatalf("/api/openapi.json status = %d, want 200", spec.Code)
	}
	if ct := spec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Errorf("/api/openapi.json content-type = %q", ct)
	}
	var doc map[string]any
	if err := json.Unmarshal(spec.Body.Bytes(), &doc); err != nil {
		t.Errorf("/api/openapi.json invalid: %v", err)
	}
}

func TestRegister_AdminGated(t *testing.T) {
	mux := testServer(config.Docs{Enabled: true, AdminEnabled: false, CDN: "x"})
	if rec := get(t, mux, "/api/docs/admin"); rec.Code != http.StatusNotFound {
		t.Errorf("/api/docs/admin (disabled) status = %d, want 404", rec.Code)
	}
	if rec := get(t, mux, "/api/openapi.admin.json"); rec.Code != http.StatusNotFound {
		t.Errorf("/api/openapi.admin.json (disabled) status = %d, want 404", rec.Code)
	}
}

func TestRegister_AdminEnabled(t *testing.T) {
	mux := testServer(config.Docs{Enabled: true, AdminEnabled: true, CDN: "x"})
	if rec := get(t, mux, "/api/docs/admin"); rec.Code != http.StatusOK {
		t.Errorf("/api/docs/admin (enabled) status = %d, want 200", rec.Code)
	}
	spec := get(t, mux, "/api/openapi.admin.json")
	if spec.Code != http.StatusOK {
		t.Fatalf("/api/openapi.admin.json (enabled) status = %d, want 200", spec.Code)
	}
	var doc map[string]any
	if err := json.Unmarshal(spec.Body.Bytes(), &doc); err != nil {
		t.Errorf("admin spec invalid: %v", err)
	}
	// Admin spec carries the admin path, not the public one.
	paths := doc["paths"].(map[string]any)
	if _, ok := paths["/api/v1/admin/things"]; !ok {
		t.Error("admin spec missing admin path")
	}
	if _, ok := paths["/api/v1/things"]; ok {
		t.Error("admin spec should not contain public-only paths")
	}
}

func TestRegister_DisabledServesNothing(t *testing.T) {
	mux := testServer(config.Docs{Enabled: false, AdminEnabled: true, CDN: "x"})
	if rec := get(t, mux, "/api/docs"); rec.Code != http.StatusNotFound {
		t.Errorf("/api/docs (docs disabled) status = %d, want 404 (unregistered)", rec.Code)
	}
}
