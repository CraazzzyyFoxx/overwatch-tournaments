// Package openapi generates an OpenAPI 3.1 document from the gateway's own
// route tables ([]edge.RouteSpec) and serves it behind a Scalar API-reference
// UI. The gateway is the single source of truth for which HTTP endpoints exist,
// so the document is derived — not hand-authored — and stays in sync as routes
// are added.
//
// Scope: paths, methods, path/query parameters, auth requirements (security),
// tags and success status are all derived from the RouteSpec. Request/response
// bodies are rendered as a generic object — the concrete schemas live in the
// Python workers (Pydantic) and the gateway never sees their types. The intent
// is an internal API explorer ("what endpoints exist + try them"), not a
// contract schema.
package openapi

import (
	"encoding/json"
	"strconv"
	"strings"

	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/edge"
)

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
// tags array follows the declared group order.
func Build(info Info, groups []Group) []byte {
	version := info.Version
	if version == "" {
		version = "dev"
	}

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
			item[strings.ToLower(route.Method)] = operation(route, g.Tag)
		}
	}

	doc := map[string]any{
		"openapi": "3.1.0",
		"info": map[string]any{
			"title":       info.Title,
			"version":     version,
			"description": info.Description,
		},
		"servers": []any{map[string]any{"url": "/"}},
		"tags":    tags,
		"paths":   paths,
		"components": map[string]any{
			"securitySchemes": map[string]any{
				"bearerAuth": map[string]any{
					"type":         "http",
					"scheme":       "bearer",
					"bearerFormat": "JWT",
					"description":  "JWT access token. Also accepted via the `aqt_access_token` cookie or a `?token=Bearer <jwt>` query parameter.",
				},
			},
			"schemas": map[string]any{
				"Error": map[string]any{
					"type":        "object",
					"description": "FastAPI-style error envelope.",
					"properties": map[string]any{
						"detail": map[string]any{"type": "string"},
					},
					"required": []any{"detail"},
				},
			},
		},
	}

	out, _ := json.MarshalIndent(doc, "", "  ")
	return out
}

// operation builds the OpenAPI operation object for one route.
func operation(route edge.RouteSpec, tag string) map[string]any {
	op := map[string]any{
		"tags":        []any{tag},
		"operationId": operationID(route),
		"summary":     summary(route),
		"responses":   responses(route),
	}
	if desc := description(route); desc != "" {
		op["description"] = desc
	}
	if params := parameters(route); len(params) > 0 {
		op["parameters"] = params
	}
	if route.Body {
		op["requestBody"] = map[string]any{
			"required": true,
			"content": map[string]any{
				"application/json": map[string]any{
					"schema": map[string]any{"type": "object"},
				},
			},
		}
	}
	op["security"] = security(route)
	return op
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

// responses builds the success response plus a small set of generic errors.
func responses(route edge.RouteSpec) map[string]any {
	status := route.Success
	if status == 0 {
		status = 200
	}

	success := map[string]any{"description": "Success"}
	if status != 204 {
		success["content"] = map[string]any{
			"application/json": map[string]any{
				"schema": map[string]any{"type": "object"},
			},
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
