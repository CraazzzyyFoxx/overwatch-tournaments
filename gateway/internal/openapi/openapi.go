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
	"github.com/CraazzzyyFoxx/anak-tournaments/gateway/internal/rpc"
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

// queryParam is one in:query parameter exported from a Pydantic query model or
// declared explicitly. Schema is the raw OpenAPI schema (may carry a namespaced
// $ref to an enum, which the builder seeds into the components closure).
type queryParam struct {
	Name     string          `json:"name"`
	Required bool            `json:"required"`
	Schema   json.RawMessage `json:"schema"`
}

type opModels struct {
	Request     *schemaRef   `json:"request"`
	Response    *schemaRef   `json:"response"`
	QueryParams []queryParam `json:"query_params"`
	Summary     string       `json:"summary"`
	Description string       `json:"description"`
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

// documentNote is appended to every generated document's info.description.
func documentNote(envelope bool) string {
	errNote := v1ErrorNote
	if envelope {
		errNote = v2ErrorNote
	}
	return versionsNote + authNote + errNote + errorTableMD() + workspaceNote
}

const versionsNote = "\n\n## Versions\n\n" +
	"Every path is `/api/v{n}/<domain>/...` — one version axis, always the second segment. " +
	"There is no namespace beside the version.\n\n" +
	"- **v1** (`/api/v1/...`) — unwrapped JSON, the FastAPI-shaped contract.\n" +
	"- **v2** (`/api/v2/...`) — the same paths, handlers and HTTP status; body is " +
	"`{ok: true, data, warnings?}` or `{ok: false, error: {code, message, details?}}`.\n\n" +
	"Switcher: `/api/docs`. Specs: `/api/openapi.json`, `/api/openapi.v2.json`.\n\n" +
	"**Deprecated spellings.** `auth`, `analytics`, `balancer`, `streams`, `notifications` and " +
	"`announcements` used to sit beside the version (`/api/auth/me`). Those paths still work and " +
	"are rewritten onto the canonical one, but every such response carries `Deprecation: true`, " +
	"a `Sunset` date and a `Link: <canonical>; rel=\"successor-version\"`. They stop being served " +
	"after the sunset date; move the prefix and nothing else changes.\n\n" +
	"The documentation surface (`/api/docs`, `/api/openapi*.json`) sits outside the version " +
	"deliberately — it describes the versions."

const authNote = "\n\n## Authentication\n\n" +
	"Two credential types share the `Authorization: Bearer` header, and every authenticated " +
	"operation below accepts either one (its `security` list is a logical OR).\n\n" +
	"A **session JWT** is the browser credential: short-lived, minted by `POST /api/v1/auth/login` " +
	"and refreshed via `POST /api/v1/auth/refresh`, carrying the caller's full RBAC — global roles " +
	"and permissions plus every workspace they belong to.\n\n" +
	"A **workspace-scoped API key** (`aqt_sk_<public_id>_<secret>`) is the machine credential: " +
	"long-lived, created by `POST /api/v1/auth/api-keys` and shown once. Its authorization is the " +
	"intersection of the scopes granted to the key with what the key's owner actually holds in " +
	"that one workspace, so a key can never outrank its owner and never reaches a second " +
	"workspace. Scopes are RBAC permission names — the same vocabulary the endpoints are " +
	"checked against; the catalog lives in `backend/shared/rbac/catalog.py`. A key carries no " +
	"global permissions and no role names by design, so role-based shortcuts (workspace owner, " +
	"admin) never apply to it.\n\n" +
	"Session-only surfaces: the `/api/v1/auth` operations that act on the caller's own account or " +
	"session — logout, session list and revoke, `/api/v1/auth/me`, password changes, and API-key " +
	"management (creating, updating and revoking keys) — resolve the caller by decoding the " +
	"bearer as a JWT, so an API key is rejected there with 401. " +
	"`GET /api/v1/auth/api-keys/self` is the inverse: it describes the calling key, so it needs a " +
	"key. WebSocket connections (`/ws`, `/api/v1/realtime/ws`) accept either credential, but a key " +
	"only authenticates the socket if it holds at least one grant in its workspace; a " +
	"zero-scope key connects anonymously and cannot subscribe to auth-gated topics."

const v1ErrorNote = "\n\n## Errors\n\n" +
	"HTTP status plus `{detail, code?, fields?, retry_after?}`. `detail` is always present. " +
	"Branch on `code`, show `detail`, never parse `detail`.\n\n" +
	"`fields` is per-item validation (`field`, `msg`, `code`). `retry_after` (seconds) comes " +
	"with 429 and mirrors the `Retry-After` header.\n\n"

const v2ErrorNote = "\n\n## Errors\n\n" +
	"HTTP status plus `{ok: false, error: {code, message, details?}}`. Branch on `error.code`, " +
	"show `error.message`, never parse `error.message`.\n\n" +
	"`error.details.fields` is per-item validation; `error.details.retry_after` comes with 429 " +
	"and mirrors `Retry-After`.\n\n"

const workspaceNote = "\n\n## Workspace scope\n\n" +
	"Workspace-scoped reads take a `workspace_id` query parameter. When the credential is " +
	"pinned to exactly ONE workspace — always true for an API key — it may be omitted and the " +
	"gateway fills it in from the credential. An explicit value always wins, and a credential " +
	"holding several workspaces must send one (the read fails closed rather than guessing a " +
	"tenant)."

type errDoc struct {
	Code  string
	Title string
	When  string
}

// errorCatalog is the public machine-code list. HTTP status is rpc.StatusForCode
// so this table cannot drift from the gateway mapping.
var errorCatalog = []errDoc{
	{"bad_request", "Bad request", "Malformed JSON or a request the gateway rejects before RPC."},
	{"unauthorized", "Not authenticated", "Missing, invalid, or expired bearer. Session-only `/api/v1/auth` routes also return this for an API key."},
	{"forbidden", "Not authorized", "Authenticated, but the credential lacks the permission, workspace, or scope."},
	{"not_found", "Not found", "Unknown id, or an id outside this credential's workspace (no existence leak)."},
	{"conflict", "Conflict", "The current state does not allow the write (already confirmed, duplicate, concurrent update)."},
	{"gone", "Gone", "The resource existed and has been permanently removed."},
	{"payload_too_large", "Payload too large", "Request body exceeded the gateway limit."},
	{"unprocessable", "Validation error", "JSON parsed but failed schema or business validation. See `fields` / `error.details.fields`."},
	{"rate_limited", "Rate limited", "Wait `retry_after` seconds (also sent as `Retry-After`)."},
	{"unavailable", "Unavailable", "A required dependency is down. Retry shortly; this is not an application bug."},
	{"internal", "Internal error", "Unexpected failure. Do not retry blindly on writes."},
}

func errorTableMD() string {
	var b strings.Builder
	b.WriteString("| code | HTTP | when |\n| --- | --- | --- |\n")
	for _, e := range errorCatalog {
		b.WriteString("| `")
		b.WriteString(e.Code)
		b.WriteString("` | ")
		b.WriteString(strconv.Itoa(rpc.StatusForCode(e.Code)))
		b.WriteString(" | ")
		b.WriteString(e.When)
		b.WriteString(" |\n")
	}
	return b.String()
}

func lookupErr(code string) errDoc {
	for _, e := range errorCatalog {
		if e.Code == code {
			return e
		}
	}
	return errDoc{Code: code, Title: code}
}

// Build assembles an OpenAPI 3.1.0 document (indented JSON) from the groups.
// Output is deterministic: encoding/json sorts the paths/methods maps, and the
// tags array follows the declared group order. components.schemas carries only
// the schemas transitively referenced by this document's operations, so the
// public spec never leaks admin-only model shapes.
func Build(info Info, groups []Group) []byte {
	return build(info, groups, false)
}

// BuildV2 is Build with /api/v1 paths rewritten to /api/v2 and every JSON
// response wrapped in the RPC envelope. Since the domains that used to sit
// beside the version (auth, analytics, balancer, streams, notifications,
// announcements) now live inside it, the v2 spec covers the whole surface —
// the filter below no longer silently drops them, and `apiver` really does
// route /api/v2/auth/... through the envelope-aware writers in `apierr`.
func BuildV2(info Info, groups []Group) []byte {
	info.Title = info.Title + " v2"
	return build(info, v2Groups(groups), true)
}

func v2Groups(groups []Group) []Group {
	out := make([]Group, 0, len(groups))
	for _, g := range groups {
		routes := make([]edge.RouteSpec, 0, len(g.Routes))
		for _, r := range g.Routes {
			if !strings.Contains(r.Pattern, "/api/v1") {
				continue
			}
			r.Pattern = strings.Replace(r.Pattern, "/api/v1", "/api/v2", 1)
			routes = append(routes, r)
		}
		if len(routes) == 0 {
			continue
		}
		g.Routes = routes
		out = append(out, g)
	}
	return out
}

func build(info Info, groups []Group, envelope bool) []byte {
	version := info.Version
	if version == "" {
		version = "dev"
	}

	b := &builder{man: loadedManifest, refs: map[string]bool{}, envelope: envelope}
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
			"description": info.Description + documentNote(envelope),
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
	man      manifest
	refs     map[string]bool
	envelope bool
}

// operation builds the OpenAPI operation object for one route.
func (b *builder) operation(route edge.RouteSpec, tag string) map[string]any {
	op := map[string]any{
		"tags":        []any{tag},
		"operationId": operationID(route),
		"summary":     b.summary(route),
		"responses":   b.responses(route),
	}
	if desc := b.description(route); desc != "" {
		op["description"] = desc
	}
	if params := b.parameters(route); len(params) > 0 {
		op["parameters"] = params
	}
	if route.Body {
		op["requestBody"] = b.requestBody(route)
	}
	op["security"] = security(route)
	return op
}

// queryParams returns the manifest-declared query parameters for a route.
func (b *builder) queryParams(route edge.RouteSpec) []queryParam {
	return b.man.Operations[b.key(route)].QueryParams
}

// parameters builds the path parameters (from the pattern placeholders, always
// required) plus query parameters: the typed manifest set when present, else the
// route's explicit Query names as plain strings.
func (b *builder) parameters(route edge.RouteSpec) []any {
	var params []any
	for _, name := range pathParams(convertPattern(route.Pattern)) {
		params = append(params, map[string]any{
			"name":     name,
			"in":       "path",
			"required": true,
			"schema":   map[string]any{"type": "string"},
		})
	}
	if qps := b.queryParams(route); len(qps) > 0 {
		for _, qp := range qps {
			var schema any
			if err := json.Unmarshal(qp.Schema, &schema); err != nil {
				schema = map[string]any{"type": "string"}
			}
			// Pull any enum/model $ref in the param schema into the components closure.
			for _, m := range refRe.FindAllSubmatch(qp.Schema, -1) {
				b.refs[string(m[1])] = true
			}
			param := map[string]any{"name": qp.Name, "in": "query", "required": qp.Required, "schema": schema}
			params = append(params, param)
		}
		return params
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

// description renders the authored description (from the manifest) plus — only
// when the route has no typed query parameters — the arbitrary-query caveat, and
// a footer carrying the RPC subject for traceability.
func (b *builder) description(route edge.RouteSpec) string {
	var parts []string
	if d := b.man.Operations[b.key(route)].Description; d != "" {
		parts = append(parts, d)
	}
	if route.AllQuery && len(b.queryParams(route)) == 0 {
		parts = append(parts, "Accepts arbitrary query parameters (pagination/filtering); see the service for the full list.")
	}
	if route.Queue != "" {
		parts = append(parts, "RPC subject: `"+route.Queue+"`")
	}
	return strings.Join(parts, "\n\n")
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
	inner := map[string]any{"type": "object"}
	if op, ok := b.man.Operations[b.key(route)]; ok && op.Response != nil {
		if s := b.refSchema(*op.Response); s != nil {
			inner = s
		}
	}
	if !b.envelope {
		return inner
	}
	return map[string]any{
		"type":     "object",
		"required": []any{"ok", "data"},
		"properties": map[string]any{
			"ok":   map[string]any{"type": "boolean", "enum": []any{true}},
			"data": inner,
			"warnings": map[string]any{
				"type":  "array",
				"items": map[string]any{"$ref": "#/components/schemas/Warning"},
			},
		},
	}
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

// responses builds the success response plus the errors every route can
// actually produce. 401/403 only on AuthRequired; 429 is gateway-global.
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
		"404":                errorResponse("not_found", errContent),
		"422":                errorResponse("unprocessable", errContent),
		"429":                errorResponse("rate_limited", errContent),
		"500":                errorResponse("internal", errContent),
	}
	if route.Auth == edge.AuthRequired {
		resp["401"] = errorResponse("unauthorized", errContent)
		resp["403"] = errorResponse("forbidden", errContent)
	}
	return resp
}

func errorResponse(code string, content map[string]any) map[string]any {
	e := lookupErr(code)
	resp := map[string]any{
		"description": e.Title + " (`" + e.Code + "`). " + e.When,
		"content":     content,
	}
	if code == "rate_limited" {
		resp["headers"] = map[string]any{
			"Retry-After": map[string]any{
				"description": "Seconds to wait before retrying. Mirrors `retry_after` in the body.",
				"schema":      map[string]any{"type": "integer", "minimum": 1},
			},
		}
	}
	return resp
}

// components builds components.schemas (Error + the transitive closure of every
// referenced model) and the two bearer security schemes.
func (b *builder) components() map[string]any {
	schemas := map[string]any{
		"Error": b.errorSchema(),
	}
	if b.envelope {
		schemas["Warning"] = map[string]any{
			"type":     "object",
			"required": []any{"code", "message"},
			"properties": map[string]any{
				"code":    map[string]any{"type": "string"},
				"message": map[string]any{"type": "string"},
				"field":   map[string]any{"type": []any{"string", "null"}},
			},
		}
	}
	for name := range b.closure() {
		var raw any
		if err := json.Unmarshal(b.man.Schemas[name], &raw); err == nil {
			schemas[name] = raw
		}
	}
	return map[string]any{
		// Both credentials ride the same `Authorization: Bearer` header, so both
		// are `type: http, scheme: bearer` and only the description distinguishes
		// them. Deliberately NOT modelled as `type: apiKey, in: header`: that
		// would make generated clients send a bare header value without the
		// `Bearer ` scheme, which the gateway rejects.
		"securitySchemes": map[string]any{
			"bearerAuth": map[string]any{
				"type":         "http",
				"scheme":       "bearer",
				"bearerFormat": "JWT",
				"description":  "Session JWT access token. REST operations read it from this header only; the `owt_access_token` cookie (legacy `aqt_access_token` as a fallback) and the `?token=Bearer <jwt>` query parameter authenticate WebSocket connections.",
			},
			"apiKeyAuth": map[string]any{
				"type":         "http",
				"scheme":       "bearer",
				"bearerFormat": "aqt_sk_<public_id>_<secret>",
				"description":  "Workspace-scoped API key, issued by `POST /api/v1/auth/api-keys` and shown once at creation. Sent as `Authorization: Bearer aqt_sk_...` — the same header as the session JWT. A key's scopes are RBAC permission names (`team.create`, `registration.approve`, `admin.*`) from the permission catalog, and its effective authorization is those scopes intersected with what the key's owner holds in that single workspace: a key can never exceed its owner's rights and never reaches another workspace.",
			},
		},
		"schemas": schemas,
	}
}

func (b *builder) errorSchema() map[string]any {
	codeSchema := map[string]any{
		"type":        "string",
		"description": "Machine reason. Branch on this; do not parse the human message. Known values are listed under Errors in info.description; workers may emit others.",
	}
	if b.envelope {
		return map[string]any{
			"type":     "object",
			"required": []any{"ok", "error"},
			"description": "v2 error envelope. HTTP status still carries the outcome; " +
				"`error.code` is the machine reason; `error.details` is optional structured data " +
				"(fields, retry_after).",
			"properties": map[string]any{
				"ok": map[string]any{"type": "boolean", "enum": []any{false}},
				"error": map[string]any{
					"type":     "object",
					"required": []any{"code", "message"},
					"properties": map[string]any{
						"code":    codeSchema,
						"message": map[string]any{"type": "string", "description": "Human message. Show it; never parse it."},
						"details": map[string]any{
							"type":        "object",
							"description": "Optional structured data. Recognized keys: `fields`, `retry_after`.",
						},
					},
				},
			},
			"examples": []any{
				map[string]any{"ok": false, "error": map[string]any{"code": "not_found", "message": "Not found"}},
				map[string]any{"ok": false, "error": map[string]any{
					"code": "rate_limited", "message": "Too many requests",
					"details": map[string]any{"retry_after": 60},
				}},
			},
		}
	}
	return map[string]any{
		"type": "object",
		"description": "Error envelope. `detail` is the human message and is always present; " +
			"`code` is the machine reason; `fields` carries per-item validation/business detail; " +
			"`retry_after` (seconds) accompanies 429 and mirrors the Retry-After header.",
		"properties": map[string]any{
			"detail": map[string]any{"type": "string", "description": "Human message. Show it; never parse it."},
			"code":   codeSchema,
			"retry_after": map[string]any{
				"type":        "integer",
				"description": "Seconds to wait before retrying (429 only).",
			},
			"fields": map[string]any{
				"type":        "array",
				"description": "Per-item detail: which input was rejected and why.",
				"items": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"field": map[string]any{"type": []any{"string", "null"}},
						"msg":   map[string]any{"type": "string"},
						"code":  map[string]any{"type": "string"},
					},
					"required": []any{"msg", "code"},
				},
			},
		},
		"required": []any{"detail"},
		"examples": []any{
			map[string]any{"detail": "Not found", "code": "not_found"},
			map[string]any{"detail": "Too many requests", "code": "rate_limited", "retry_after": 60},
			map[string]any{
				"detail": "Validation error",
				"code":   "unprocessable",
				"fields": []any{map[string]any{"field": "name", "msg": "Field required", "code": "missing"}},
			},
		},
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

// summary returns the human-readable operation title: an authored summary from
// the manifest, else one auto-derived from the route (CRUD action + entity, or
// the RPC subject's last segment). The raw RPC subject is no longer the title —
// it moves to operationId + the description footer.
func (b *builder) summary(route edge.RouteSpec) string {
	if s := b.man.Operations[b.key(route)].Summary; s != "" {
		return s
	}
	return autoSummary(route)
}

func autoSummary(route edge.RouteSpec) string {
	if route.Entity != "" && route.Action != "" {
		return titleFirst(route.Action) + " " + strings.ReplaceAll(route.Entity, "_", " ")
	}
	if route.Queue == "" {
		return route.Method + " " + route.Pattern
	}
	seg := route.Queue[strings.LastIndexByte(route.Queue, '.')+1:]
	words := strings.Split(seg, "_")
	if len(words) > 0 {
		words[0] = titleFirst(words[0])
	}
	return strings.Join(words, " ")
}

func titleFirst(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

// operationID is unique per (method, path) within a document.
func operationID(route edge.RouteSpec) string {
	return sanitize(strings.ToLower(route.Method) + "_" + convertPattern(route.Pattern))
}

// security maps the RouteSpec auth mode onto an OpenAPI security requirement.
// AuthNone returns an explicit empty list — a valid "no auth required" override
// that also satisfies strict linters (every operation has security defined).
//
// An authenticated route lists both schemes: the security array is a logical OR,
// and the gateway accepts either credential on the same header, so a generated
// client must know a key is as valid as a session JWT here.
//
// The requirement arrays are intentionally EMPTY rather than carrying the
// route's required permission as an OAuth-style scope list. The permission a
// route needs is asserted imperatively inside the Python worker that serves the
// RPC subject; there is no machine-readable per-route source to derive it from,
// so hand-annotating ~460 operations here would create a second declaration that
// drifts out of step with the enforcement the moment either side changes. The
// document points readers at the permission catalog instead
// (backend/shared/rbac/catalog.py). Do not "fix" this by adding scope literals
// unless the worker-side requirement becomes exportable the way request/response
// schemas already are (see schemas.json).
func security(route edge.RouteSpec) []any {
	bearer := map[string]any{"bearerAuth": []any{}}
	apiKey := map[string]any{"apiKeyAuth": []any{}}
	switch route.Auth {
	case edge.AuthRequired:
		return []any{bearer, apiKey}
	case edge.AuthOptional:
		return []any{map[string]any{}, bearer, apiKey}
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
