import { headers } from "next/headers";
import workspaceService from "@/services/workspace.service";

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

/** Tenant (white-label) host branding: the host workspace's name + icon. */
export interface TenantWorkspaceBranding {
  name: string;
  iconUrl: string | null;
}

/**
 * The host workspace's branding on a tenant (white-label) host, resolved from
 * the `x-owt-workspace-id` header that `middleware.ts` injects. `null` on the
 * platform apex host or on any failure (fail-safe: platform branding).
 * Server-only.
 */
export async function resolveTenantWorkspace(): Promise<TenantWorkspaceBranding | null> {
  try {
    const h = await headers();
    if (h.get("x-owt-host-mode") !== "tenant") return null;
    const raw = h.get("x-owt-workspace-id");
    const id = raw ? Number(raw) : NaN;
    if (!Number.isFinite(id)) return null;
    const workspace = await workspaceService.getById(id);
    return { name: workspace.name, iconUrl: workspace.icon_url };
  } catch {
    return null;
  }
}
