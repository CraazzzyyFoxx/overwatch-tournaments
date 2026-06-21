// Package openapi generates an OpenAPI 3.1 document from the gateway's own
// route tables ([]edge.RouteSpec) and serves it behind a Scalar API-reference
// UI. The gateway is the single source of truth for which HTTP endpoints exist,
// so the document is derived — not hand-authored — and stays in sync as routes
// are added.
//
// Scope: paths, methods, path/query parameters, auth requirements (security),
// tags and success status are derived from the RouteSpec. Request/response body
// SCHEMAS come from schemas.json — a manifest exported from the Python services'
// Pydantic models (see backend/scripts/export_openapi_schemas.py), keyed by RPC
// subject. Endpoints without a manifest entry fall back to a generic object.
package openapi

import (
	_ "embed"
	"encoding/json"
	"regexp"
	"strconv"
	"strings"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

// schemasJSON is the Pydantic-derived schema manifest. Regenerate with
// backend/scripts/export_openapi_schemas.sh.
//
//go:embed schemas.json
var schemasJSON []byte

// schemaRef points at one component schema; Array wraps it as an array (a raw
// list[...] return — a Paginated[...] wrapper is itself a model, not an array).
type schemaRef struct {
	Ref   string `json:"ref"`
	Array bool   `json:"array"`
}

type opModels struct {
	Request  *schemaRef `json:"request"`
	Response *schemaRef `json:"response"`
}

// manifest is the parsed schemas.json: a flat schema pool + per-subject models.
type manifest struct {
	Schemas    map[string]json.RawMessage `json:"schemas"`
	Operations map[string]opModels        `json:"operations"`
}

var loadedManifest = loadManifest()

func loadManifest() manifest {
	m := manifest{Schemas: map[string]json.RawMessage{}, Operations: map[string]opModels{}}
	if len(schemasJSON) > 0 {
		_ = json.Unmarshal(schemasJSON, &m)
	}
	return m
}

// Info is the top-level metadata for the generated document.
type Info struct {
	Title       string
	Version     string
	Description string
}

// Group is a tagged set of routes rendered as one section (OpenAPI tag) in the
// Scalar sidebar.
type Group struct {
	Tag         string
	Description string
	Routes      []edge.RouteSpec
}

// PublicOnly returns the routes that do not require authentication
// (AuthNone/AuthOptional). Used to split a mixed route table across the
// public/admin specs.
func PublicOnly(routes []edge.RouteSpec) []edge.RouteSpec {
	out := make([]edge.RouteSpec, 0, len(routes))
	for _, r := range routes {
		if r.Auth != edge.AuthRequired {
			out = append(out, r)
		}
	}
	return out
}

// AuthedOnly returns the routes that require authentication (AuthRequired).
func AuthedOnly(routes []edge.RouteSpec) []edge.RouteSpec {
	out := make([]edge.RouteSpec, 0, len(routes))
	for _, r := range routes {
		if r.Auth == edge.AuthRequired {
			out = append(out, r)
		}
	}
	return out
}

// Build assembles an OpenAPI 3.1.0 document (indented JSON) from the groups.
// Output is deterministic: encoding/json sorts the paths/methods maps, and the
// tags array follows the declared group order. components.schemas carries only
// the schemas transitively referenced by this document's operations, so the
// public spec never leaks admin-only model shapes.
func Build(info Info, groups []Group) []byte {
	version := info.Version
	if version == "" {
		version = "dev"
	}

	b := &builder{man: loadedManifest, refs: map[string]bool{}}
	tags := make([]any, 0, len(groups))
	paths := map[string]any{}

	for _, g := range groups {
		tag := map[string]any{"name": g.Tag}
		if g.Description != "" {
			tag["description"] = g.Description
		}
		tags = append(tags, tag)

		for _, route := range g.Routes {
			p := convertPattern(route.Pattern)
			item, ok := paths[p].(map[string]any)
			if !ok {
				item = map[string]any{}
				paths[p] = item
			}
			item[strings.ToLower(route.Method)] = b.operation(route, g.Tag)
		}
	}

	doc := map[string]any{
		"openapi": "3.1.0",
		"info": map[string]any{
			"title":       info.Title,
			"version":     version,
			"description": info.Description,
		},
		"servers":    []any{map[string]any{"url": "/"}},
		"tags":       tags,
		"paths":      paths,
		"components": b.components(),
	}

	out, _ := json.MarshalIndent(doc, "", "  ")
	return out
}

// builder carries the manifest and accumulates the set of referenced schema
// names while operations are generated.
type builder struct {
	man  manifest
	refs map[string]bool
}

// operation builds the OpenAPI operation object for one route.
func (b *builder) operation(route edge.RouteSpec, tag string) map[string]any {
	op := map[string]any{
		"tags":        []any{tag},
		"operationId": operationID(route),
		"summary":     summary(route),
		"responses":   b.responses(route),
	}
	if desc := description(route); desc != "" {
		op["description"] = desc
	}
	if params := parameters(route); len(params) > 0 {
		op["parameters"] = params
	}
	if route.Body {
		op["requestBody"] = b.requestBody(route)
	}
	op["security"] = security(route)
	return op
}

// key is the manifest lookup key: the RPC subject, suffixed with the entity for
// the shared generic-CRUD engine (one subject, many entities).
func (b *builder) key(route edge.RouteSpec) string {
	if route.Entity != "" {
		return route.Queue + "#" + route.Entity
	}
	return route.Queue
}

// refSchema renders a schemaRef as an OpenAPI schema and records the reference.
// Returns nil if the schema is unknown (so callers fall back to a generic object
// rather than emit a dangling $ref).
func (b *builder) refSchema(sr schemaRef) map[string]any {
	if sr.Ref == "" || b.man.Schemas[sr.Ref] == nil {
		return nil
	}
	b.refs[sr.Ref] = true
	ref := map[string]any{"$ref": "#/components/schemas/" + sr.Ref}
	if sr.Array {
		return map[string]any{"type": "array", "items": ref}
	}
	return ref
}

func (b *builder) responseSchema(route edge.RouteSpec) map[string]any {
	if op, ok := b.man.Operations[b.key(route)]; ok && op.Response != nil {
		if s := b.refSchema(*op.Response); s != nil {
			return s
		}
	}
	return map[string]any{"type": "object"}
}

func (b *builder) requestBody(route edge.RouteSpec) map[string]any {
	schema := map[string]any{"type": "object"}
	if op, ok := b.man.Operations[b.key(route)]; ok && op.Request != nil {
		if s := b.refSchema(*op.Request); s != nil {
			schema = s
		}
	}
	return map[string]any{
		"required": true,
		"content":  map[string]any{"application/json": map[string]any{"schema": schema}},
	}
}

// responses builds the success response plus a small set of generic errors.
func (b *builder) responses(route edge.RouteSpec) map[string]any {
	status := route.Success
	if status == 0 {
		status = 200
	}

	success := map[string]any{"description": "Success"}
	if status != 204 {
		success["content"] = map[string]any{
			"application/json": map[string]any{"schema": b.responseSchema(route)},
		}
	}

	errContent := map[string]any{
		"application/json": map[string]any{
			"schema": map[string]any{"$ref": "#/components/schemas/Error"},
		},
	}
	resp := map[string]any{
		strconv.Itoa(status): success,
		"404":                map[string]any{"description": "Not found", "content": errContent},
		"422":                map[string]any{"description": "Validation error", "content": errContent},
		"500":                map[string]any{"description": "Internal error", "content": errContent},
	}
	if route.Auth == edge.AuthRequired {
		resp["401"] = map[string]any{"description": "Not authenticated", "content": errContent}
	}
	return resp
}

// components builds components.schemas (Error + the transitive closure of every
// referenced model) and the bearer security scheme.
func (b *builder) components() map[string]any {
	schemas := map[string]any{
		"Error": map[string]any{
			"type":        "object",
			"description": "FastAPI-style error envelope.",
			"properties":  map[string]any{"detail": map[string]any{"type": "string"}},
			"required":    []any{"detail"},
		},
	}
	for name := range b.closure() {
		var raw any
		if err := json.Unmarshal(b.man.Schemas[name], &raw); err == nil {
			schemas[name] = raw
		}
	}
	return map[string]any{
		"securitySchemes": map[string]any{
			"bearerAuth": map[string]any{
				"type":         "http",
				"scheme":       "bearer",
				"bearerFormat": "JWT",
				"description":  "JWT access token. Also accepted via the `aqt_access_token` cookie or a `?token=Bearer <jwt>` query parameter.",
			},
		},
		"schemas": schemas,
	}
}

var refRe = regexp.MustCompile(`#/components/schemas/([^"]+)`)

// closure expands the recorded refs to every schema they transitively depend on.
func (b *builder) closure() map[string]bool {
	out := map[string]bool{}
	stack := make([]string, 0, len(b.refs))
	for n := range b.refs {
		stack = append(stack, n)
	}
	for len(stack) > 0 {
		n := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		raw, ok := b.man.Schemas[n]
		if out[n] || !ok {
			continue
		}
		out[n] = true
		for _, m := range refRe.FindAllSubmatch(raw, -1) {
			dep := string(m[1])
			if !out[dep] {
				stack = append(stack, dep)
			}
		}
	}
	return out
}

// summary uses the RPC queue (the subject the request is dispatched to) when
// present, falling back to "METHOD /path" for manually-wired routes.
func summary(route edge.RouteSpec) string {
	if route.Queue != "" {
		return route.Queue
	}
	return route.Method + " " + route.Pattern
}

// description surfaces the generic-CRUD entity/action and the arbitrary-query
// caveat, since neither is expressible as a typed parameter/schema.
func description(route edge.RouteSpec) string {
	var parts []string
	if route.Entity != "" || route.Action != "" {
		parts = append(parts, "Generic CRUD: entity="+route.Entity+" action="+route.Action+".")
	}
	if route.AllQuery {
		parts = append(parts, "Accepts arbitrary query parameters (pagination/filtering); see the service for the full list.")
	}
	return strings.Join(parts, " ")
}

// operationID is unique per (method, path) within a document.
func operationID(route edge.RouteSpec) string {
	return sanitize(strings.ToLower(route.Method) + "_" + convertPattern(route.Pattern))
}

// parameters builds the path parameters (from the pattern placeholders, always
// required) plus any explicitly-declared query parameters (optional).
func parameters(route edge.RouteSpec) []any {
	var params []any
	for _, name := range pathParams(convertPattern(route.Pattern)) {
		params = append(params, map[string]any{
			"name":     name,
			"in":       "path",
			"required": true,
			"schema":   map[string]any{"type": "string"},
		})
	}
	for _, name := range route.Query {
		params = append(params, map[string]any{
			"name":     name,
			"in":       "query",
			"required": false,
			"schema":   map[string]any{"type": "string"},
		})
	}
	return params
}

// security maps the RouteSpec auth mode onto an OpenAPI security requirement.
// AuthNone returns an explicit empty list — a valid "no auth required" override
// that also satisfies strict linters (every operation has security defined).
func security(route edge.RouteSpec) []any {
	bearer := map[string]any{"bearerAuth": []any{}}
	switch route.Auth {
	case edge.AuthRequired:
		return []any{bearer}
	case edge.AuthOptional:
		return []any{map[string]any{}, bearer}
	default:
		return []any{}
	}
}

// convertPattern turns a ServeMux pattern into an OpenAPI path template: the
// trailing-wildcard form "{name...}" becomes a plain "{name}". The simple
// "{name}" placeholder syntax is identical in both.
func convertPattern(pattern string) string {
	return strings.ReplaceAll(pattern, "...}", "}")
}

// pathParams extracts the {name} placeholders from a path template, in order.
func pathParams(pattern string) []string {
	var out []string
	for {
		open := strings.IndexByte(pattern, '{')
		if open < 0 {
			return out
		}
		end := strings.IndexByte(pattern[open:], '}')
		if end < 0 {
			return out
		}
		end += open
		out = append(out, pattern[open+1:end])
		pattern = pattern[end+1:]
	}
}

// sanitize keeps only identifier-safe runes, collapsing the rest to '_'.
func sanitize(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
			b.WriteRune(r)
		default:
			b.WriteByte('_')
		}
	}
	return b.String()
}
