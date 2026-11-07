import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";

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
const BREADCRUMB_ENTITIES: Record<
  string,
  (id: number, workspaceId: number | null) => readonly unknown[]
> = {
  tournaments: (id) => getTournamentWorkspaceQueryKeys(id).tournament,
  // Same key as the team workspace query (admin/teams/[id]/page.tsx).
  teams: (id) => adminQueryKeys.team(id),
  people: (id) => adminQueryKeys.person(id),
  achievements: (id, workspaceId) => achievementQueryKeys.rule(workspaceId, id),
  workspaces: (id) => adminQueryKeys.workspace(id),
};

/**
 * Labels for path segments the kebab→Title rule gets wrong.
 *
 * The new IA turns views into path segments, and a mechanical
 * "pre-game" → "Pre game" or "oauth" → "Oauth" reads as a typo in the one
 * place a user looks to know where they are.
 */
const SEGMENT_LABELS: Record<string, string> = {
  // Tournament hub
  overview: "breadcrumbOverview",
  registration: "breadcrumbRegistration",
  entries: "breadcrumbEntries",
  feed: "breadcrumbFeed",
  "rank-autofill": "breadcrumbRankAutofill",
  teams: "breadcrumbTeams",
  roster: "breadcrumbRoster",
  draft: "breadcrumbDraft",
  bracket: "breadcrumbBracket",
  matches: "breadcrumbMatches",
  encounters: "breadcrumbEncounters",
  rooms: "breadcrumbRooms",
  standings: "breadcrumbStandings",
  reports: "breadcrumbReports",
  parsed: "breadcrumbParsed",
  logs: "breadcrumbLogs",
  // Settings sections
  settings: "breadcrumbSettings",
  general: "breadcrumbGeneral",
  rules: "breadcrumbRules",
  schedule: "breadcrumbSchedule",
  "pre-game": "breadcrumbPreGame",
  "report-form": "breadcrumbReportForm",
  links: "breadcrumbLinks",
  challonge: "breadcrumbChallonge",
  discord: "breadcrumbDiscord",
  preview: "breadcrumbPreview",
  danger: "breadcrumbDanger",
  branding: "breadcrumbBranding",
  // "Visibility & SEO" no longer describes it: the SEO text now sits with the
  // subdomain and the custom domain, where "what does this workspace answer
  // on" is decided.
  visibility: "breadcrumbVisibility",
  domain: "breadcrumbDomain",
  divisions: "breadcrumbDivisions",
  // `/admin/settings/divisions/v/12` — the segment is `v` only because the
  // route is short enough to type; kebab→Title would render it as "V".
  v: "breadcrumbVersion",
  // Registration AND balancer scopes now live in one table, so the label cannot
  // name just one of them.
  statuses: "breadcrumbStatuses",
  "sub-roles": "breadcrumbSubRoles",
  subscriptions: "breadcrumbSubscriptions",
  import: "breadcrumbImport",
  // Platform
  content: "breadcrumbContent",
  heroes: "breadcrumbHeroes",
  maps: "breadcrumbMaps",
  gamemodes: "breadcrumbGamemodes",
  unresolved: "breadcrumbUnresolved",
  collectors: "breadcrumbCollectors",
  rank: "breadcrumbRank",
  streams: "breadcrumbStreams",
  access: "breadcrumbAccess",
  accounts: "breadcrumbAccounts",
  roles: "breadcrumbRoles",
  permissions: "breadcrumbPermissions",
  "api-keys": "breadcrumbApiKeys",
  oauth: "breadcrumbOauth",
  sessions: "breadcrumbSessions",
  members: "breadcrumbMembers",
  people: "breadcrumbPeople",
  workspaces: "breadcrumbWorkspaces",
  audit: "breadcrumbAudit",
  tournaments: "breadcrumbTournaments",
  achievements: "breadcrumbAchievements",
  announcements: "breadcrumbAnnouncements",
  notifications: "breadcrumbNotifications",
  ranks: "breadcrumbRanks",
  quota: "breadcrumbQuota",
  "registration-forms": "breadcrumbRegistrationForms",
  scoring: "breadcrumbScoring",
  admission: "breadcrumbAdmission",
  flow: "breadcrumbFlow",
  "game-content": "breadcrumbContent",
  new: "breadcrumbNew",
};

/** Label for one path segment: the dictionary first, kebab→Title as fallback. */
export function breadcrumbSegmentLabel(segment: string, translate?: (key: string) => string): string {
  const known = SEGMENT_LABELS[segment];
  if (known && translate) return translate(known);
  if (known) return known;
  if (/^\d+$/.test(segment)) return translate?.("breadcrumbDetails") ?? segment;

  const normalized = segment.replace(/-/g, " ");
  return translate?.("breadcrumbUnknown") ?? normalized;
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
