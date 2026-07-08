// Derive the PUBLIC host/origin of an incoming request from the proxy's
// forwarded headers.
//
// Behind the edge chain (Traefik/nginx -> gateway -> Next), `request.url`'s
// host is the Next server's INTERNAL bind address (e.g. `0.0.0.0:3000`), not
// the host the browser actually used. Relying on it makes OAuth sign an
// internal origin into the signed state and makes post-login/logout redirects
// point at `0.0.0.0:3000`. The real public host arrives as `x-forwarded-host`
// (the same header `middleware.ts` reads); the scheme as `x-forwarded-proto`.
//
// Falls back to `request.url` for local/dev where there is no proxy and no
// forwarded headers.

// Public host including port if the edge forwards one (e.g. `team.owt…` or
// `test-owt.example.com`). Takes the first value of a comma-joined list.
export function publicHost(request: Request): string {
  const url = new URL(request.url);
  return (request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? url.host)
    .split(",")[0]
    .trim();
}

// Public hostname WITHOUT any port — for comparisons against PLATFORM_ZONE /
// resolveHost().
export function publicHostname(request: Request): string {
  return publicHost(request).split(":")[0];
}

// Full public origin, e.g. `https://test-owt.craazzzyyfoxx.me`. Scheme comes
// from `x-forwarded-proto`, else defaults to https in production (the edge
// always terminates TLS there) and the request scheme in dev.
export function publicOrigin(request: Request): string {
  const url = new URL(request.url);
  const proto =
    request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim() ||
    (process.env.NODE_ENV === "production" ? "https" : url.protocol.replace(/:$/, ""));
  return `${proto}://${publicHost(request)}`;
}
