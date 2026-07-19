export const PLATFORM_ZONE = "owt.craazzzyyfoxx.me";

const RESERVED = new Set([
  "www", "api", "auth", "admin", "app", "assets", "static", "cdn", "mail", "ws",
]);

export type HostResolution = { mode: "platform" } | { mode: "tenant"; host: string };

const IP_RE = /^\d{1,3}(?:\.\d{1,3}){3}$/;

// Resolves the Host header to either the platform (apex/www/localhost/IP/
// no-dot/reserved-subdomain) or a tenant, in which case `host` is the full
// lowercased host to look up — a platform-zone subdomain OR an arbitrary
// custom domain. The backend `by_host` lookup (Task 3) decides which one it
// actually is; this function only filters out hosts that can never be a
// tenant.
export function resolveHost(host: string | null | undefined): HostResolution {
  if (!host) return { mode: "platform" };
  const hostname = host.trim().toLowerCase().split(":")[0];
  if (!hostname || hostname === "localhost" || IP_RE.test(hostname) || !hostname.includes(".")) {
    return { mode: "platform" };
  }
  if (hostname === PLATFORM_ZONE || hostname === `www.${PLATFORM_ZONE}`) return { mode: "platform" };
  const suffix = `.${PLATFORM_ZONE}`;
  if (hostname.endsWith(suffix)) {
    const label = hostname.slice(0, -suffix.length);
    if (!label || label.includes(".") || RESERVED.has(label)) return { mode: "platform" };
  }
  // Subdomain or custom domain — the backend by_host decides which.
  return { mode: "tenant", host: hostname };
}

// True when `host` can carry a `Domain=.owt.craazzzyyfoxx.me` session cookie —
// i.e. it IS the platform apex or a `*.owt.craazzzyyfoxx.me` subdomain. A custom
// domain is a foreign registrable domain and the browser rejects that cookie, so
// its session cookies MUST be host-only (no Domain). Use this to pick the cookie
// Domain wherever a session cookie is set/refreshed. Mirrors backend
// is_platform_host.
export function isPlatformHost(host: string | null | undefined): boolean {
  if (!host) return false;
  const hostname = host.trim().toLowerCase().split(":")[0];
  return hostname === PLATFORM_ZONE || hostname.endsWith(`.${PLATFORM_ZONE}`);
}
