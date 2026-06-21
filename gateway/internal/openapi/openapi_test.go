package openapi

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

func buildDoc(t *testing.T, groups []Group) map[string]any {
	t.Helper()
	raw := Build(Info{Title: "Test API", Version: "1.2.3", Description: "desc"}, groups)
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("Build produced invalid JSON: %v", err)
	}
	return doc
}

func asMap(t *testing.T, v any, what string) map[string]any {
	t.Helper()
	m, ok := v.(map[string]any)
	if !ok {
		t.Fatalf("%s: expected object, got %T", what, v)
	}
	return m
}

func sampleGroups() []Group {
	return []Group{
		{Tag: "Public", Routes: []edge.RouteSpec{
			{Method: "GET", Pattern: "/api/v1/things", Queue: "rpc.thing.list", AllQuery: true, Auth: edge.AuthNone},
			{Method: "GET", Pattern: "/api/v1/things/{id}", Queue: "rpc.thing.get", IDParam: "id", Query: []string{"entities"}, Auth: edge.AuthOptional},
		}},
		{Tag: "Admin", Routes: []edge.RouteSpec{
			{Method: "POST", Pattern: "/api/v1/things", Queue: "rpc.thing.create", Body: true, Auth: edge.AuthRequired, Success: 201},
			{Method: "DELETE", Pattern: "/api/v1/things/{id}", Queue: "rpc.thing.delete", IDParam: "id", Auth: edge.AuthRequired, Success: 204},
			{Method: "GET", Pattern: "/api/v1/files/{path...}", Queue: "rpc.file.get", Path: []string{"path"}, Auth: edge.AuthRequired},
		}},
	}
}

func TestBuild_TopLevel(t *testing.T) {
	doc := buildDoc(t, sampleGroups())

	if got := doc["openapi"]; got != "3.1.0" {
		t.Errorf("openapi = %v, want 3.1.0", got)
	}
	info := asMap(t, doc["info"], "info")
	if info["title"] != "Test API" || info["version"] != "1.2.3" {
		t.Errorf("info = %v", info)
	}
	comps := asMap(t, doc["components"], "components")
	schemes := asMap(t, comps["securitySchemes"], "securitySchemes")
	bearer := asMap(t, schemes["bearerAuth"], "bearerAuth")
	if bearer["scheme"] != "bearer" {
		t.Errorf("bearerAuth.scheme = %v", bearer["scheme"])
	}

	tags, ok := doc["tags"].([]any)
	if !ok || len(tags) != 2 {
		t.Fatalf("tags = %v, want 2", doc["tags"])
	}
	if name := asMap(t, tags[0], "tags[0]")["name"]; name != "Public" {
		t.Errorf("tags[0].name = %v, want Public (declared order)", name)
	}
}

func TestBuild_PathsAndMethods(t *testing.T) {
	doc := buildDoc(t, sampleGroups())
	paths := asMap(t, doc["paths"], "paths")

	// Same path declared across two groups merges into one path item.
	things := asMap(t, paths["/api/v1/things"], "/api/v1/things")
	if _, ok := things["get"]; !ok {
		t.Error("/api/v1/things missing GET")
	}
	if _, ok := things["post"]; !ok {
		t.Error("/api/v1/things missing POST (cross-group merge failed)")
	}

	// Trailing wildcard {path...} becomes {path}.
	files, ok := paths["/api/v1/files/{path}"]
	if !ok {
		t.Fatalf("wildcard pattern not converted; paths = %v", keys(paths))
	}
	get := asMap(t, asMap(t, files, "files")["get"], "files.get")
	params, _ := get["parameters"].([]any)
	if len(params) != 1 || asMap(t, params[0], "param")["name"] != "path" {
		t.Errorf("files.get parameters = %v, want one path param named 'path'", get["parameters"])
	}
}

func TestBuild_Operations(t *testing.T) {
	doc := buildDoc(t, sampleGroups())
	paths := asMap(t, doc["paths"], "paths")

	// AllQuery → documented in the description; AuthNone → no security key.
	listGet := asMap(t, asMap(t, paths["/api/v1/things"], "things")["get"], "things.get")
	if desc, _ := listGet["description"].(string); !strings.Contains(desc, "arbitrary query") {
		t.Errorf("AllQuery route description = %q, want arbitrary-query note", listGet["description"])
	}
	if sec, ok := listGet["security"].([]any); !ok || len(sec) != 0 {
		t.Errorf("AuthNone route security = %v, want explicit empty list", listGet["security"])
	}

	// AuthRequired POST with body → requestBody, bearer security, 201 + 401.
	post := asMap(t, asMap(t, paths["/api/v1/things"], "things")["post"], "things.post")
	if _, ok := post["requestBody"]; !ok {
		t.Error("Body route missing requestBody")
	}
	sec, ok := post["security"].([]any)
	if !ok || len(sec) != 1 || asMap(t, sec[0], "sec")["bearerAuth"] == nil {
		t.Errorf("AuthRequired security = %v, want [{bearerAuth}]", post["security"])
	}
	resp := asMap(t, post["responses"], "post.responses")
	if _, ok := resp["201"]; !ok {
		t.Error("custom Success=201 not reflected in responses")
	}
	if _, ok := resp["401"]; !ok {
		t.Error("AuthRequired route missing 401 response")
	}

	// 204 success → no response content.
	del := asMap(t, asMap(t, paths["/api/v1/things/{id}"], "things/id")["delete"], "delete")
	r204 := asMap(t, asMap(t, del["responses"], "del.responses")["204"], "204")
	if _, ok := r204["content"]; ok {
		t.Error("204 response should have no content")
	}

	// AuthOptional → anonymous + bearer.
	optGet := asMap(t, asMap(t, paths["/api/v1/things/{id}"], "things/id")["get"], "get")
	if sec, _ := optGet["security"].([]any); len(sec) != 2 {
		t.Errorf("AuthOptional security = %v, want 2 entries", optGet["security"])
	}
}

func TestBuild_Deterministic(t *testing.T) {
	a := Build(Info{Title: "x"}, sampleGroups())
	b := Build(Info{Title: "x"}, sampleGroups())
	if string(a) != string(b) {
		t.Error("Build output is not deterministic")
	}
}

func TestPublicAuthedSplit(t *testing.T) {
	routes := []edge.RouteSpec{
		{Method: "GET", Pattern: "/a", Auth: edge.AuthNone},
		{Method: "GET", Pattern: "/b", Auth: edge.AuthOptional},
		{Method: "POST", Pattern: "/c", Auth: edge.AuthRequired},
	}
	if got := PublicOnly(routes); len(got) != 2 {
		t.Errorf("PublicOnly len = %d, want 2", len(got))
	}
	if got := AuthedOnly(routes); len(got) != 1 || got[0].Pattern != "/c" {
		t.Errorf("AuthedOnly = %v, want [/c]", got)
	}
}

func keys(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
