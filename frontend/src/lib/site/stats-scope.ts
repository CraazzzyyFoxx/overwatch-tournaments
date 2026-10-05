/**
 * Cross-workspace ("all workspaces") reads for the public site: every browse
 * page except the Play section (scrims and mixes are hosted inside one
 * workspace). `/` and `/statistics` are platform-wide on the apex already.
 *
 * The mode is a visitor preference stored in {@link STATS_SCOPE_COOKIE} and
 * toggled from the workspace switcher. It exists only on the platform apex
 * host; a tenant (white-label) host is one workspace by definition, so the
 * scope is always resolved server-side (see `resolveStatsScope` in
 * `@/lib/site/tenant-host`) and handed to the client as a prop.
 *
 * Client-safe: this module must not import `next/headers`.
 */
export type StatsScope = "workspace" | "all";

export const STATS_SCOPE_COOKIE = "owt-stats-scope";

/**
 * The `workspace_id` query fragment for a scoped read. `all` is the backend's
 * cross-workspace sentinel; in workspace mode the fragment is empty so
 * `apiFetch` keeps injecting the ambient workspace.
 */
export function scopeQuery(scope: StatsScope | undefined): { workspace_id?: "all" } {
  return scope === "all" ? { workspace_id: "all" } : {};
}
