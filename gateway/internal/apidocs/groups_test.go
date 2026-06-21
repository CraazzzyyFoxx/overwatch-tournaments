package apidocs

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/openapi"
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
// methods (e.g. a public GET read + an admin POST write on /api/analytics/jobs).
func TestGroups_NoOverlap(t *testing.T) {
	public, admin := Groups()
	pubOps := opSet(public)
	for op := range opSet(admin) {
		if pubOps[op] {
			t.Errorf("operation %q appears in both public and admin specs", op)
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
