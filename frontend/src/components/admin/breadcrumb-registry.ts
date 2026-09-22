import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";

/**
 * Detail routes whose numeric id segment can be resolved to a real entity name.
 *
 * The breadcrumb only READS the query cache (`skipToken` never fetches), so a
 * key listed here that nobody has populated yet simply falls back to the
 * generic label — which is why the registry can name the key a screen WILL use
 * before that screen exists.
 *
 * `workspaceId` is passed because some detail queries are workspace-scoped
 * (an achievement rule is), and the breadcrumb has no other way to reach it.
 */
export const BREADCRUMB_ENTITIES: Record<
  string,
  (id: number, workspaceId: number | null) => readonly unknown[]
> = {
  tournaments: (id) => getTournamentWorkspaceQueryKeys(id).tournament,
  // Same key as the team workspace query (admin/teams/[id]/page.tsx).
  teams: (id) => ["admin", "team", id] as const,
  people: (id) => ["admin", "person", id] as const,
  achievements: (id, workspaceId) => ["admin", "achievement-rule", workspaceId, id] as const,
  workspaces: (id) => ["admin-workspace", id] as const,
};

/**
 * Labels for path segments the kebab→Title rule gets wrong.
 *
 * The new IA turns views into path segments, and a mechanical
 * "pre-game" → "Pre game" or "oauth" → "Oauth" reads as a typo in the one
 * place a user looks to know where they are.
 */
export const SEGMENT_LABELS: Record<string, string> = {
  // Tournament hub
  overview: "Overview",
  registration: "Registration",
  entries: "Entries",
  form: "Form",
  feed: "Sheets feed",
  "rank-autofill": "Rank autofill",
  teams: "Teams",
  roster: "Roster",
  draft: "Draft",
  bracket: "Bracket",
  matches: "Matches",
  encounters: "Encounters",
  standings: "Standings",
  reports: "Reports",
  parsed: "Parsed maps",
  logs: "Logs",
  // Settings sections
  settings: "Settings",
  general: "General",
  rules: "Rules & scoring",
  schedule: "Schedule",
  "pre-game": "Pre-game phase",
  "report-form": "Match report form",
  links: "Links",
  challonge: "Challonge",
  discord: "Discord",
  preview: "Preview access",
  danger: "Danger zone",
  branding: "Branding",
  // "Visibility & SEO" no longer describes it: the SEO text now sits with the
  // subdomain and the custom domain, where "what does this workspace answer
  // on" is decided.
  visibility: "Visibility",
  domain: "Domain",
  divisions: "Divisions",
  // `/admin/settings/divisions/v/12` — the segment is `v` only because the
  // route is short enough to type; kebab→Title would render it as "V".
  v: "Version",
  // Registration AND balancer scopes now live in one table, so the label cannot
  // name just one of them.
  statuses: "Player statuses",
  "sub-roles": "Sub-roles",
  subscriptions: "Subscriptions",
  import: "Import",
  // Platform
  content: "Game content",
  heroes: "Heroes",
  maps: "Maps",
  gamemodes: "Gamemodes",
  unresolved: "Unresolved names",
  collectors: "Collectors",
  rank: "Rank",
  streams: "Streams",
  access: "Access",
  accounts: "Accounts",
  roles: "Roles",
  permissions: "Permissions",
  "api-keys": "API keys",
  oauth: "OAuth",
  sessions: "Sessions",
  members: "Members",
  people: "People",
  workspaces: "Workspaces",
  audit: "Audit log",
  tournaments: "Tournaments",
  achievements: "Achievements",
  new: "New",
};

/** Label for one path segment: the dictionary first, kebab→Title as fallback. */
export function breadcrumbSegmentLabel(segment: string): string {
  const known = SEGMENT_LABELS[segment];
  if (known) return known;
  if (/^\d+$/.test(segment)) return "Details";

  const normalized = segment.replace(/-/g, " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

/**
 * The `/admin/<section>/<id>` crumb to resolve, if this path has one.
 *
 * `segments` excludes the leading "admin" segment's own crumb the same way
 * `AdminBreadcrumb` slices it: index 0 is "admin".
 */
export function getBreadcrumbEntityRef(
  segments: string[],
  workspaceId: number | null,
): { queryKey: readonly unknown[]; segmentIndex: number } | null {
  const [, section, id] = segments;
  if (!id || !/^\d+$/.test(id)) return null;

  const buildKey = section ? BREADCRUMB_ENTITIES[section] : undefined;
  if (!buildKey) return null;

  return { queryKey: buildKey(Number(id), workspaceId), segmentIndex: 2 };
}
