// Single source of truth for the gateway's URL namespaces.
//
// Every backend domain lives behind one gateway (one origin), so the path
// prefix IS the domain — there is no per-service base URL. The browser uses
// relative, same-origin paths; the server prefixes them with the internal
// gateway base (NEXT_INTERNAL_API_URL, e.g. http://gateway:8080), falling back
// to the incoming request origin in a bare `next dev`.
//
// Domain namespaces exposed by the gateway:
//   /api/v1/*        app + tournament + parser (the main API)
//   /api/balancer/*  team balancer + draft
//   /api/analytics/* analytics
//   /api/auth/*      identity / auth
//   /api/realtime/ws realtime WebSocket hub

// Internal gateway origin for server-side (SSR + route handlers + middleware)
// fetches. Trailing slash stripped. Undefined when unset (bare next dev).
export function internalApiOrigin(): string | undefined {
  return process.env.NEXT_INTERNAL_API_URL?.replace(/\/$/, "") || undefined;
}

// Absolute auth base for server-side callers that need a concrete URL
// (middleware token refresh, /api/account route handlers). The gateway serves
// the identity domain under /api/auth. Defaults to the gateway's local dev port
// when NEXT_INTERNAL_API_URL is unset.
export function authServiceBase(): string {
  return `${internalApiOrigin() ?? "http://localhost:8080"}/api/auth`;
}
