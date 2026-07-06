import { headers } from "next/headers";
import workspaceService from "@/services/workspace.service";
import { SITE_NAME, SITE_URL, SITE_URL_OBJ, SITE_FAVICON } from "@/config/site";

export interface SiteMetadata {
  name: string;
  description: string;
  origin: string;
  icon: string;
}

function platformDefaults(origin: string): SiteMetadata {
  return {
    name: SITE_NAME,
    description: `${SITE_NAME} — Overwatch tournament results & stats.`,
    origin,
    icon: SITE_FAVICON
  };
}

/**
 * Per-request SEO metadata, resolved from the tenant host's workspace.
 *
 * On a tenant host, `middleware.ts` (Task 6) injects `x-owt-workspace-id`
 * ahead of the request. When present, the workspace's own SEO fields
 * (`seo_title` / `seo_description` / `icon_url`) drive the page title, OG
 * tags, and favicon, and `origin` becomes the tenant host itself (so
 * `metadataBase`/canonical resolve to that subdomain). On the apex host (no
 * workspace header) — or if anything above fails, including reading the
 * request headers themselves — this falls back to the platform defaults.
 * Never throws: callers can await this unconditionally in
 * `generateMetadata()`.
 */
export async function resolveSiteMetadata(): Promise<SiteMetadata> {
  try {
    const h = await headers();
    const host = (h.get("x-forwarded-host") ?? h.get("host") ?? "").split(",")[0]?.trim();
    const proto = h.get("x-forwarded-proto")?.split(",")[0]?.trim() || "https";
    let origin = SITE_URL_OBJ.origin;
    if (host) {
      try {
        origin = new URL(`${proto}://${host}`).origin;
      } catch {
        origin = SITE_URL_OBJ.origin;
      }
    }

    const wsId = h.get("x-owt-workspace-id");
    if (!wsId) {
      return platformDefaults(origin);
    }

    try {
      const ws = await workspaceService.getById(Number(wsId));
      return {
        name: ws.seo_title ?? ws.name,
        description: ws.seo_description ?? ws.description ?? `${ws.name} — tournaments`,
        origin,
        icon: ws.icon_url ?? SITE_FAVICON
      };
    } catch {
      return platformDefaults(origin);
    }
  } catch {
    return platformDefaults(SITE_URL_OBJ.origin);
  }
}
