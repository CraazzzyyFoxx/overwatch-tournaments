package apidocs

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/app"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/balancer"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/identity"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/openapi"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/stats"
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/tournament"
)

// TestGroups_RealSpecsValid builds both specs from the real gateway route
// tables and asserts they are well-formed OpenAPI: valid JSON, non-empty paths,
// every path absolute under /api, and no duplicate operationIds within a spec
// (duplicates would silently shadow operations in the Scalar UI).
func TestGroups_RealSpecsValid(t *testing.T) {
	public, admin := Groups()

	for _, tc := range []struct {
		name   string
		groups []openapi.Group
	}{
		{"public", public},
		{"admin", admin},
	} {
		t.Run(tc.name, func(t *testing.T) {
			raw := openapi.Build(openapi.Info{Title: "t", Version: "1"}, tc.groups)

			var doc struct {
				OpenAPI string                                `json:"openapi"`
				Paths   map[string]map[string]json.RawMessage `json:"paths"`
			}
			if err := json.Unmarshal(raw, &doc); err != nil {
				t.Fatalf("invalid JSON: %v", err)
			}
			if doc.OpenAPI != "3.1.0" {
				t.Errorf("openapi = %q", doc.OpenAPI)
			}
			if len(doc.Paths) == 0 {
				t.Fatal("no paths generated")
			}

			ids := map[string]string{}
			for path, methods := range doc.Paths {
				if !strings.HasPrefix(path, "/api/") {
					t.Errorf("path %q is not under /api/", path)
				}
				if strings.Contains(path, "...") {
					t.Errorf("path %q still contains a raw ServeMux wildcard", path)
				}
				for method, opRaw := range methods {
					var op struct {
						OperationID string `json:"operationId"`
					}
					_ = json.Unmarshal(opRaw, &op)
					if op.OperationID == "" {
						t.Errorf("%s %s missing operationId", method, path)
						continue
					}
					if prev, dup := ids[op.OperationID]; dup {
						t.Errorf("duplicate operationId %q (%s %s and %s)", op.OperationID, method, path, prev)
					}
					ids[op.OperationID] = method + " " + path
				}
			}
			t.Logf("%s spec: %d paths, %d operations", tc.name, len(doc.Paths), len(ids))
		})
	}
}

// TestGroups_NoOverlap ensures the public and admin specs are disjoint by
// operation (method + path) — a single endpoint should be documented on exactly
// one page. The same path may legitimately appear on both pages with different
// methods (e.g. a public GET read + an admin POST write on /api/v1/analytics/jobs).
func TestGroups_NoOverlap(t *testing.T) {
	public, admin := Groups()
	pubOps := opSet(public)
	for op := range opSet(admin) {
		if pubOps[op] {
			t.Errorf("operation %q appears in both public and admin specs", op)
		}
	}
}

// TestGroups_WorkspaceAndQuotaAdminDocumented: both tables are registered on the
// mux (main.go) but were in no group, so 27 working routes had no docs page.
func TestGroups_WorkspaceAndQuotaAdminDocumented(t *testing.T) {
	_, admin := Groups()
	adminOps := opSet(admin)
	for _, r := range concat(app.WorkspaceWriteRoutes, app.QuotaAdminRoutes) {
		if op := strings.ToLower(r.Method) + " " + r.Pattern; !adminOps[op] {
			t.Errorf("%s is served but not on the admin docs page", op)
		}
	}
}

// TestGroups_TypedResponses guards the end-to-end typing: the embedded manifest
// must resolve at least one tournament + one app response to a real component
// schema (vs the generic object fallback).
func TestGroups_TypedResponses(t *testing.T) {
	public, _ := Groups()
	spec := string(openapi.Build(openapi.Info{Title: "t"}, public))
	for _, want := range []string{"#/components/schemas/tournament.", "#/components/schemas/app."} {
		if !strings.Contains(spec, want) {
			t.Errorf("public spec has no typed response referencing %q (manifest not wired?)", want)
		}
	}
}

func opSet(groups []openapi.Group) map[string]bool {
	raw := openapi.Build(openapi.Info{Title: "t"}, groups)
	var doc struct {
		Paths map[string]map[string]json.RawMessage `json:"paths"`
	}
	_ = json.Unmarshal(raw, &doc)
	out := map[string]bool{}
	for path, methods := range doc.Paths {
		for method := range methods {
			out[method+" "+path] = true
		}
	}
	return out
}

// TestGroups_BinaryRoutesDocumentTheirWireFormat: every bespoke multipart upload
// was documented with no request body at all and the match-log download as
// JSON, so neither a generated SDK nor Scalar could call them correctly.
func TestGroups_BinaryRoutesDocumentTheirWireFormat(t *testing.T) {
	public, admin := Groups()
	ops := map[string]struct {
		RequestBody struct {
			Content map[string]json.RawMessage `json:"content"`
		} `json:"requestBody"`
		Responses map[string]struct {
			Content map[string]json.RawMessage `json:"content"`
		} `json:"responses"`
	}{}
	for _, groups := range [][]openapi.Group{public, admin} {
		var doc struct {
			Paths map[string]map[string]json.RawMessage `json:"paths"`
		}
		_ = json.Unmarshal(openapi.Build(openapi.Info{Title: "t"}, groups), &doc)
		for path, methods := range doc.Paths {
			for method, raw := range methods {
				op := ops[method+" "+path]
				_ = json.Unmarshal(raw, &op)
				ops[method+" "+path] = op
			}
		}
	}

	var avatar []edge.RouteSpec
	for _, r := range identity.PublicDocRoutes {
		if r.Queue == "rpc.identity.me.avatar_set" {
			avatar = append(avatar, r)
		}
	}
	binary := concat(app.BinaryDocRoutes, balancer.BinaryPublicDocRoutes, balancer.BinaryAdminDocRoutes,
		stats.BinaryDocRoutes, tournament.BinaryDocRoutes, avatar)
	uploads := 0
	for _, r := range binary {
		op, ok := ops[strings.ToLower(r.Method)+" "+r.Pattern]
		if !ok {
			t.Errorf("%s %s is not documented", r.Method, r.Pattern)
			continue
		}
		if r.Method == "POST" {
			uploads++
			if _, ok := op.RequestBody.Content["multipart/form-data"]; !ok {
				t.Errorf("upload %s does not document a multipart/form-data body", r.Pattern)
			}
		}
	}
	if uploads != 10 {
		t.Errorf("checked %d uploads, want the 10 bespoke multipart routes", uploads)
	}
	log := ops["get /api/v1/matches/{match_id}/log"].Responses["200"].Content
	if _, ok := log["application/octet-stream"]; !ok || len(log) != 1 {
		t.Errorf("match-log download documents %v, want raw application/octet-stream", log)
	}
}
