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
