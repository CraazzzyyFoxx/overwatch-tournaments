// Single source of truth for the gateway's URL shape.
//
// One API, one origin, one version axis: every gateway path is
// `/api/v{n}/<domain>/...` and the version is always the second segment. There
// is no namespace beside it. The browser uses relative, same-origin paths; the
// server prefixes them with the internal gateway base (NEXT_INTERNAL_API_URL,
// e.g. http://gateway:8080), falling back to the incoming request origin in a
// bare `next dev`.
//
// Domains under the version:
//   /api/v1/{tournaments,users,workspaces,admin,me,...}  app + tournament + parser
//   /api/v1/auth/*            identity, RBAC, API keys
//   /api/v1/balancer/*        team balancer + draft
//   /api/v1/analytics/*       post-tournament analytics
//   /api/v1/streams/*         tournament live streams
//   /api/v1/notifications*    the per-user inbox
//   /api/v1/announcements/*   the per-user announcement feed
//   /api/v1/realtime/ws       realtime WebSocket hub
//
// `/api/v2/*` is the same paths with the RPC envelope as the body; the gateway
// rewrites it onto v1 before routing (gateway/internal/apiver).
//
// Outside the version, on purpose:
//   /api/docs, /api/openapi*.json   the reference — it describes the versions
//   /api/health                     the frontend container's probe
//   /bff/*                          THIS app's own endpoints (cookie auth,
//                                   served by Next, never by the gateway)
//
// The pre-unification spellings (`/api/auth/me`, `/api/balancer/...`) still
// answer, with `Deprecation` + `Sunset` headers, until the date in
// gateway/internal/apiver.SunsetDate. Nothing in this app should use them.

// Internal gateway origin for server-side (SSR + route handlers + middleware)
// fetches. Trailing slash stripped. Undefined when unset (bare next dev).
export function internalApiOrigin(): string | undefined {
  return process.env.NEXT_INTERNAL_API_URL?.replace(/\/$/, "") || undefined;
}

// Absolute auth base for server-side callers that need a concrete URL
// (middleware token refresh, /bff/account route handlers). The gateway serves
// the identity domain under /api/v1/auth. Defaults to the gateway's local dev port
// when NEXT_INTERNAL_API_URL is unset.
export function authServiceBase(): string {
  return `${internalApiOrigin() ?? "http://localhost:8080"}/api/v1/auth`;
}
