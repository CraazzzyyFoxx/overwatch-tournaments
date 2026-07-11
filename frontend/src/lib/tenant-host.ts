import { headers } from "next/headers";

/**
 * True when the current request is served on a white-label tenant host — a
 * workspace subdomain or a verified custom domain — per the `x-owt-host-mode`
 * header that `middleware.ts` sets (and strips on the platform apex). Server-only.
 *
 * Fail-safe: returns `false` (platform behaviour) if headers are unavailable.
 */
export async function isTenantHost(): Promise<boolean> {
  try {
    return (await headers()).get("x-owt-host-mode") === "tenant";
  } catch {
    return false;
  }
}
