/**
 * Cross-workspace ("all workspaces") reads for the public player statistics —
 * the users index, a player profile, the hero leaderboard and the achievement
 * catalogue.
 *
 * The mode is opt-in through `?scope=all` and exists only on the platform apex
 * host; a tenant (white-label) host is one workspace by definition, so the
 * scope is always resolved server-side (see `resolveStatsScope` in
 * `@/lib/site/tenant-host`) and handed to the client as a prop — never
 * re-derived in the browser, where the host lock lands one effect too late.
 *
 * Client-safe: this module must not import `next/headers`.
 */
export type StatsScope = "workspace" | "all";

/** Server-resolved scope plus whether the toggle exists on this host at all. */
export interface StatsScopeState {
  scope: StatsScope;
  /** `false` on a tenant host: no cross-workspace mode, no toggle. */
  available: boolean;
}

export const WORKSPACE_SCOPE: StatsScopeState = { scope: "workspace", available: false };

/**
 * The `workspace_id` query fragment for a scoped read. `all` is the backend's
 * cross-workspace sentinel; in workspace mode the fragment is empty so
 * `apiFetch` keeps injecting the ambient workspace.
 */
export function scopeQuery(scope: StatsScope | undefined): { workspace_id?: "all" } {
  return scope === "all" ? { workspace_id: "all" } : {};
}

/** Carries the mode across an internal link (users index row → profile). */
export function scopeHref(href: string, scope: StatsScope): string {
  if (scope !== "all") return href;
  return `${href}${href.includes("?") ? "&" : "?"}scope=all`;
}
