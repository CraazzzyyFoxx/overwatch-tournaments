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
	// The caller's description is kept and the credential note appended: the note
	// is the document's only explanation of the two bearer credentials.
	desc, _ := info["description"].(string)
	if !strings.HasPrefix(desc, "desc") || !strings.Contains(desc, "owt_sk_") {
		t.Errorf("info.description = %q, want caller text + API-key credential note", desc)
	}
	comps := asMap(t, doc["components"], "components")
	schemes := asMap(t, comps["securitySchemes"], "securitySchemes")
	// Both credentials ride Authorization: Bearer, so both schemes are http/bearer.
	for _, name := range []string{"bearerAuth", "apiKeyAuth"} {
		s := asMap(t, schemes[name], name)
		if s["type"] != "http" || s["scheme"] != "bearer" {
			t.Errorf("%s = %v, want http/bearer", name, s)
		}
	}

	tags, ok := doc["tags"].([]any)
	if !ok || len(tags) != 2 {
		t.Fatalf("tags = %v, want 2", doc["tags"])
	}
	if name := asMap(t, tags[0], "tags[0]")["name"]; name != "Public" {
		t.Errorf("tags[0].name = %v, want Public (declared order)", name)
	}
}

func TestBuild_ErrorSchemaIncludesCode(t *testing.T) {
	doc := buildDoc(t, sampleGroups())
	comps := asMap(t, doc["components"], "components")
	schemas := asMap(t, comps["schemas"], "schemas")
	errSchema := asMap(t, schemas["Error"], "Error")
	props := asMap(t, errSchema["properties"], "Error.properties")
	if _, ok := props["detail"]; !ok {
		t.Fatal("Error.properties missing detail")
	}
	if _, ok := props["code"]; !ok {
		t.Fatal("Error.properties missing code")
	}
	examples, _ := errSchema["examples"].([]any)
	if len(examples) == 0 {
		t.Fatal("Error schema missing examples")
	}
	info := asMap(t, doc["info"], "info")
	desc, _ := info["description"].(string)
	for _, want := range []string{"rate_limited", "not_found", "`detail`", "/api/v2"} {
		if !strings.Contains(desc, want) {
			t.Errorf("info.description missing %q", want)
		}
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

func TestBuildV2_RewritesAndWraps(t *testing.T) {
	raw := BuildV2(Info{Title: "Test API", Version: "1"}, sampleGroups())
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	paths := asMap(t, doc["paths"], "paths")
	if _, ok := paths["/api/v1/things"]; ok {
		t.Fatal("v1 path leaked into v2 spec")
	}
	if _, ok := paths["/api/v2/things"]; !ok {
		t.Fatalf("missing v2 path; have %v", keys(paths))
	}
	get := asMap(t, asMap(t, paths["/api/v2/things"], "things")["get"], "get")
	schema := asMap(t, asMap(t, asMap(t, asMap(t, get["responses"], "resp")["200"], "200")["content"], "content")["application/json"], "json")["schema"]
	props := asMap(t, asMap(t, schema, "schema")["properties"], "properties")
	if _, ok := props["ok"]; !ok {
		t.Fatalf("success schema not wrapped: %#v", schema)
	}
	schemas := asMap(t, asMap(t, doc["components"], "components")["schemas"], "schemas")
	errProps := asMap(t, asMap(t, schemas["Error"], "Error")["properties"], "Error.properties")
	if _, ok := errProps["ok"]; !ok {
		t.Fatalf("v2 Error missing ok: %#v", schemas["Error"])
	}
	desc, _ := asMap(t, doc["info"], "info")["description"].(string)
	if !strings.Contains(desc, "error.code") || strings.Contains(desc, "`detail` is always present") {
		t.Errorf("v2 info.description still documents the v1 envelope: %q", desc)
	}
	resp := asMap(t, get["responses"], "get.responses")
	if _, ok := resp["429"]; !ok {
		t.Error("v2 GET missing 429")
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

	// AuthRequired POST with body → requestBody, both schemes, 201 + 401.
	post := asMap(t, asMap(t, paths["/api/v1/things"], "things")["post"], "things.post")
	if _, ok := post["requestBody"]; !ok {
		t.Error("Body route missing requestBody")
	}
	sec, ok := post["security"].([]any)
	if !ok || len(sec) != 2 {
		t.Fatalf("AuthRequired security = %v, want [{bearerAuth},{apiKeyAuth}]", post["security"])
	}
	if asMap(t, sec[0], "sec[0]")["bearerAuth"] == nil || asMap(t, sec[1], "sec[1]")["apiKeyAuth"] == nil {
		t.Errorf("AuthRequired security = %v, want session JWT and API key as alternatives", post["security"])
	}
	resp := asMap(t, post["responses"], "post.responses")
	if _, ok := resp["201"]; !ok {
		t.Error("custom Success=201 not reflected in responses")
	}
	if _, ok := resp["401"]; !ok {
		t.Error("AuthRequired route missing 401 response")
	}
	if _, ok := resp["403"]; !ok {
		t.Error("AuthRequired route missing 403 response")
	}
	if _, ok := resp["429"]; !ok {
		t.Error("missing 429 response")
	}

	// 204 success → no response content.
	del := asMap(t, asMap(t, paths["/api/v1/things/{id}"], "things/id")["delete"], "delete")
	r204 := asMap(t, asMap(t, del["responses"], "del.responses")["204"], "204")
	if _, ok := r204["content"]; ok {
		t.Error("204 response should have no content")
	}

	// AuthOptional → anonymous + both credentials.
	optGet := asMap(t, asMap(t, paths["/api/v1/things/{id}"], "things/id")["get"], "get")
	if sec, _ := optGet["security"].([]any); len(sec) != 3 {
		t.Errorf("AuthOptional security = %v, want 3 entries (anonymous, JWT, API key)", optGet["security"])
	}
}

// TestBuild_EveryAuthedOperationAcceptsBothCredentials walks the whole document
// instead of sampling one operation: the invariant clients depend on is that no
// authenticated operation ever offers the session JWT alone, since the same
// header also carries a workspace-scoped API key.
func TestBuild_EveryAuthedOperationAcceptsBothCredentials(t *testing.T) {
	doc := buildDoc(t, sampleGroups())
	paths := asMap(t, doc["paths"], "paths")

	authed := 0
	for path, item := range paths {
		for method, op := range asMap(t, item, path) {
			sec, ok := asMap(t, op, path+" "+method)["security"].([]any)
			if !ok {
				t.Errorf("%s %s: no security key", method, path)
				continue
			}
			if len(sec) == 0 {
				continue // AuthNone
			}
			authed++
			var jwt, key bool
			for _, req := range sec {
				r := asMap(t, req, "security entry")
				_, hasJWT := r["bearerAuth"]
				_, hasKey := r["apiKeyAuth"]
				jwt = jwt || hasJWT
				key = key || hasKey
			}
			if !jwt || !key {
				t.Errorf("%s %s security = %v, want both bearerAuth and apiKeyAuth", method, path, sec)
			}
		}
	}
	if authed != 4 {
		t.Errorf("checked %d authenticated operations, want 4 (1 optional + 3 required)", authed)
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

func TestBuilder_ManifestRefWiring(t *testing.T) {
	man := manifest{
		Schemas: map[string]json.RawMessage{
			"Thing":  json.RawMessage(`{"type":"object","properties":{"dep":{"$ref":"#/components/schemas/Dep"}}}`),
			"Dep":    json.RawMessage(`{"type":"object"}`),
			"Create": json.RawMessage(`{"type":"object"}`),
			"Unused": json.RawMessage(`{"type":"object"}`),
		},
		Operations: map[string]opModels{
			"rpc.x.get":      {Response: &schemaRef{Ref: "Thing"}},
			"rpc.x.list":     {Response: &schemaRef{Ref: "Thing", Array: true}},
			"rpc.x.cr#thing": {Request: &schemaRef{Ref: "Create"}, Response: &schemaRef{Ref: "Thing"}},
		},
	}
	b := &builder{man: man, refs: map[string]bool{}}

	if got := b.responseSchema(edge.RouteSpec{Queue: "rpc.x.get"}); got["$ref"] != "#/components/schemas/Thing" {
		t.Errorf("single response = %v, want $ref Thing", got)
	}
	arr := b.responseSchema(edge.RouteSpec{Queue: "rpc.x.list"})
	if arr["type"] != "array" {
		t.Errorf("array response = %v, want type array", arr)
	}
	// entity key: rpc.x.cr#thing
	if got := b.responseSchema(edge.RouteSpec{Queue: "rpc.x.cr", Entity: "thing"}); got["$ref"] != "#/components/schemas/Thing" {
		t.Errorf("entity-keyed response = %v, want $ref Thing", got)
	}
	rb := b.requestBody(edge.RouteSpec{Queue: "rpc.x.cr", Entity: "thing", Body: true})
	rbSchema := rb["content"].(map[string]any)["application/json"].(map[string]any)["schema"].(map[string]any)
	if rbSchema["$ref"] != "#/components/schemas/Create" {
		t.Errorf("requestBody schema = %v, want $ref Create", rbSchema)
	}
	// unknown subject -> generic object
	if got := b.responseSchema(edge.RouteSpec{Queue: "rpc.unknown"}); got["type"] != "object" {
		t.Errorf("unknown response = %v, want generic object", got)
	}
	// dangling ref (not in Schemas) -> generic object, no panic
	b2 := &builder{man: manifest{Operations: map[string]opModels{"q": {Response: &schemaRef{Ref: "Missing"}}}}, refs: map[string]bool{}}
	if got := b2.responseSchema(edge.RouteSpec{Queue: "q"}); got["type"] != "object" {
		t.Errorf("dangling ref response = %v, want generic object", got)
	}

	// closure pulls transitive deps (Dep via Thing) but not unreferenced schemas.
	cl := b.closure()
	for _, want := range []string{"Thing", "Dep", "Create"} {
		if !cl[want] {
			t.Errorf("closure missing %q", want)
		}
	}
	if cl["Unused"] {
		t.Error("closure should not include unreferenced Unused")
	}
}

func TestBuilder_QueryParams(t *testing.T) {
	man := manifest{
		Schemas: map[string]json.RawMessage{
			"SortOrder": json.RawMessage(`{"type":"string","enum":["asc","desc"]}`),
		},
		Operations: map[string]opModels{
			"rpc.q.list": {QueryParams: []queryParam{
				{Name: "page", Schema: json.RawMessage(`{"type":"integer","default":1}`)},
				{Name: "order", Schema: json.RawMessage(`{"$ref":"#/components/schemas/SortOrder","default":"asc"}`)},
			}},
		},
	}
	b := &builder{man: man, refs: map[string]bool{}}

	params := b.parameters(edge.RouteSpec{Method: "GET", Pattern: "/x/{id}", Queue: "rpc.q.list"})
	in := map[string]string{}
	for _, p := range params {
		m := p.(map[string]any)
		in[m["name"].(string)] = m["in"].(string)
	}
	if in["id"] != "path" {
		t.Errorf("path param id missing/wrong: %v", in)
	}
	if in["page"] != "query" || in["order"] != "query" {
		t.Errorf("query params missing: %v", in)
	}
	// the enum $ref inside a query-param schema must be seeded + pulled into the closure
	if !b.refs["SortOrder"] {
		t.Error("query-param $ref not seeded into refs")
	}
	if !b.closure()["SortOrder"] {
		t.Error("closure missing the query-param enum")
	}
	// AllQuery note is suppressed once a route has typed query params
	if d := b.description(edge.RouteSpec{Queue: "rpc.q.list", AllQuery: true}); strings.Contains(d, "arbitrary") {
		t.Errorf("AllQuery note should be suppressed when typed: %q", d)
	}
	// fallback: unmapped route falls back to RouteSpec.Query as plain strings
	fb := b.parameters(edge.RouteSpec{Method: "GET", Pattern: "/y", Queue: "rpc.none", Query: []string{"workspace_id"}})
	if len(fb) != 1 || fb[0].(map[string]any)["name"] != "workspace_id" {
		t.Errorf("fallback Query param missing: %v", fb)
	}
}

func keys(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
