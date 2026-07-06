export const PLATFORM_ZONE = "owt.craazzzyyfoxx.me";

const RESERVED = new Set([
  "www", "api", "auth", "admin", "app", "assets", "static", "cdn", "mail", "ws",
]);

export type HostResolution = { mode: "platform" } | { mode: "tenant"; subdomain: string };

export function resolveHost(host: string | null | undefined): HostResolution {
  if (!host) return { mode: "platform" };
  const hostname = host.trim().toLowerCase().split(":")[0];
  const suffix = `.${PLATFORM_ZONE}`;
  if (!hostname.endsWith(suffix)) return { mode: "platform" };
  const label = hostname.slice(0, -suffix.length);
  if (!label || label.includes(".") || RESERVED.has(label)) return { mode: "platform" };
  return { mode: "tenant", subdomain: label };
}
