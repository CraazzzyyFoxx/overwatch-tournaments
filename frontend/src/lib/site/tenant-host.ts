import { cookies, headers } from "next/headers";
import { STATS_SCOPE_COOKIE, type StatsScope } from "@/lib/site/stats-scope";
import workspaceService from "@/services/workspace.service";

/**
 * True when the current request is served on a white-label tenant host — a
 * workspace subdomain or a verified custom domain — per the `x-owt-host-mode`
 * header that `proxy.ts` sets (and strips on the platform apex). Server-only.
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

/**
 * The saved public viewing scope. First visits span all communities on the
 * platform; a tenant host always overrides the preference with its own scope.
 * Server-only.
 */
export async function resolveStatsScope(): Promise<StatsScope> {
  if (await isTenantHost()) return "workspace";
  try {
    return (await cookies()).get(STATS_SCOPE_COOKIE)?.value === "workspace" ? "workspace" : "all";
  } catch {
    return "all";
  }
}

/** Tenant (white-label) host branding: the host community's avatar source. */
export interface TenantWorkspaceBranding {
  id: number;
  name: string;
  icon_url: string | null;
}

/**
 * The host workspace's branding on a tenant (white-label) host, resolved from
 * the `x-owt-workspace-id` header that `proxy.ts` injects. `null` on the
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
    return { id: workspace.id, name: workspace.name, icon_url: workspace.icon_url };
  } catch {
    return null;
  }
}
